"""Investigador — NÃO é um repositório fixo de poucas estratégias. É um
FLUXO CONTÍNUO: a cada rodada de pesquisa (produção: script separado, cron/
GitHub Actions, chamando a API da Anthropic com busca web habilitada — ver
CLAUDE.md), novas estratégias de sucesso são descobertas e injetadas na
fila (`ingest`). O Estrategista consome dessa fila conforme robôs precisam
nascer — nunca um catálogo estático de "as 4 estratégias de sempre".

Cada estratégia é estruturada em formato padronizado (nome, indicadores,
regra de entrada, regra de saída, gestão de risco, fonte) antes de virar
uma `StrategyProposal`.
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
        """Checagem de schema — não substitui o julgamento do Estrategista,
        só garante que os campos obrigatórios existem antes de submeter."""
        required = [self.name, self.entry_rule, self.exit_rule,
                   self.risk_management, self.source, self.implementation]
        return all(bool(f) for f in required)


class Investigador:
    """Fila de estratégias pesquisadas — cresce continuamente via `ingest`.
    Nada aqui é fixo: uma rodada de pesquisa pode trazer 0, 1 ou várias
    estratégias novas a qualquer momento; o mesmo `implementation` pode
    reaparecer com parâmetros/fontes diferentes conforme a pesquisa avança.
    """

    def __init__(self):
        self._feed: List[StrategyProposal] = []
        self._consumed = 0

    def ingest(self, proposal: StrategyProposal):
        """Uma rodada de pesquisa trouxe uma estratégia nova — entra na fila."""
        self._feed.append(proposal)

    def next_new(self) -> Optional[StrategyProposal]:
        """Consome a próxima estratégia ainda não usada da fila (FIFO)."""
        if self._consumed < len(self._feed):
            proposal = self._feed[self._consumed]
            self._consumed += 1
            return proposal
        return None

    def pending_count(self) -> int:
        return len(self._feed) - self._consumed

    def all_ingested(self) -> List[StrategyProposal]:
        return list(self._feed)


def bootstrap_feed() -> Investigador:
    """Ponto de partida pra desenvolvimento/simulação — algumas rodadas de
    pesquisa já feitas manualmente (fontes reais, ver cada `source`). Em
    produção isto some: o Investigador roda de verdade e `ingest()` é
    chamado continuamente por um script externo, não por esta função."""
    inv = Investigador()
    inv.ingest(StrategyProposal(
        name="EMA 9/21 Crossover (Momentum)",
        indicators=["EMA 9", "EMA 21"],
        entry_rule="Compra quando EMA9 cruza acima da EMA21 (tendência de alta); "
                   "vende quando cruza abaixo (tendência de baixa).",
        exit_rule="Stop loss e take profit fixos por % de distância do preço de entrada; "
                  "sai também se a tendência reverter (cruzamento contrário).",
        risk_management="Máx. 2% do capital em risco por trade, R:R mínimo 1.5:1.",
        source="https://quant-signals.com/ema-crossover-strategy/ "
              "(profit factor 1.59 no EMA 9/21 em BTCUSD D1; funciona melhor "
              "como filtro de tendência do que sinal isolado)",
        implementation="momentum",
        asset_hint="BTCUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="Bollinger Bands Mean Reversion",
        indicators=["Bollinger Bands (20, 2)", "ADX (filtro de regime)"],
        entry_rule="Compra perto da banda inferior, vende perto da banda superior — "
                   "só em mercado lateral (ADX < 20); evitar em tendência forte.",
        exit_rule="Sai na banda média (mean) ou banda oposta; stop se ADX subir "
                  "acima de 30 no meio da operação (mudança de regime).",
        risk_management="Filtro de volatilidade: pausar se ATR > 1.5x a média de 20 "
                        "períodos — evita a maior parte das perdas grandes.",
        source="https://quant-signals.com/bollinger-bands-trading-strategy/ "
              "(profit factor 1.62 em BTC/USDT 4H 2023-2025 em regime lateral; "
              "profit factor NEGATIVO -0.74 em regime de tendência — usar com filtro de ADX)",
        implementation="mean_reversion",
        asset_hint="ETHUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="VWAP + RSI + EMA Scalping",
        indicators=["VWAP", "RSI", "EMA (tendência)", "ATR (risco)"],
        entry_rule="Compra só acima da VWAP, vende só abaixo — alinhado ao viés "
                   "dominante da sessão; RSI/EMA confirmam o timing da entrada.",
        exit_rule="Saída rápida por ATR-based stop; alvo curto (scalping, não "
                  "segura posição por muito tempo).",
        risk_management="Volume altíssimo de trades exige controle de custo "
                        "(fees/slippage) rígido — validar R líquido, não bruto.",
        source="Backtest em 183 perpétuos da Bybit, 60 dias de candles de 5min, "
              "taxas/slippage reais da Bybit descontados: win rate 53.7%, profit "
              "factor líquido 1.355 (ver ressalva: estudos anteriores tinham bugs "
              "de lookahead, esta é a versão corrigida)",
        implementation="scalping",
        asset_hint="SOLUSDT",
    ))
    return inv
