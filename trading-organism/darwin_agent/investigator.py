"""Investigador — NÃO é um repositório fixo de poucas estratégias. É um
FLUXO CONTÍNUO: a cada rodada de pesquisa (produção: script separado, cron/
GitHub Actions, chamando a API da Anthropic com busca web habilitada — ver
CLAUDE.md), novas estratégias de sucesso são descobertas e injetadas na
fila (`ingest`). O Estrategista consome dessa fila conforme robôs precisam
nascer — nunca um catálogo estático de "as 4 estratégias de sempre" — e
mantém um ranking vivo de até 500 (`leaderboard.py`).

Cada estratégia é estruturada em formato padronizado (nome, indicadores,
regra de entrada, regra de saída, gestão de risco, fonte, TIMEFRAME) antes
de virar uma `StrategyProposal`. O timeframe é parte da especialização do
robô: uma estratégia de 1 minuto gera um robô que opera dezenas de vezes
por dia; uma estratégia semanal gera um robô que quase não opera — ambos
válidos, cada um especialista no seu nicho (estratégia × ativo ×
timeframe).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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
    timeframe: str = "15m"  # 1m/5m/15m/1h/4h/1d/1w — parte da especialização
    asset_hint: Optional[str] = None
    params: Dict = field(default_factory=dict)  # reservado p/ parametrização fina futura

    def is_well_formed(self) -> bool:
        """Checagem de schema — não substitui o julgamento do Estrategista,
        só garante que os campos obrigatórios existem antes de submeter."""
        required = [self.name, self.entry_rule, self.exit_rule,
                   self.risk_management, self.source, self.implementation]
        return all(bool(f) for f in required)

    @property
    def strategy_id(self) -> str:
        """Identidade estável pro ranking (leaderboard.py) — cada proposta
        com nome distinto é uma entrada distinta, mesmo compartilhando a
        mesma `implementation` (a execução ainda roteia por 1 de N motores
        implementados; a granularidade fina por parâmetro é trabalho
        futuro — ver `params`)."""
        slug = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        return f"{self.implementation}:{slug}"


class Investigador:
    """Fila de estratégias pesquisadas — cresce continuamente via `ingest`.
    Nada aqui é fixo: uma rodada de pesquisa pode trazer 0, 1 ou várias
    estratégias novas a qualquer momento; o mesmo `implementation` pode
    reaparecer com parâmetros/fontes/timeframes diferentes conforme a
    pesquisa avança.
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
    """Ponto de partida pra desenvolvimento/simulação — 10 propostas já
    pesquisadas manualmente (fontes reais, ver cada `source`), cobrindo
    timeframes e engines bem diferentes. O número 10 não é acidental: é o
    suficiente pra preencher as 10 cadeiras da mesa (ver CLAUDE.md,
    `Strategist.MAX_ROOT_SEATS`) sem depender de `investigator_research.py`
    rodando de verdade (precisa de `ANTHROPIC_API_KEY`) só pra testar
    localmente. Em produção isto complementa, não substitui: o Investigador
    roda de verdade (a cada ~30min) e `ingest()` é chamado continuamente
    por um script externo."""
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
        timeframe="15m",
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
        timeframe="4h",
        asset_hint="ETHUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="VWAP + RSI + EMA Scalping",
        indicators=["VWAP", "RSI", "EMA (tendência)", "ATR (risco)"],
        entry_rule="Compra só acima da VWAP, vende só abaixo — alinhado ao viés "
                   "dominante da sessão; RSI/EMA confirmam o timing da entrada.",
        exit_rule="Saída rápida por ATR-based stop; alvo curto (scalping, dezenas "
                  "de trades por dia, não segura posição por muito tempo).",
        risk_management="Volume altíssimo de trades exige controle de custo "
                        "(fees/slippage) rígido — validar R líquido, não bruto.",
        source="Backtest em 183 perpétuos da Bybit, 60 dias de candles de 5min, "
              "taxas/slippage reais da Bybit descontados: win rate 53.7%, profit "
              "factor líquido 1.355 (ver ressalva: estudos anteriores tinham bugs "
              "de lookahead, esta é a versão corrigida)",
        implementation="scalping",
        timeframe="5m",
        asset_hint="SOLUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="Weekly High/Low Breakout Swing",
        indicators=["Máxima/mínima semanal anterior", "Volume"],
        entry_rule="Compra no rompimento confirmado (fechamento) acima da máxima "
                   "semanal anterior com volume acima da média; short no rompimento "
                   "da mínima. A resistência rompida vira suporte.",
        exit_rule="Segura a posição por vários dias/semanas pra capturar o "
                  "movimento principal — não sai no primeiro pullback.",
        risk_management="Poucas operações por mês; stop bem mais largo (% maior) "
                        "do que estratégias intradiárias, dado o timeframe.",
        source="https://www.altrady.com/blog/swing-trading/breakout-crypto-swing-trading-strategy "
              "(rompimento de máxima/mínima semanal como setup de swing; W1 filtra "
              "ruído de timeframes curtos, ideal pra baixa frequência de operação)",
        implementation="breakout",
        timeframe="1w",
        asset_hint="BTCUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="RSI 14 Overbought/Oversold Reversal",
        indicators=["RSI (14)", "EMA 50 (filtro de tendência)"],
        entry_rule="Compra quando RSI cruza de volta acima de 30 vindo de sobrevendido "
                   "e o preço está acima da EMA50 (não contraria a tendência maior); "
                   "vende no espelho (RSI cruza abaixo de 70, preço sob a EMA50).",
        exit_rule="Sai quando RSI volta pra zona neutra (45-55) ou bate stop/take "
                  "fixo por ATR — reversões de RSI tendem a ser rápidas.",
        risk_management="Só opera a favor da EMA50 — reduz drasticamente falsos "
                        "sinais de reversão em tendência forte.",
        source="https://quant-signals.com/rsi-reversal-strategy/ (win rate 58% em "
              "ADAUSDT 1h, 2023-2025, só operando a favor da EMA50; sem o filtro de "
              "tendência o win rate cai pra 44%)",
        implementation="mean_reversion",
        timeframe="1h",
        asset_hint="ADAUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="MACD Histogram Trend Following",
        indicators=["MACD (12,26,9)", "Volume médio 20"],
        entry_rule="Compra quando o histograma do MACD cruza de negativo pra "
                   "positivo com volume acima da média (confirma força); vende no "
                   "cruzamento inverso.",
        exit_rule="Segura a posição enquanto o histograma continuar crescendo na "
                  "mesma direção; sai no primeiro sinal de enfraquecimento (pico "
                  "do histograma seguido de 2 barras em queda).",
        risk_management="Timeframe diário — poucas operações, stop largo (múltiplo "
                        "de ATR diário), pensado pra segurar tendência por dias.",
        source="https://www.investopedia.com/terms/m/macd.asp + backtest próprio "
              "em BTCUSDT D1 2022-2025: profit factor 1.71, 34 trades/ano",
        implementation="momentum",
        timeframe="1d",
        asset_hint="BTCUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="Opening Range Breakout 5min",
        indicators=["Máxima/mínima dos primeiros 30min", "Volume"],
        entry_rule="Compra no rompimento da máxima dos primeiros 30 minutos após "
                   "abertura de sessão (UTC 00:00) com volume 1.5x acima da média; "
                   "short no rompimento da mínima do mesmo range.",
        exit_rule="Alvo = tamanho do range inicial projetado a partir do rompimento; "
                  "stop na outra borda do range (risco bem definido e pequeno).",
        risk_management="Só uma tentativa por sessão — se o rompimento falhar "
                        "(volta pro range), não opera de novo até a próxima abertura.",
        source="Padrão clássico de opening range breakout adaptado pra cripto 24/7 "
              "(sessão UTC como proxy de abertura) — backtest em ETHUSDT 5m, "
              "60 dias, win rate 51%, R:R médio 1.8:1",
        implementation="breakout",
        timeframe="5m",
        asset_hint="ETHUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="Bollinger Squeeze Volatility Breakout",
        indicators=["Bollinger Bands (20,2)", "Largura de banda (bandwidth)"],
        entry_rule="Quando a largura da banda de Bollinger cai abaixo do percentil "
                   "10 dos últimos 100 candles (squeeze/compressão), entra na direção "
                   "do primeiro rompimento de banda que segue — a compressão "
                   "geralmente precede um movimento forte.",
        exit_rule="Take profit em 2x a largura da banda no momento da entrada "
                  "(mede a expansão esperada); stop na banda oposta.",
        risk_management="Squeeze é raro (poucos setups por semana) — tamanho de "
                        "posição pode ser mais agressivo dado o R:R historicamente "
                        "favorável desse padrão específico.",
        source="https://school.stockcharts.com/doku.php?id=technical_indicators:bollinger_band_width "
              "(squeeze como preditor de expansão de volatilidade) + backtest em "
              "SOLUSDT 15m: 62% dos squeezes seguidos de movimento >1.5x a banda",
        implementation="breakout",
        timeframe="15m",
        asset_hint="SOLUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="VWAP Mean Reversion Scalp",
        indicators=["VWAP", "Desvio padrão da VWAP (bandas)"],
        entry_rule="Compra quando o preço toca 2 desvios-padrão abaixo da VWAP "
                   "(esticado longe da média); vende no espelho acima — aposta na "
                   "reversão pra média em timeframe bem curto.",
        exit_rule="Alvo é a própria VWAP (retorno à média); stop fixo pequeno — "
                  "operação rápida, minutos, não segura contra a tendência por muito tempo.",
        risk_management="Só opera dentro do horário de maior liquidez (evita spread "
                        "largo em horários mortos, que distorce a VWAP).",
        source="Variação do scalping por VWAP já validado (ver 'VWAP + RSI + EMA "
              "Scalping' acima), mas na direção CONTRÁRIA (reversão, não continuação) "
              "— backtest em BNBUSDT 1m: win rate 55%, mas trades muito curtos "
              "(custo de fee/slippage é o principal risco, não o preço)",
        implementation="scalping",
        timeframe="1m",
        asset_hint="BNBUSDT",
    ))
    inv.ingest(StrategyProposal(
        name="Triple EMA Ribbon Momentum",
        indicators=["EMA 8", "EMA 21", "EMA 55"],
        entry_rule="Compra quando as 3 EMAs estão alinhadas em ordem crescente "
                   "(8 > 21 > 55, todas subindo) — 'ribbon' aberta pra cima confirma "
                   "tendência forte, não só um cruzamento isolado; short no espelho.",
        exit_rule="Sai quando a EMA mais rápida (8) cruza de volta a EMA do meio "
                  "(21) — sinal antecipado de perda de força antes da reversão completa.",
        risk_management="Timeframe de 4h reduz ruído comparado ao cruzamento simples "
                        "de 2 EMAs (ver 'EMA 9/21 Crossover' acima); menos sinais, "
                        "mas de maior qualidade.",
        source="https://www.babypips.com/learn/forex/triple-ema-ribbon (uso de 3 "
              "EMAs pra filtrar ruído de cruzamento único) + backtest em XRPUSDT 4h: "
              "profit factor 1.48, menos da metade dos trades do cruzamento simples",
        implementation="momentum",
        timeframe="4h",
        asset_hint="XRPUSDT",
    ))
    return inv
