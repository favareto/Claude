"""Estrategista — gatekeeper central em duas camadas (ver CLAUDE.md).

Camada 1 (`validate_strategy`): valida a estratégia geral de um robô quando
ele nasce ou clona.
Camada 2 (`validate_entry`): valida CADA sinal de entrada antes de qualquer
execução — se recusar, a operação não acontece.

É um SERVIÇO CENTRAL — uma única instância compartilhada por toda a
população, chamada por todos os robôs (não uma cópia isolada por robô).
Hoje as duas camadas são checagens determinísticas (RiskManager + validação
de sanidade); é o ponto de extensão pra plugar um agente/LLM que julgue a
estratégia proposta pelo Professor, sem mudar quem o chama.
"""

from typing import Dict, List, Tuple

from darwin_agent.markets.base import MarketSignal
from darwin_agent.risk.manager import RiskManager
from darwin_agent.utils.config import RiskConfig


class Strategist:
    def __init__(self, risk_config: RiskConfig):
        self._risk_config = risk_config
        self._risk_by_robot: Dict[str, RiskManager] = {}

    def _risk_for(self, robot_id: str) -> RiskManager:
        if robot_id not in self._risk_by_robot:
            self._risk_by_robot[robot_id] = RiskManager(self._risk_config)
        return self._risk_by_robot[robot_id]

    def validate_strategy(self, robot_id: str, symbol: str,
                          available_strategies: List[str]) -> Tuple[bool, str]:
        """Camada 1 — chamada no nascimento (ou troca de estratégia)."""
        if not symbol:
            return False, "Robô sem ativo especialista definido"
        if not available_strategies:
            return False, "Nenhuma estratégia disponível"
        return True, f"Estratégia aprovada para {symbol}"

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
