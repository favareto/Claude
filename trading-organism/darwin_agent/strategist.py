"""Estrategista — gatekeeper central em duas camadas (ver CLAUDE.md).

Camada 1 (`validate_strategy`/`validate_proposal`): valida a estratégia
geral de um robô quando ele nasce ou clona.
Camada 2 (`validate_entry`): valida CADA sinal de entrada antes de qualquer
execução — se recusar, a operação não acontece.

É um SERVIÇO CENTRAL — uma única instância compartilhada por toda a
população, chamada por todos os robôs (não uma cópia isolada por robô). Tem
autonomia pra reprovar QUALQUER estratégia ou operação sempre que
consultado — não é um carimbo automático: mesmo uma proposta com schema
perfeito é recusada se o histórico da população mostrar que aquela
estratégia não está performando naquele ativo (ver `validate_proposal`).
Hoje o julgamento é determinístico (RiskManager + histórico de
sobrevivência); é o ponto de extensão pra plugar um agente/LLM depois, sem
mudar quem chama.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from darwin_agent.investigator import StrategyProposal
from darwin_agent.leaderboard import StrategyLeaderboard
from darwin_agent.markets.base import MarketSignal
from darwin_agent.risk.manager import RiskManager
from darwin_agent.strategies.base import STRATEGY_REGISTRY
from darwin_agent.utils.config import RiskConfig


@dataclass
class TrackRecord:
    """Histórico de robôs já nascidos com uma (estratégia, ativo) — dá ao
    Estrategista uma base real pra reprovar propostas, não só checar schema."""
    attempts: int = 0
    deaths: int = 0
    clones: int = 0

    @property
    def death_rate(self) -> float:
        return self.deaths / self.attempts if self.attempts > 0 else 0.0


class Strategist:
    # Só julga pelo histórico depois de um mínimo de tentativas — amostra
    # pequena demais não é evidência.
    MIN_ATTEMPTS_BEFORE_JUDGING = 3
    MAX_DEATH_RATE = 0.75

    def __init__(self, risk_config: RiskConfig):
        self._risk_config = risk_config
        self._risk_by_robot: Dict[str, RiskManager] = {}
        # Ranking vivo de até 500 estratégias — a autonomia do Estrategista
        # expressa como mérito acumulado (ver leaderboard.py).
        self.leaderboard = StrategyLeaderboard()

    def _risk_for(self, robot_id: str) -> RiskManager:
        if robot_id not in self._risk_by_robot:
            self._risk_by_robot[robot_id] = RiskManager(self._risk_config)
        return self._risk_by_robot[robot_id]

    def consider_new_strategy(self, proposal: StrategyProposal) -> Tuple[bool, str]:
        """O Investigador traz uma proposta nova (a cada rodada de
        pesquisa, ~30min em produção) — o Estrategista decide se ela entra
        no ranking de até 500. Uma estratégia melhor pode sobrepor uma
        pior quando o ranking está cheio."""
        return self.leaderboard.consider(proposal)

    def promote_strategy(self, strategy_id: str):
        """Um robô com esta estratégia clonou (+70%) — promove no ranking."""
        self.leaderboard.promote(strategy_id)

    def demote_strategy(self, strategy_id: str):
        """Um robô com esta estratégia foi eliminado (-60% do pico) —
        rebaixa no ranking."""
        self.leaderboard.demote(strategy_id)

    def register_strategy_attempt(self, strategy_id: str):
        self.leaderboard.register_attempt(strategy_id)

    def validate_strategy(self, robot_id: str, symbol: str,
                          available_strategies: List[str]) -> Tuple[bool, str]:
        """Camada 1 (checagem genérica) — chamada por todo robô ao nascer,
        incluindo clones. Só confirma que o robô tem ativo e implementação
        de estratégia válidos; não julga o MÉRITO da estratégia."""
        if not symbol:
            return False, "Robô sem ativo especialista definido"
        if not available_strategies:
            return False, "Nenhuma estratégia disponível"
        return True, f"Estratégia aprovada para {symbol}"

    def validate_proposal(self, proposal: StrategyProposal, symbol: str,
                          track_record: Optional[TrackRecord] = None) -> Tuple[bool, str]:
        """Camada 1 (julgamento da proposta do Investigador) — chamada UMA
        vez por proposta trazida, antes de criar um avatar novo pra ela.
        Cada proposta aprovada aqui gera exatamente um boneco novo; cada
        recusa não gera nenhum.

        Duas frentes de reprovação, independentes:
        1. Schema/rastreabilidade — proposta incompleta ou estratégia sem
           implementação não passa, ponto.
        2. Mérito — mesmo uma proposta bem formada é recusada se o
           histórico real da população (`track_record`, calculado pelo
           Organism a partir dos robôs já nascidos com essa combinação
           estratégia+ativo) mostrar taxa de morte alta demais. O
           Estrategista NÃO é obrigado a aprovar só porque o formulário
           está certo.
        """
        if not proposal.is_well_formed():
            return False, "Proposta incompleta — faltam campos obrigatórios (nome/regras/fonte)"
        if proposal.implementation not in STRATEGY_REGISTRY:
            return False, f"Implementação '{proposal.implementation}' não existe em strategies/base.py"
        if not symbol:
            return False, "Nenhum ativo disponível para o novo avatar"

        if track_record and track_record.attempts >= self.MIN_ATTEMPTS_BEFORE_JUDGING:
            if track_record.death_rate >= self.MAX_DEATH_RATE:
                return False, (
                    f"Estrategista recusou por histórico: {track_record.deaths}/{track_record.attempts} "
                    f"robôs com '{proposal.implementation}' em {symbol} já morreram "
                    f"({track_record.death_rate:.0%}) — não vale mais insistir nessa combinação"
                )

        return True, f"Proposta '{proposal.name}' aprovada — avatar nascerá especialista em {proposal.implementation}/{symbol}"

    def validate_entry(self, robot_id: str, signal: MarketSignal, capital: float,
                       open_positions: int) -> Tuple[bool, str]:
        """Camada 2 — chamada antes de CADA execução."""
        return self._risk_for(robot_id).approve_trade(signal, capital, open_positions)

    def calculate_position_size(self, robot_id: str, capital: float,
                                entry_price: float, stop_loss: float) -> float:
        return self._risk_for(robot_id).calculate_position_size(capital, entry_price, stop_loss)

    def record_result(self, robot_id: str, pnl: float, capital: float):
        self._risk_for(robot_id).record_trade_result(pnl, capital)

    def risk_report(self, robot_id: str, capital: float) -> dict:
        return self._risk_for(robot_id).get_risk_report(capital)

    def remove_robot(self, robot_id: str):
        self._risk_by_robot.pop(robot_id, None)
