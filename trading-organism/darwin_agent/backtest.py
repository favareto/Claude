"""Backtest antes de nascer — Sala de Risco, camada 0.

Antes de uma proposta do Investigador arriscar capital real (mesmo que só
$5), roda a MESMA lógica de análise que o robô usaria ao vivo
(`strategies/base.py: Strategy.analyze`) sobre candles já conhecidos, com
uma janela deslizante, simulando fills simples por stop-loss/take-profit —
sem custo de exchange, só pra descartar de cara propostas obviamente
quebradas. O julgamento de "passou ou não" fica com o Estrategista
(`strategist.py: Strategist.judge_backtest`); aqui só a mecânica pura da
simulação.
"""

from dataclasses import dataclass
from typing import List

from darwin_agent.markets.base import Candle, OrderSide, TimeFrame
from darwin_agent.strategies.base import STRATEGY_CLASSES


@dataclass
class BacktestResult:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0


def run_backtest(candles: List[Candle], strategy_name: str, params: dict,
                 symbol: str, timeframe: TimeFrame, window: int = 60) -> BacktestResult:
    """Varre `candles` com uma janela deslizante de `window` candles,
    chamando `Strategy.analyze` a cada passo — igual ao robô ao vivo.
    Quando há uma posição aberta, só checa se o candle atual bateu o
    stop-loss ou o take-profit da proposta (execução simplificada, sem
    slippage/fees — o objetivo é descartar propostas ruins, não simular
    P&L exato)."""
    if strategy_name not in STRATEGY_CLASSES or len(candles) <= window:
        return BacktestResult()
    strategy = STRATEGY_CLASSES[strategy_name](params=params)

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    trades = wins = losses = 0
    open_side = None
    open_entry = open_stop = open_tp = None

    for i in range(window, len(candles)):
        current = candles[i]

        if open_side is not None:
            hit_stop = current.low <= open_stop if open_side == OrderSide.BUY else current.high >= open_stop
            hit_tp = current.high >= open_tp if open_side == OrderSide.BUY else current.low <= open_tp
            if hit_stop or hit_tp:
                exit_price = open_stop if hit_stop else open_tp
                pnl_pct = ((exit_price - open_entry) / open_entry if open_side == OrderSide.BUY
                          else (open_entry - exit_price) / open_entry)
                equity *= (1 + pnl_pct)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
                trades += 1
                wins += 1 if pnl_pct > 0 else 0
                losses += 1 if pnl_pct <= 0 else 0
                open_side = None
            continue

        window_candles = candles[i - window:i + 1]
        signal = strategy.analyze(window_candles, symbol, timeframe)
        if signal and signal.entry_price > 0 and signal.stop_loss > 0 and signal.take_profit > 0:
            open_side = signal.side
            open_entry = signal.entry_price
            open_stop = signal.stop_loss
            open_tp = signal.take_profit

    return BacktestResult(
        trades=trades, wins=wins, losses=losses,
        total_return_pct=round((equity - 1) * 100, 2),
        max_drawdown_pct=round(max_dd, 2),
        win_rate=round(wins / trades, 4) if trades else 0.0,
    )
