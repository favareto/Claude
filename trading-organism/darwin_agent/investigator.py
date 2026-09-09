"""Investigador — pesquisa estratégias de trading e estrutura em formato
padronizado (nome, indicadores, regra de entrada, regra de saída, gestão de
risco, fonte). Cada proposta aprovada pelo Estrategista dá nascimento a um
novo avatar (boneco) especialista naquela estratégia — um boneco novo por
validação (ver CLAUDE.md).

Em produção isto roda como script separado (cron/GitHub Actions) chamando a
API da Anthropic com busca web habilitada — não depende de sessão
interativa do Claude Code. Este módulo define o contrato de dados
(`StrategyProposal`) e um catálogo inicial pesquisado manualmente; pesquisa
contínua/automatizada é o próximo passo (rodar isto como script com a
ferramenta de busca web habilitada).
"""

from dataclasses import dataclass, field
from typing import List, Optional

from darwin_agent.strategies.base import STRATEGY_REGISTRY


@dataclass
class StrategyProposal:
    name: str
    indicators: List[str]
    entry_rule: str
    exit_rule: str
    risk_management: str
    source: str
    implementation: str  # chave em STRATEGY_REGISTRY que executa isto
    asset_hint: Optional[str] = None

    def is_well_formed(self) -> bool:
        """Checagem de schema — não substitui a validação do Estrategista,
        só garante que os campos obrigatórios existem antes de submeter."""
        required = [self.name, self.entry_rule, self.exit_rule,
                   self.risk_management, self.source, self.implementation]
        return all(bool(f) for f in required)


class Investigador:
    """Catálogo de estratégias pesquisadas. `propose()` entrega uma de cada
    vez — cada chamada é uma "trazida" separada, cada uma vira uma tentativa
    de nascimento de avatar (aprovada ou recusada pelo Estrategista)."""

    def __init__(self):
        self._catalog: List[StrategyProposal] = []

    def add_researched(self, proposal: StrategyProposal):
        self._catalog.append(proposal)

    def propose(self, index: int = 0) -> Optional[StrategyProposal]:
        if 0 <= index < len(self._catalog):
            return self._catalog[index]
        return None

    def all_proposals(self) -> List[StrategyProposal]:
        return list(self._catalog)


def seed_catalog() -> Investigador:
    """Catálogo inicial — estratégias já mapeadas nesta pesquisa manual,
    casando 1:1 com o que já está implementado em strategies/base.py."""
    inv = Investigador()
    inv.add_researched(StrategyProposal(
        name="EMA 9/21 Crossover (Momentum)",
        indicators=["EMA 9", "EMA 21"],
        entry_rule="Compra quando EMA9 cruza acima da EMA21 (tendência de alta); "
                   "vende quando cruza abaixo (tendência de baixa).",
        exit_rule="Stop loss e take profit fixos por % de distância do preço de entrada; "
                  "sai também se a tendência reverter (cruzamento contrário).",
        risk_management="Máx. 2% do capital em risco por trade, R:R mínimo 1.5:1.",
        source="https://quant-signals.com/ema-crossover-strategy/ "
              "(backtest reportou profit factor 1.59 no EMA 9/21 em BTCUSD D1; "
              "consenso: funciona melhor como filtro de tendência do que sinal isolado)",
        implementation="momentum",
        asset_hint="BTCUSDT",
    ))
    return inv
