"""Macro-organismo — orquestrador central da população de robôs.

É a ÚNICA fonte de verdade sobre quem existe, saldo de cada um, quem está
operando, e o histórico de quem já foi eliminado ou gerou clones (ver
CLAUDE.md). Persiste o estado em `data/population.json`; simulação e
visualização devem sempre ler esse arquivo, nunca ter lógica de decisão
própria.

Roda N robôs (`DarwinAgentV2`) como tasks assíncronas concorrentes — quando
um clona, um novo robô nasce como task irmã; quando um morre, sai da
população viva e vira só um registro histórico.
"""

import asyncio
import copy
import json
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from darwin_agent.core.agent_v2 import DarwinAgentV2
from darwin_agent.investigator import StrategyProposal
from darwin_agent.professor import Professor
from darwin_agent.strategist import Strategist, StrategyReview, TrackRecord
from darwin_agent.utils.config import AgentConfig

STATE_FILE = "data/population.json"

# Quanto menos frequente o timeframe, menos sentido faz ficar checando o
# mercado toda hora — um robô semanal não precisa de heartbeat de 60s. Só
# usado quando Organism(heartbeat_by_timeframe=True) (produção/real); em
# simulação o heartbeat vem direto de base_config, sem essa escala, pra
# controlar a velocidade do teste.
HEARTBEAT_BY_TIMEFRAME = {
    "1m": 30, "5m": 60, "15m": 180, "1h": 900, "4h": 1800, "1d": 3600, "1w": 21600,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RobotRecord:
    id: str
    symbol: str
    strategy_name: str
    parent_id: Optional[str]
    born_at: str
    status: str = "alive"  # alive | dead
    capital: float = 0.0
    peak_capital: float = 0.0
    drawdown_pct: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    clones_generated: int = 0
    died_at: Optional[str] = None
    cause_of_death: Optional[str] = None
    strategy_source: str = ""
    strategy_id: str = ""
    timeframe: str = ""
    strategy_params: dict = field(default_factory=dict)
    # Descrição da estratégia (StrategyProposal original) — pra explicar
    # "como esse robô opera" no painel, não só o nome curto.
    strategy_indicators: List[str] = field(default_factory=list)
    strategy_entry_rule: str = ""
    strategy_exit_rule: str = ""
    strategy_risk_management: str = ""


class Organism:
    def __init__(self, base_config: AgentConfig, symbols: List[str],
                 real_adapter_factory: Optional[Callable[[dict], object]] = None,
                 state_file: str = STATE_FILE,
                 heartbeat_by_timeframe: bool = False):
        self.base_config = base_config
        self.symbols = symbols
        self._next_symbol_idx = 0
        self.strategist = Strategist(base_config.risk)
        self.professor = Professor()
        self._real_adapter_factory = real_adapter_factory
        self.state_file = state_file
        self.heartbeat_by_timeframe = heartbeat_by_timeframe

        self.agents: Dict[str, DarwinAgentV2] = {}
        self.records: Dict[str, RobotRecord] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # ── Nascimento / clonagem / morte ──────────────────────────────

    def _pick_symbol(self) -> str:
        symbol = self.symbols[self._next_symbol_idx % len(self.symbols)]
        self._next_symbol_idx += 1
        return symbol

    def _new_config(self, symbol: str, timeframe: Optional[str] = None) -> AgentConfig:
        cfg = copy.deepcopy(self.base_config)
        cfg.symbol = symbol
        if timeframe:
            cfg.scan_timeframe = timeframe
            if self.heartbeat_by_timeframe:
                cfg.heartbeat_interval = HEARTBEAT_BY_TIMEFRAME.get(timeframe, cfg.heartbeat_interval)
        return cfg

    async def spawn_root(self, symbol: Optional[str] = None,
                         strategy_name: str = "momentum",
                         timeframe: str = "15m") -> str:
        """Nasce um robô raiz (sem pai), especialista em `symbol` +
        `strategy_name` + `timeframe`. Uso direto (CLI/debug); o caminho
        "oficial" pra nascimento de robôs raiz é `propose_and_spawn`, via
        uma proposta do Investigador validada pelo Estrategista."""
        symbol = symbol or self._pick_symbol()
        robot_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(robot_id, symbol, strategy_name, parent=None,
                          timeframe=timeframe, strategy_id=f"{strategy_name}:manual-spawn")
        return robot_id

    def _track_record(self, strategy_name: str, symbol: str) -> TrackRecord:
        """Histórico real dessa combinação (estratégia, ativo) na população
        — é isso que dá ao Estrategista base pra reprovar por mérito, não
        só por schema."""
        tr = TrackRecord()
        for r in self.records.values():
            if r.strategy_name != strategy_name or r.symbol != symbol:
                continue
            tr.attempts += 1
            tr.clones += r.clones_generated
            if r.status == "dead":
                tr.deaths += 1
        return tr

    def _all_track_records(self) -> List[dict]:
        """O mesmo histórico que o Estrategista usa pra julgar
        (`_track_record`), pra TODA combinação (estratégia, ativo) que já
        existiu — exposto no estado salvo pra o painel mostrar "o
        Estrategista já viu isso Nx, deu certo Y vezes"."""
        pairs = sorted({(r.strategy_name, r.symbol) for r in self.records.values()})
        out = []
        for strategy_name, symbol in pairs:
            tr = self._track_record(strategy_name, symbol)
            out.append({
                "strategy_name": strategy_name, "symbol": symbol,
                "attempts": tr.attempts, "deaths": tr.deaths, "clones": tr.clones,
                "death_rate": round(tr.death_rate, 4),
            })
        return out

    async def propose_and_spawn(self, proposal: StrategyProposal,
                                symbol: Optional[str] = None) -> tuple:
        """Fluxo Investigador -> Estrategista -> nascimento: cada proposta
        trazida pelo Investigador e APROVADA pelo Estrategista gera
        exatamente um avatar novo. Retorna (robot_id ou None, motivo). Duas
        camadas de julgamento, qualquer uma pode recusar:
        1. Ranking (`leaderboard`): a proposta entra nas 500 estratégias
           ativas? Se o ranking está cheio, só entra sobrepondo a pior.
        2. Mérito por ativo (`TrackRecord`): mesmo já estando no ranking,
           essa combinação específica (estratégia+ativo) pode estar com
           histórico ruim o bastante pra recusar mais uma tentativa ali.
        """
        symbol = symbol or proposal.asset_hint or self._pick_symbol()

        admitted, admit_reason = self.strategist.consider_new_strategy(proposal)
        if not admitted:
            return None, admit_reason

        track_record = self._track_record(proposal.implementation, symbol)
        ok, reason = self.strategist.validate_proposal(proposal, symbol, track_record)
        if not ok:
            return None, reason

        # Professor monta o currículo: pega a estratégia genérica e adapta
        # os parâmetros pro ativo específico deste robô (ver professor.py).
        curriculum = self.professor.build_curriculum(proposal, symbol)

        robot_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(robot_id, symbol, proposal.implementation, parent=None,
                          strategy_source=f"{proposal.name} — {proposal.source}",
                          strategy_id=proposal.strategy_id, timeframe=proposal.timeframe,
                          strategy_params=curriculum,
                          strategy_indicators=list(proposal.indicators),
                          strategy_entry_rule=proposal.entry_rule,
                          strategy_exit_rule=proposal.exit_rule,
                          strategy_risk_management=proposal.risk_management)
        self.strategist.register_strategy_attempt(proposal.strategy_id)
        return robot_id, f"{admit_reason} | {reason}"

    async def _spawn(self, robot_id: str, symbol: str, strategy_name: str,
                     parent: Optional[DarwinAgentV2], strategy_source: str = "",
                     strategy_id: str = "", timeframe: str = "15m",
                     strategy_params: Optional[dict] = None,
                     strategy_indicators: Optional[List[str]] = None,
                     strategy_entry_rule: str = "", strategy_exit_rule: str = "",
                     strategy_risk_management: str = ""):
        cfg = self._new_config(symbol, timeframe)
        agent = DarwinAgentV2(
            config=cfg,
            strategy_name=strategy_name,
            robot_id=robot_id,
            strategist=self.strategist,
            parent_id=parent.robot_id if parent else None,
            strategy_params=strategy_params,
            on_clone=self._handle_clone,
            on_death=self._handle_death,
            real_adapter_factory=self._real_adapter_factory,
        )
        if parent is not None:
            agent.inherit_brain_from(parent)

        async with self._lock:
            self.agents[robot_id] = agent
            self.records[robot_id] = RobotRecord(
                id=robot_id, symbol=symbol, strategy_name=strategy_name,
                parent_id=parent.robot_id if parent else None,
                born_at=_utcnow().isoformat(),
                capital=cfg.starting_capital, peak_capital=cfg.starting_capital,
                strategy_source=strategy_source, strategy_id=strategy_id,
                timeframe=timeframe, strategy_params=strategy_params or {},
                strategy_indicators=strategy_indicators or [],
                strategy_entry_rule=strategy_entry_rule, strategy_exit_rule=strategy_exit_rule,
                strategy_risk_management=strategy_risk_management,
            )
            self.tasks[robot_id] = asyncio.create_task(agent.run())
        self._save_state()

    async def _handle_clone(self, parent: DarwinAgentV2):
        clone_id = f"r-{uuid.uuid4().hex[:8]}"
        parent_rec = self.records.get(parent.robot_id)
        await self._spawn(clone_id, parent.symbol, parent.strategy_name, parent,
                          strategy_source=parent_rec.strategy_source if parent_rec else "",
                          strategy_id=parent_rec.strategy_id if parent_rec else "",
                          timeframe=parent_rec.timeframe if parent_rec else "15m",
                          strategy_params=parent.strategy_params,
                          strategy_indicators=parent_rec.strategy_indicators if parent_rec else [],
                          strategy_entry_rule=parent_rec.strategy_entry_rule if parent_rec else "",
                          strategy_exit_rule=parent_rec.strategy_exit_rule if parent_rec else "",
                          strategy_risk_management=parent_rec.strategy_risk_management if parent_rec else "")
        # Clonagem (+70%) é o sinal de sucesso — promove a estratégia no ranking.
        if parent_rec and parent_rec.strategy_id:
            self.strategist.promote_strategy(parent_rec.strategy_id)

    async def _handle_death(self, robot: DarwinAgentV2, cause: str):
        async with self._lock:
            rec = self.records.get(robot.robot_id)
            if rec:
                rec.status = "dead"
                rec.died_at = _utcnow().isoformat()
                rec.cause_of_death = cause
                rec.capital = robot.health.current_capital
                rec.peak_capital = robot.health.peak_capital
                rec.drawdown_pct = robot.health.current_drawdown_pct
                rec.total_trades = robot.health.total_trades
                rec.win_rate = robot.health.win_rate
                rec.clones_generated = robot.clones_generated
            self.strategist.remove_robot(robot.robot_id)
            self.agents.pop(robot.robot_id, None)
            self.tasks.pop(robot.robot_id, None)
        # Eliminação (-60% do pico) rebaixa a estratégia no ranking.
        if rec and rec.strategy_id:
            self.strategist.demote_strategy(rec.strategy_id)
        self._save_state()

    # ── Estado / persistência ───────────────────────────────────────

    def _sync_alive_records(self):
        for rid, agent in self.agents.items():
            rec = self.records.get(rid)
            if not rec:
                continue
            rec.capital = agent.health.current_capital
            rec.peak_capital = agent.health.peak_capital
            rec.drawdown_pct = agent.health.current_drawdown_pct
            rec.total_trades = agent.health.total_trades
            rec.win_rate = agent.health.win_rate
            rec.clones_generated = agent.clones_generated

    def _save_state(self):
        self._sync_alive_records()
        alive = [r for r in self.records.values() if r.status == "alive"]
        dead = [r for r in self.records.values() if r.status == "dead"]
        leaderboard = self.strategist.leaderboard
        data = {
            "updated_at": _utcnow().isoformat(),
            "population_alive": len(alive),
            "population_total": len(self.records),
            "total_capital_alive": round(sum(r.capital for r in alive), 2),
            "robots": [asdict(r) for r in self.records.values()],
            "leaderboard_size": len(leaderboard),
            "leaderboard_capacity": leaderboard.capacity,
            "leaderboard_top": [e.to_dict() for e in leaderboard.top(20)],
            "track_records": self._all_track_records(),
        }
        directory = os.path.dirname(self.state_file) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.state_file)

    def summary(self) -> dict:
        self._sync_alive_records()
        alive = [r for r in self.records.values() if r.status == "alive"]
        dead = [r for r in self.records.values() if r.status == "dead"]
        return {
            "alive": len(alive),
            "dead": len(dead),
            "total_capital_alive": round(sum(r.capital for r in alive), 2),
            "total_clones": sum(r.clones_generated for r in self.records.values()),
        }

    # ── Execução ─────────────────────────────────────────────────

    async def run_until(self, condition: Callable[["Organism"], bool],
                        check_interval: float = 1.0, save_interval_ticks: int = 5):
        """Roda a população até `condition(self)` retornar True ou a
        população inteira ser extinta."""
        tick = 0
        while self.agents and not condition(self):
            await asyncio.sleep(check_interval)
            tick += 1
            if tick % save_interval_ticks == 0:
                self._save_state()
        self._save_state()

    async def shutdown(self):
        for task in list(self.tasks.values()):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def poll_strategy_feed(self, feed_dir: str = "data/strategy_feed",
                                 reviews_dir: str = "data/strategy_reviews",
                                 interval: float = 30.0, review_grace_seconds: float = 60.0):
        """Roda pra sempre (chamar como task em paralelo com run_until).
        Observa `feed_dir` — onde `investigator_research.py` (script
        separado, pesquisa contínua de verdade via API da Anthropic + busca
        web) grava propostas novas — e injeta cada arquivo novo na
        população via `propose_and_spawn`. É assim que a pesquisa (lenta,
        externa) fica desacoplada do loop de trading (rápido, contínuo).

        Antes de nascer, espera até `review_grace_seconds` por uma revisão
        do Estrategista em `reviews_dir` (`strategist_research.py`, também
        um script separado — pesquisa em fonte aberta, pode aprovar,
        recusar ou sugerir mudança de parâmetros). Se a revisão não chegar
        a tempo, segue sem ela — a revisão é um reforço, não um bloqueio
        permanente (ver `strategist.py: Strategist.apply_review`)."""
        processed = set()
        pending_since: Dict[str, float] = {}
        os.makedirs(feed_dir, exist_ok=True)
        while True:
            now = asyncio.get_event_loop().time()
            for fname in sorted(os.listdir(feed_dir)):
                if not fname.endswith(".json") or fname in processed:
                    continue
                pending_since.setdefault(fname, now)

                review = None
                review_path = os.path.join(reviews_dir, fname)
                if os.path.exists(review_path):
                    try:
                        with open(review_path) as f:
                            review = StrategyReview(**json.load(f))
                    except Exception as e:
                        print(f"[Estrategista] review '{fname}' inválida, ignorando: {e}")
                elif now - pending_since[fname] < review_grace_seconds:
                    continue  # ainda dentro da janela de graça, espera mais um pouco

                processed.add(fname)
                path = os.path.join(feed_dir, fname)
                try:
                    with open(path) as f:
                        data = json.load(f)
                    proposal = StrategyProposal(**data)
                except Exception as e:
                    print(f"[Investigador] '{fname}' inválido, ignorando: {e}")
                    continue

                proposal, reject_reason = self.strategist.apply_review(proposal, review)
                if reject_reason:
                    print(f"[Estrategista] '{proposal.name}' -> {reject_reason}")
                    continue
                if review is None:
                    print(f"[Investigador] '{proposal.name}' seguiu sem revisão do Estrategista (prazo esgotado)")
                elif review.verdict == "revise":
                    print(f"[Estrategista] '{proposal.name}' revisada: {review.reason[:100]}")

                symbol = proposal.asset_hint or self._pick_symbol()
                robot_id, reason = await self.propose_and_spawn(proposal, symbol=symbol)
                print(f"[Investigador] '{proposal.name}' -> {reason}")
            await asyncio.sleep(interval)
