"""Professor — recebe a estratégia genérica que o Investigador trouxe e
monta o CURRÍCULO: os parâmetros concretos que aquele robô específico vai
usar naquele ativo específico. Personalizado por robô/ativo, não uma regra
genérica pra todos (ver CLAUDE.md) — é isso que "ensina o robô a aplicar
(e adaptar) a estratégia no ativo em que ele é especialista".

Hoje é heurístico e determinístico (classifica o ativo por liquidez típica,
ajusta os parâmetros da estratégia — período dos indicadores, largura do
stop — de acordo; refina ainda mais se houver candles recentes pra medir
volatilidade real). É o ponto de extensão pra um agente/LLM que ensine de
verdade (adapta a explicação, não só os números), sem mudar quem chama.
"""

from typing import Dict, List, Optional

from darwin_agent.investigator import StrategyProposal
from darwin_agent.markets.base import Candle

# Heurística simples: ativos "major" tendem a ter volatilidade mais baixa e
# tendências mais limpas; o resto entra como "alt" (mais ruidoso).
MAJOR_ASSETS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "BTCUSD", "ETHUSD", "BTC", "ETH",
}

# Ajustes por família de estratégia quando o ativo é "alt" — indicadores um
# pouco mais lentos (menos sinal falso) e stop um pouco mais largo.
ALT_ADJUSTMENTS: Dict[str, Dict[str, float]] = {
    "momentum": {"rsi_period": 18, "atr_stop_mult": 2.5, "atr_tp_mult": 3.5},
    "mean_reversion": {"rsi_period": 18, "atr_stop_mult": 2.0},
    "scalping": {"atr_period": 14},
    "breakout": {"vol_surge_mult": 1.8},
}


class Professor:
    def build_curriculum(self, proposal: StrategyProposal, symbol: str,
                         recent_candles: Optional[List[Candle]] = None) -> Dict:
        """Retorna o dict de `params` que o robô vai usar — parte do que o
        Investigador já trouxe na proposta, ajustado pro ativo específico."""
        params = dict(proposal.params)
        is_major = symbol.upper() in MAJOR_ASSETS

        if not is_major:
            for key, value in ALT_ADJUSTMENTS.get(proposal.implementation, {}).items():
                params.setdefault(key, value)

        if recent_candles and len(recent_candles) >= 20:
            self._tune_by_realized_volatility(params, recent_candles)

        return params

    def _tune_by_realized_volatility(self, params: Dict, candles: List[Candle]):
        """Se há candles reais disponíveis, afina os multiplicadores de
        ATR proporcionalmente à volatilidade medida (mais vol -> stop mais
        largo, sem depender só da heurística major/alt)."""
        closes = [c.close for c in candles[-20:]]
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
        if not returns:
            return
        vol = (sum(r ** 2 for r in returns) / len(returns)) ** 0.5
        baseline = 0.01  # ~1% por candle, referência
        mult = max(0.7, min(1.8, vol / baseline)) if baseline > 0 else 1.0
        for key in ("atr_stop_mult", "atr_tp_mult"):
            if key in params:
                params[key] = round(params[key] * mult, 2)
