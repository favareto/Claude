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

from darwin_agent.backtest import BacktestResult, run_backtest
from darwin_agent.core.agent_v2 import DarwinAgentV2
from darwin_agent.investigator import StrategyProposal
from darwin_agent.leaderboard import LeaderboardEntry
from darwin_agent.markets.base import TimeFrame
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
    # Resumo do backtest sobre candles históricos ANTES do robô nascer
    # (Sala de Risco, camada 0 — ver backtest.py e Strategist.judge_backtest).
    # None quando não havia dados históricos suficientes na hora.
    backtest_summary: Optional[dict] = None


class Organism:
    def __init__(self, base_config: AgentConfig, symbols: List[str],
                 real_adapter_factory: Optional[Callable[[dict], object]] = None,
                 state_file: str = STATE_FILE,
                 heartbeat_by_timeframe: bool = False,
                 asset_classes: Optional[Dict[str, str]] = None):
        """`asset_classes`: symbol -> nome do mercado em `base_config.markets`
        (ex: "crypto" ou "stocks") — pra saber qual adapter cada robô deve
        usar quando o universo mistura ativos de fontes diferentes (ver
        `_new_config`, `markets/yahoo.py`). Símbolo ausente do mapa vira
        "crypto" por padrão (mantém compatibilidade com quem só passa uma
        lista de símbolos de cripto, como sempre foi)."""
        self.base_config = base_config
        self.symbols = symbols
        self._asset_classes = asset_classes or {}
        self._next_symbol_idx = 0
        self.strategist = Strategist(base_config.risk)
        self.professor = Professor()
        self._real_adapter_factory = real_adapter_factory
        self.state_file = state_file
        self.history_file = os.path.join(os.path.dirname(state_file) or ".", "history.jsonl")
        # Estado completo pra RETOMAR a população depois de um restart do
        # processo (diferente de population.json, que é só o retrato pro
        # painel) — ver save_full_state/resume_from_state.
        self.full_state_file = os.path.join(os.path.dirname(state_file) or ".", "organism_state.json")
        # Log de eventos — o que está ACONTECENDO (nasceu, morreu, clonou,
        # foi recusado e por quê, decisões da Mesa), pra janela separada
        # `/eventos` do painel (ver dashboard.py, CLAUDE.md). Diferente de
        # population.json (o "agora") e history.jsonl (só capital) — aqui é
        # a linha do tempo em texto.
        self.events_file = os.path.join(os.path.dirname(state_file) or ".", "events.jsonl")
        self.heartbeat_by_timeframe = heartbeat_by_timeframe

        self.agents: Dict[str, DarwinAgentV2] = {}
        self.records: Dict[str, RobotRecord] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

        # Sala de Risco — pedidos de clonagem/otimização bloqueados por
        # teto (nicho ou população), esperando uma vaga liberar por morte
        # (ver `_handle_clone`/`_handle_death`/`_drain_pending_clones`).
        # Cada item: {kind: "clone"|"variant", base_robot_id, strategy_id,
        # symbol, timeframe, params (só variant), queued_at}.
        self._pending_clones: List[dict] = []

        # A Mesa — propostas de estratégia NOVA que já passaram por toda a
        # análise automática, esperando SUA aprovação (ver
        # `propose_and_spawn`/`approve_pending`/`reject_pending`). Clones
        # não passam por aqui, só estratégias novas pedindo cadeira.
        self._pending_approvals: Dict[str, dict] = {}
        self._last_root_proposal_at: Optional[datetime] = None

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

        # Universo multi-asset (crypto + ações/índices/commodities/futuros,
        # ver markets/yahoo.py): cada robô só deve conectar no mercado da
        # classe de ativo do SEU símbolo, nunca em todos os configurados —
        # um robô de AAPL não tem porque tentar falar com a Bybit.
        market_name = self._asset_classes.get(symbol, "crypto")
        for name, mc in cfg.markets.items():
            mc.enabled = mc.enabled and (name == market_name)
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

    # ── Sala de Risco — fatos sobre concentração (o Estrategista julga) ──

    def _niche_key(self, strategy_id: str, symbol: str) -> str:
        """Identifica uma "aposta repetida": mesma proposta exata
        (indicadores/params/nome — não só a família 'momentum') no mesmo
        ativo. Uma otimização (`suggest_optimization`) gera um `strategy_id`
        novo, logo vira um nicho próprio, com seu próprio teto."""
        return f"{strategy_id}|{symbol}"

    def _alive_count_in_niche(self, niche_key: str) -> int:
        return sum(1 for r in self.records.values()
                  if r.status == "alive" and self._niche_key(r.strategy_id, r.symbol) == niche_key)

    def _alive_count_total(self) -> int:
        return sum(1 for r in self.records.values() if r.status == "alive")

    def _best_in_niche(self, niche_key: str) -> Optional[RobotRecord]:
        """Robô vivo de maior capital nesse nicho — base pra uma otimização
        partir do que já provou ser o melhor, não de um membro qualquer."""
        candidates = [r for r in self.records.values()
                     if r.status == "alive" and self._niche_key(r.strategy_id, r.symbol) == niche_key]
        return max(candidates, key=lambda r: r.capital) if candidates else None

    def _risk_room_report(self) -> dict:
        """Visão da Sala de Risco pro painel: quanto da capacidade (por
        nicho e global) está em uso, e onde está a concentração — é a base
        pra decidir apertar/afrouxar os tetos no futuro."""
        alive = [r for r in self.records.values() if r.status == "alive"]
        niches: Dict[str, dict] = {}
        assets: Dict[str, dict] = {}
        for r in alive:
            nk = self._niche_key(r.strategy_id, r.symbol)
            n = niches.setdefault(nk, {
                "niche": nk, "strategy_name": r.strategy_name, "strategy_id": r.strategy_id,
                "symbol": r.symbol, "count": 0, "capital": 0.0,
            })
            n["count"] += 1
            n["capital"] = round(n["capital"] + r.capital, 2)
            a = assets.setdefault(r.symbol, {"symbol": r.symbol, "count": 0, "capital": 0.0})
            a["count"] += 1
            a["capital"] = round(a["capital"] + r.capital, 2)
        return {
            "population_alive": len(alive),
            "population_cap": self.strategist.MAX_POPULATION_ALIVE,
            "niche_cap": self.strategist.MAX_ROBOTS_PER_NICHE,
            "pending_count": len(self._pending_clones),
            "niches_at_cap": sum(1 for n in niches.values() if n["count"] >= self.strategist.MAX_ROBOTS_PER_NICHE),
            "by_niche": sorted(niches.values(), key=lambda n: -n["count"])[:30],
            "by_asset": sorted(assets.values(), key=lambda a: -a["count"])[:30],
        }

    def _table_report(self) -> dict:
        """A Mesa pro painel: quantas cadeiras ocupadas, quanto falta pra
        próxima janela de cadência, e a fila de aprovação com tudo que
        você precisa decidir — texto da estratégia, track record real, e
        por que o Estrategista acha que ela é vencedora."""
        alive_roots = self._alive_root_count()
        pending = sorted(self._pending_approvals.values(), key=lambda e: e["submitted_at"])
        minutes_since_last = None
        if self._last_root_proposal_at:
            minutes_since_last = (_utcnow() - self._last_root_proposal_at).total_seconds() / 60
        cooldown_ok, cooldown_reason = self.strategist.check_root_cooldown(minutes_since_last)
        return {
            # seats_occupied = vivas + pendentes (reservadas) — é essa soma
            # que o teto realmente checa (ver propose_and_spawn), não só
            # vivas, senão dava pra furar o teto enfileirando demais.
            "seats_occupied": alive_roots + len(pending),
            "seats_alive": alive_roots,
            "seats_pending": len(pending),
            "seats_max": self.strategist.MAX_ROOT_SEATS,
            "cooldown_ok": cooldown_ok,
            "cooldown_reason": cooldown_reason,
            "pending_approvals": pending,
        }

    async def _fetch_recent_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list:
        """Busca candles históricos reais (mesmo adapter que os robôs usam)
        — uma única vez, reaproveitado tanto pelo currículo do Professor
        (afinar parâmetros pela volatilidade real do ativo) quanto pelo
        backtest (Sala de Risco, camada 0). Não levanta exceção nem bloqueia
        o nascimento se não conseguir dados (rede fora do ar, símbolo novo
        demais): retorna lista vazia e quem chama segue sem essa camada."""
        try:
            # Multi-asset (crypto + ações/índices/commodities/futuros via
            # Yahoo Finance): tem que ser o mercado da classe de ativo DESSE
            # símbolo, não "o primeiro habilitado" — com dois mercados
            # habilitados ao mesmo tempo isso pegaria o adapter errado pra
            # metade dos símbolos (backtestaria AAPL com dado de cripto).
            market_name = self._asset_classes.get(symbol, "crypto")
            mc = self.base_config.markets.get(market_name)
            if mc is None or not mc.enabled:
                return []
            if self._real_adapter_factory:
                adapter = self._real_adapter_factory(mc)
            elif market_name == "stocks":
                from darwin_agent.markets.yahoo import YahooFinanceAdapter
                adapter = YahooFinanceAdapter({"testnet": mc.testnet})
            else:
                from darwin_agent.markets.crypto import BybitAdapter
                adapter = BybitAdapter({"api_key": mc.api_key, "api_secret": mc.api_secret, "testnet": mc.testnet})
            if not await adapter.connect():
                return []
            return await adapter.get_candles(symbol, self._resolve_timeframe(timeframe), limit=limit)
        except Exception as e:
            print(f"[Sala de Risco] candles históricos indisponíveis pra {symbol}: {e}")
            return []

    @staticmethod
    def _resolve_timeframe(timeframe: str) -> TimeFrame:
        try:
            return TimeFrame(timeframe)
        except ValueError:
            return TimeFrame.M15

    def _run_backtest(self, strategy_name: str, params: dict, symbol: str,
                      timeframe: str, candles: list) -> Optional[BacktestResult]:
        """Sala de Risco, camada 0 — roda `backtest.run_backtest` sobre
        candles já buscados (ver `_fetch_recent_candles`). Amostra menor
        que 80 candles não é suficiente pra uma janela deslizante útil."""
        if len(candles) < 80:
            return None
        return run_backtest(candles, strategy_name, params, symbol, self._resolve_timeframe(timeframe))

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

    def _alive_root_count(self) -> int:
        """Cadeiras ocupadas na mesa — robôs RAIZ (sem pai) vivos. Clones
        não contam (multiplicação de uma estratégia já sentada, não uma
        estratégia nova pedindo cadeira)."""
        return sum(1 for r in self.records.values() if r.status == "alive" and r.parent_id is None)

    async def propose_and_spawn(self, proposal: StrategyProposal,
                                symbol: Optional[str] = None,
                                bypass_root_cooldown: bool = False) -> tuple:
        """Fluxo Investigador -> Estrategista -> A MESA (aprovação humana)
        -> nascimento. Retorna (robot_id ou None, motivo) — mas note que
        numa proposta aprovada em tudo, `robot_id` ainda vem None: ela não
        nasce aqui, só entra na fila de `_pending_approvals` esperando
        você aprovar pelo painel (`approve_pending`/`reject_pending`).
        Só clones (`_handle_clone`) nascem automáticos; toda ESTRATÉGIA
        NOVA precisa da sua aprovação, decisão explícita do usuário.

        `bypass_root_cooldown=True` é só pro bootstrap inicial (encher as
        `MAX_ROOT_SEATS` cadeiras na largada) — depois disso, uma cadeira
        vaga só é oferecida de novo ao Investigador a cada
        `MIN_MINUTES_BETWEEN_ROOTS` minutos (ver `poll_strategy_feed`).

        Camadas de julgamento, qualquer uma pode recusar, na ordem (mais
        barata primeiro):
        1. Ranking (`leaderboard`): a proposta entra nas 500 estratégias
           ativas? Se o ranking está cheio, só entra sobrepondo a pior.
        2. Mérito por ativo (`TrackRecord`): mesmo já estando no ranking,
           essa combinação específica (estratégia+ativo) pode estar com
           histórico ruim o bastante pra recusar mais uma tentativa ali.
        3. Cadeira na mesa + cadência entre novos traders.
        4. Sala de Risco (teto de nicho/população) + backtest.
        5. Você — a decisão final, "por que essa estratégia merece
           sentar", fica na fila de aprovação.
        """
        symbol = symbol or proposal.asset_hint or self._pick_symbol()

        admitted, admit_reason = self.strategist.consider_new_strategy(proposal)
        if not admitted:
            self._log_event("refused_leaderboard", f"Estrategista recusou '{proposal.name}' em {symbol}: {admit_reason}",
                            proposal_name=proposal.name, symbol=symbol)
            return None, admit_reason

        track_record = self._track_record(proposal.implementation, symbol)
        ok, reason = self.strategist.validate_proposal(proposal, symbol, track_record)
        if not ok:
            self._log_event("refused_track_record", f"Estrategista recusou '{proposal.name}' em {symbol}: {reason}",
                            proposal_name=proposal.name, symbol=symbol)
            return None, reason

        # A Mesa — cadeira vaga + cadência, antes de gastar tempo com
        # backtest (checagem cara por último). Conta vivas + PENDENTES de
        # aprovação juntas — sem isso, dava pra enfileirar 20 propostas e
        # aprovar todas, furando o teto de 10 (nada bloquearia no momento
        # da fila, só quando já fosse tarde demais).
        occupied_or_reserved = self._alive_root_count() + len(self._pending_approvals)
        ok, seat_reason = self.strategist.check_seat_availability(occupied_or_reserved)
        if not ok:
            self._log_event("refused_seat", f"'{proposal.name}' em {symbol} recusada: {seat_reason}",
                            proposal_name=proposal.name, symbol=symbol)
            return None, seat_reason
        minutes_since_last = None
        if self._last_root_proposal_at:
            minutes_since_last = (_utcnow() - self._last_root_proposal_at).total_seconds() / 60
        ok, cooldown_reason = self.strategist.check_root_cooldown(
            None if bypass_root_cooldown else minutes_since_last)
        if not ok:
            self._log_event("refused_cooldown", f"'{proposal.name}' em {symbol} recusada: {cooldown_reason}",
                            proposal_name=proposal.name, symbol=symbol)
            return None, cooldown_reason

        # Sala de Risco — teto global e de concentração por nicho.
        ok, cap_reason = self.strategist.check_population_capacity(self._alive_count_total())
        if not ok:
            self._log_event("refused_capacity", f"'{proposal.name}' em {symbol} recusada: {cap_reason}",
                            proposal_name=proposal.name, symbol=symbol)
            return None, cap_reason
        niche_key = self._niche_key(proposal.strategy_id, symbol)
        ok, cap_reason = self.strategist.check_niche_capacity(self._alive_count_in_niche(niche_key))
        if not ok:
            self._log_event("refused_capacity", f"'{proposal.name}' em {symbol} recusada: {cap_reason}",
                            proposal_name=proposal.name, symbol=symbol)
            return None, cap_reason

        # Busca candles históricos reais UMA vez — o Professor usa pra
        # afinar o currículo pela volatilidade real (não só a heurística
        # major/alt) e o backtest reaproveita os mesmos candles logo abaixo.
        candles = await self._fetch_recent_candles(symbol, proposal.timeframe)

        # Professor monta o currículo: pega a estratégia genérica e adapta
        # os parâmetros pro ativo específico deste robô (ver professor.py).
        curriculum = self.professor.build_curriculum(proposal, symbol, recent_candles=candles)

        # Sala de Risco, camada 0 — backtest sobre candles históricos ANTES
        # de arriscar capital real (ver backtest.py, Strategist.judge_backtest).
        backtest_result = self._run_backtest(proposal.implementation, curriculum, symbol, proposal.timeframe, candles)
        ok, bt_reason = self.strategist.judge_backtest(backtest_result)
        if not ok:
            self._log_event("refused_backtest", f"'{proposal.name}' em {symbol} recusada: {bt_reason}",
                            proposal_name=proposal.name, symbol=symbol)
            return None, bt_reason

        approval_id = self._queue_for_approval(
            proposal=proposal, symbol=symbol, curriculum=curriculum, track_record=track_record,
            backtest_result=backtest_result, admit_reason=admit_reason, validate_reason=reason,
            backtest_reason=bt_reason,
        )
        self._last_root_proposal_at = _utcnow()
        self._log_event("queued_approval", f"'{proposal.name}' em {symbol} passou em toda a análise — aguardando sua aprovação",
                        proposal_name=proposal.name, symbol=symbol, approval_id=approval_id)
        return None, (f"Aprovada em toda a análise — aguardando você na mesa (id={approval_id}) | "
                      f"{admit_reason} | {reason} | {bt_reason}")

    def _queue_for_approval(self, proposal: StrategyProposal, symbol: str, curriculum: dict,
                            track_record: TrackRecord, backtest_result: Optional[BacktestResult],
                            admit_reason: str, validate_reason: str, backtest_reason: str) -> str:
        """A Mesa — guarda tudo que você precisa pra decidir: o texto da
        estratégia (nome/indicadores/regras), o track record real dessa
        combinação (estratégia+ativo) até agora, e por que o Estrategista
        acha que ela é vencedora (as 3 razões que já passou). Nada disso
        nasce até `approve_pending`."""
        approval_id = f"a-{uuid.uuid4().hex[:8]}"
        self._pending_approvals[approval_id] = {
            "id": approval_id,
            "proposal": asdict(proposal),
            "symbol": symbol,
            "curriculum": curriculum,
            "track_record": {
                "attempts": track_record.attempts, "deaths": track_record.deaths,
                "clones": track_record.clones, "death_rate": round(track_record.death_rate, 4),
            },
            "backtest_summary": asdict(backtest_result) if backtest_result else None,
            "admit_reason": admit_reason,
            "validate_reason": validate_reason,
            "backtest_reason": backtest_reason,
            "submitted_at": _utcnow().isoformat(),
        }
        return approval_id

    async def approve_pending(self, approval_id: str) -> tuple:
        """Você aprovou — a proposta finalmente vira um robô de verdade,
        sentando na cadeira que estava reservada pra ela."""
        entry = self._pending_approvals.pop(approval_id, None)
        if not entry:
            return None, "Proposta não encontrada (já aprovada, recusada, ou id inválido)"
        proposal = StrategyProposal(**entry["proposal"])
        robot_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(robot_id, entry["symbol"], proposal.implementation, parent=None,
                          strategy_source=f"{proposal.name} — {proposal.source}",
                          strategy_id=proposal.strategy_id, timeframe=proposal.timeframe,
                          strategy_params=entry["curriculum"],
                          strategy_indicators=list(proposal.indicators),
                          strategy_entry_rule=proposal.entry_rule,
                          strategy_exit_rule=proposal.exit_rule,
                          strategy_risk_management=proposal.risk_management,
                          backtest_summary=entry.get("backtest_summary"))
        self.strategist.register_strategy_attempt(proposal.strategy_id)
        self._log_event("approved", f"Você aprovou '{proposal.name}' — {robot_id} sentou na mesa especialista em {proposal.implementation}/{entry['symbol']}",
                        robot_id=robot_id, proposal_name=proposal.name, symbol=entry["symbol"])
        return robot_id, f"Aprovado por você — sentou na mesa especialista em {proposal.implementation}/{entry['symbol']}"

    def reject_pending(self, approval_id: str, note: str = "") -> bool:
        """Você recusou — descarta, libera a vaga reservada (que nem
        tinha efetivamente ocupado nada, só estava na fila)."""
        entry = self._pending_approvals.pop(approval_id, None)
        if entry:
            note_txt = f" — {note}" if note else ""
            print(f"[A Mesa] recusado por você: '{entry['proposal']['name']}' em {entry['symbol']}{note_txt}")
            self._log_event("rejected", f"Você recusou '{entry['proposal']['name']}' em {entry['symbol']}{note_txt}",
                            proposal_name=entry["proposal"]["name"], symbol=entry["symbol"])
        return entry is not None

    async def _spawn(self, robot_id: str, symbol: str, strategy_name: str,
                     parent: Optional[DarwinAgentV2], strategy_source: str = "",
                     strategy_id: str = "", timeframe: str = "15m",
                     strategy_params: Optional[dict] = None,
                     strategy_indicators: Optional[List[str]] = None,
                     strategy_entry_rule: str = "", strategy_exit_rule: str = "",
                     strategy_risk_management: str = "",
                     backtest_summary: Optional[dict] = None):
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
                backtest_summary=backtest_summary,
            )
            self.tasks[robot_id] = asyncio.create_task(agent.run())
        is_variant = "otimização automática" in (strategy_source or "")
        kind = "optimization" if is_variant else ("clone" if parent else "birth")
        kind_label = "otimização (variante)" if is_variant else ("clone" if parent else "nasceu")
        parent_txt = f" de {parent.robot_id}" if parent else ""
        self._log_event(kind, f"{robot_id} {kind_label}{parent_txt} — especialista em {strategy_name}/{symbol}/{timeframe} com ${cfg.starting_capital:.2f}",
                        robot_id=robot_id, symbol=symbol, strategy_name=strategy_name,
                        parent_id=parent.robot_id if parent else None)
        self._save_state()

    async def _handle_clone(self, parent: DarwinAgentV2):
        parent_rec = self.records.get(parent.robot_id)
        if not parent_rec:
            return

        # Clonagem (+70%) é sempre sinal de sucesso da ESTRATÉGIA, mesmo
        # quando a Sala de Risco impede uma réplica física agora — promove
        # incondicionalmente.
        if parent_rec.strategy_id:
            self.strategist.promote_strategy(parent_rec.strategy_id)
            self._log_event("promote", f"{parent.robot_id} bateu +70% — '{parent_rec.strategy_name}' em {parent_rec.symbol} promovida no ranking",
                            robot_id=parent.robot_id, symbol=parent_rec.symbol, strategy_name=parent_rec.strategy_name)

        niche_key = self._niche_key(parent_rec.strategy_id, parent_rec.symbol)
        niche_ok, _ = self.strategist.check_niche_capacity(self._alive_count_in_niche(niche_key))

        if niche_ok:
            await self._spawn_exact_clone(parent, parent_rec)
        else:
            await self._spawn_optimization(parent, parent_rec, niche_key)

    async def _spawn_exact_clone(self, parent: DarwinAgentV2, parent_rec: RobotRecord):
        pop_ok, _ = self.strategist.check_population_capacity(self._alive_count_total())
        if not pop_ok:
            self._pending_clones.append({
                "kind": "clone", "base_robot_id": parent.robot_id,
                "strategy_id": parent_rec.strategy_id, "symbol": parent_rec.symbol,
                "timeframe": parent_rec.timeframe, "params": None,
                "queued_at": _utcnow().isoformat(),
            })
            return
        clone_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(clone_id, parent.symbol, parent.strategy_name, parent,
                          strategy_source=parent_rec.strategy_source,
                          strategy_id=parent_rec.strategy_id, timeframe=parent_rec.timeframe,
                          strategy_params=parent.strategy_params,
                          strategy_indicators=parent_rec.strategy_indicators,
                          strategy_entry_rule=parent_rec.strategy_entry_rule,
                          strategy_exit_rule=parent_rec.strategy_exit_rule,
                          strategy_risk_management=parent_rec.strategy_risk_management)

    async def _spawn_optimization(self, parent: DarwinAgentV2, parent_rec: RobotRecord, niche_key: str):
        """Nicho no teto (MAX_ROBOTS_PER_NICHE robôs vivos já apostando a
        mesma coisa) — em vez de mais uma cópia idêntica, o Estrategista
        propõe uma pequena otimização a partir do melhor desempenho já
        observado nesse nicho (ver `Strategist.suggest_optimization`). O
        resultado é um `strategy_id` novo — um nicho PRÓPRIO, com seu
        próprio teto, então não some no meio da concentração que motivou a
        otimização."""
        base_rec = self._best_in_niche(niche_key) or parent_rec
        base_agent = self.agents.get(base_rec.id, parent)
        mutated_params = self.strategist.suggest_optimization(base_rec.strategy_params or {})
        variant_strategy_id = self.strategist.variant_strategy_id(base_rec.strategy_id, mutated_params)

        pop_ok, _ = self.strategist.check_population_capacity(self._alive_count_total())
        if not pop_ok:
            self._pending_clones.append({
                "kind": "variant", "base_robot_id": base_rec.id,
                "strategy_id": variant_strategy_id, "symbol": base_rec.symbol,
                "timeframe": base_rec.timeframe, "params": mutated_params,
                "queued_at": _utcnow().isoformat(),
            })
            return

        clone_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(clone_id, base_rec.symbol, base_agent.strategy_name, base_agent,
                          strategy_source=f"{base_rec.strategy_source} — otimização automática "
                                        f"(nicho no limite de {self.strategist.MAX_ROBOTS_PER_NICHE})",
                          strategy_id=variant_strategy_id, timeframe=base_rec.timeframe,
                          strategy_params=mutated_params,
                          strategy_indicators=base_rec.strategy_indicators,
                          strategy_entry_rule=base_rec.strategy_entry_rule,
                          strategy_exit_rule=base_rec.strategy_exit_rule,
                          strategy_risk_management=base_rec.strategy_risk_management)

    async def _drain_pending_clones(self, freed_niche_key: str):
        """Uma morte libera exatamente uma vaga — na população global, e às
        vezes também no nicho específico de quem morreu. Atende primeiro
        quem esperava por ESSE nicho (fila FIFO); se não havia ninguém
        esperando por ele, atende o pedido mais antigo da fila cujo nicho
        (se for clone exato) ainda tenha espaço."""
        if not self._pending_clones:
            return
        pop_ok, _ = self.strategist.check_population_capacity(self._alive_count_total())
        if not pop_ok:
            return

        for i, req in enumerate(self._pending_clones):
            if req["kind"] == "clone" and self._niche_key(req["strategy_id"], req["symbol"]) == freed_niche_key:
                await self._fulfill_pending(self._pending_clones.pop(i))
                return

        for i, req in enumerate(self._pending_clones):
            if req["kind"] == "variant":
                await self._fulfill_pending(self._pending_clones.pop(i))
                return
            niche_ok, _ = self.strategist.check_niche_capacity(
                self._alive_count_in_niche(self._niche_key(req["strategy_id"], req["symbol"])))
            if niche_ok:
                await self._fulfill_pending(self._pending_clones.pop(i))
                return

    async def _fulfill_pending(self, req: dict):
        base_agent = self.agents.get(req["base_robot_id"])
        base_rec = self.records.get(req["base_robot_id"])
        if not base_agent or not base_rec or base_rec.status != "alive":
            return  # a base morreu/sumiu enquanto esperava vaga — descarta o pedido
        is_variant = req["kind"] == "variant"
        clone_id = f"r-{uuid.uuid4().hex[:8]}"
        await self._spawn(clone_id, base_rec.symbol, base_agent.strategy_name, base_agent,
                          strategy_source=base_rec.strategy_source + (" — otimização automática" if is_variant else ""),
                          strategy_id=req["strategy_id"], timeframe=base_rec.timeframe,
                          strategy_params=req["params"] if is_variant else base_agent.strategy_params,
                          strategy_indicators=base_rec.strategy_indicators,
                          strategy_entry_rule=base_rec.strategy_entry_rule,
                          strategy_exit_rule=base_rec.strategy_exit_rule,
                          strategy_risk_management=base_rec.strategy_risk_management)

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
            self._log_event("demote", f"{robot.robot_id} foi eliminado — '{rec.strategy_name}' em {rec.symbol} rebaixada no ranking",
                            robot_id=robot.robot_id, symbol=rec.symbol, strategy_name=rec.strategy_name)
        if rec:
            self._log_event("death", f"{robot.robot_id} ({rec.strategy_name}/{rec.symbol}) foi eliminado: {cause}",
                            robot_id=robot.robot_id, symbol=rec.symbol, strategy_name=rec.strategy_name, cause=cause)
        # Sala de Risco — a morte libera uma vaga (nesse nicho e na
        # população global); atende quem estava esperando, se houver.
        if rec:
            await self._drain_pending_clones(self._niche_key(rec.strategy_id, rec.symbol))
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
            "risk_room": self._risk_room_report(),
            "table": self._table_report(),
        }
        directory = os.path.dirname(self.state_file) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.state_file)

    def _log_event(self, event_type: str, message: str, **extra):
        """Grava uma linha no log de eventos (`data/events.jsonl`,
        append-only) — a linha do tempo em texto do que está acontecendo
        (nasceu, morreu, clonou, foi recusado e por quê, decisões da
        Mesa), pra janela separada `/eventos` do painel. Só registra —
        não decide nada, mesmo espírito de `_record_history`."""
        record = {"ts": _utcnow().isoformat(), "type": event_type, "message": message, **extra}
        directory = os.path.dirname(self.events_file) or "."
        os.makedirs(directory, exist_ok=True)
        try:
            with open(self.events_file, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass

    def _record_history(self):
        """Grava um snapshot no tempo (append-only, `data/history.jsonl`) —
        `population.json` só guarda o "agora" (sobrescrito a cada save), sem
        isso não tem como desenhar o gráfico de patrimônio de cada robô ao
        longo do tempo no painel. Um snapshot por robô vivo + o total global,
        por linha de JSON, pra poder ler incrementalmente sem carregar tudo."""
        self._sync_alive_records()
        alive = [r for r in self.records.values() if r.status == "alive"]
        snapshot = {
            "ts": _utcnow().isoformat(),
            "total_capital_alive": round(sum(r.capital for r in alive), 2),
            "population_alive": len(alive),
            "robots": [
                {
                    "id": r.id, "symbol": r.symbol, "strategy_name": r.strategy_name,
                    "parent_id": r.parent_id, "capital": round(r.capital, 4),
                }
                for r in alive
            ],
        }
        directory = os.path.dirname(self.history_file) or "."
        os.makedirs(directory, exist_ok=True)
        try:
            with open(self.history_file, "a") as f:
                f.write(json.dumps(snapshot) + "\n")
        except Exception:
            pass

    def save_full_state(self):
        """Estado completo pra RETOMAR a população depois de um restart do
        processo — diferente de `_save_state()` (retrato leve só pro
        painel), isso inclui o cérebro aprendido de cada robô vivo
        (`DarwinAgentV2.export_state()`), o ranking de estratégias, e a
        fila de pendências da Sala de Risco. Sem isso, desligar o processo
        significaria começar a população do zero toda vez."""
        self._sync_alive_records()
        agent_states = {}
        for rid, agent in self.agents.items():
            try:
                agent_states[rid] = agent.export_state()
            except Exception as e:
                print(f"[Organism] não consegui exportar estado de {rid}, ele não será retomado: {e}")
        data = {
            "saved_at": _utcnow().isoformat(),
            "next_symbol_idx": self._next_symbol_idx,
            "pending_clones": self._pending_clones,
            "pending_approvals": self._pending_approvals,
            "last_root_proposal_at": self._last_root_proposal_at.isoformat() if self._last_root_proposal_at else None,
            "leaderboard": [asdict(e) for e in self.strategist.leaderboard.all_entries()],
            "records": {rid: asdict(r) for rid, r in self.records.items()},
            "agent_states": agent_states,
        }
        directory = os.path.dirname(self.full_state_file) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = self.full_state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.full_state_file)

    async def resume_from_state(self) -> bool:
        """Lê `full_state_file` (se existir) e religa a população de onde
        parou: robôs vivos voltam com o capital/cérebro/marcos exatos de
        antes (não nascem de novo — ver `DarwinAgentV2.import_state`);
        robôs mortos voltam só como registro histórico. Retorna False se
        não havia nada salvo (primeira vez rodando) — quem chama decide
        então nascer uma população nova."""
        if not os.path.exists(self.full_state_file):
            return False
        try:
            with open(self.full_state_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[Organism] estado salvo corrompido/ilegível, começando do zero: {e}")
            return False

        self._next_symbol_idx = data.get("next_symbol_idx", 0)
        self._pending_clones = data.get("pending_clones", [])
        self._pending_approvals = data.get("pending_approvals", {})
        last_root_at = data.get("last_root_proposal_at")
        self._last_root_proposal_at = datetime.fromisoformat(last_root_at) if last_root_at else None
        for e in data.get("leaderboard", []):
            entry = LeaderboardEntry(**e)
            self.strategist.leaderboard._entries[entry.strategy_id] = entry

        agent_states = data.get("agent_states", {})
        resumed_count = 0
        for rid, rec_data in data.get("records", {}).items():
            rec = RobotRecord(**rec_data)
            self.records[rid] = rec
            if rec.status != "alive":
                continue
            state = agent_states.get(rid)
            if not state:
                # Registro dizia "vivo" mas não tinha cérebro/saúde salvos
                # (não deveria acontecer) — não dá pra religar sem isso;
                # melhor marcar como perdido do que nascer do zero por
                # baixo do mesmo ID.
                rec.status = "dead"
                rec.died_at = _utcnow().isoformat()
                rec.cause_of_death = "Estado do robô perdido no reinício do processo"
                continue
            cfg = self._new_config(rec.symbol, rec.timeframe)
            agent = DarwinAgentV2(
                config=cfg, strategy_name=rec.strategy_name, robot_id=rid,
                strategist=self.strategist, parent_id=rec.parent_id,
                strategy_params=rec.strategy_params, on_clone=self._handle_clone,
                on_death=self._handle_death, real_adapter_factory=self._real_adapter_factory,
            )
            agent.import_state(state)
            async with self._lock:
                self.agents[rid] = agent
                self.tasks[rid] = asyncio.create_task(agent.run())
            resumed_count += 1

        print(f"[Organism] retomado de {self.full_state_file}: {resumed_count} robô(s) vivo(s), "
              f"{len(self.records)} no histórico total")
        self._save_state()
        return True

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
                        check_interval: float = 1.0, save_interval_ticks: int = 5,
                        history_interval_ticks: int = 30):
        """Roda a população até `condition(self)` retornar True ou a
        população inteira ser extinta. `history_interval_ticks` controla de
        quanto em quanto tempo grava um ponto no histórico de patrimônio
        (mais espaçado que o save de estado — não precisa de um ponto por
        tick, só o suficiente pra desenhar a curva no painel)."""
        tick = 0
        while self.agents and not condition(self):
            await asyncio.sleep(check_interval)
            tick += 1
            if tick % save_interval_ticks == 0:
                self._save_state()
                self.save_full_state()
            if tick % history_interval_ticks == 0:
                self._record_history()
        self._save_state()
        self.save_full_state()
        self._record_history()

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
