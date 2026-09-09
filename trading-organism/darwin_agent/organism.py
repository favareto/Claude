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
from darwin_agent.strategist import Strategist, TrackRecord
from darwin_agent.utils.config import AgentConfig

STATE_FILE = "data/population.json"


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


class Organism:
    def __init__(self, base_config: AgentConfig, symbols: List[str],
                 real_adapter_factory: Optional[Callable[[dict], object]] = None,
                 state_file: str = STATE_FILE):
        self.base_config = base_config
        self.symbols = symbols
        self._next_symbol_idx = 0
        self.strategist = Strategist(base_config.risk)
        self._real_adapter_factory = real_adapter_factory
        self.state_file = state_file

        self.agents: Dict[str, DarwinAgentV2] = {}
        self.records: Dict[str, RobotRecord] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # ── Nascimento / clonagem / morte ──────────────────────────────

    def _pick_symbol(self) -> str:
        symbol = self.symbols[self._next_symbol_idx % len(self.symbols)]
        self._next_symbol_idx += 1
        return symbol

    def _new_config(self, symbol: str) -> AgentConfig:
        cfg = copy.deepcopy(self.base_config)
        cfg.symbol = symbol
        return cfg

    async def spawn_root(self, symbol: Optional[str] = None,
                         strategy_name: str = "momentum") -> str:
        """Nasce um robô raiz (sem pai), especialista em `symbol` +
        `strategy_name`. Uso direto (CLI/debug); o caminho "oficial" pra
        nascimento de robôs raiz é `propose_and_spawn`, via uma proposta do
        Investigador validada pelo Estrategista."""
        symbol = symbol or self._pick_symbol()
        robot_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(robot_id, symbol, strategy_name, parent=None)
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

    async def propose_and_spawn(self, proposal: StrategyProposal,
                                symbol: Optional[str] = None) -> tuple:
        """Fluxo Investigador -> Estrategista -> nascimento: cada proposta
        trazida pelo Investigador e APROVADA pelo Estrategista (camada 1)
        gera exatamente um avatar novo. Retorna (robot_id ou None, motivo).
        O Estrategista pode recusar mesmo uma proposta bem formada, com
        base no histórico real de robôs anteriores com essa combinação."""
        symbol = symbol or proposal.asset_hint or self._pick_symbol()
        track_record = self._track_record(proposal.implementation, symbol)
        ok, reason = self.strategist.validate_proposal(proposal, symbol, track_record)
        if not ok:
            return None, reason

        robot_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(robot_id, symbol, proposal.implementation, parent=None,
                          strategy_source=f"{proposal.name} — {proposal.source}")
        return robot_id, reason

    async def _spawn(self, robot_id: str, symbol: str, strategy_name: str,
                     parent: Optional[DarwinAgentV2], strategy_source: str = ""):
        cfg = self._new_config(symbol)
        agent = DarwinAgentV2(
            config=cfg,
            strategy_name=strategy_name,
            robot_id=robot_id,
            strategist=self.strategist,
            parent_id=parent.robot_id if parent else None,
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
                strategy_source=strategy_source,
            )
            self.tasks[robot_id] = asyncio.create_task(agent.run())
        self._save_state()

    async def _handle_clone(self, parent: DarwinAgentV2):
        clone_id = f"r-{uuid.uuid4().hex[:8]}"
        parent_rec = self.records.get(parent.robot_id)
        await self._spawn(clone_id, parent.symbol, parent.strategy_name, parent,
                          strategy_source=parent_rec.strategy_source if parent_rec else "")

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
        data = {
            "updated_at": _utcnow().isoformat(),
            "population_alive": len(alive),
            "population_total": len(self.records),
            "total_capital_alive": round(sum(r.capital for r in alive), 2),
            "robots": [asdict(r) for r in self.records.values()],
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
