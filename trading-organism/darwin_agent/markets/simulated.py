"""Simulated market — gera candles sintéticos (random walk) localmente, sem
depender de nenhuma exchange real.

Serve como `real_adapter` de um `PaperTradingAdapter` (markets/crypto.py),
que já implementa toda a execução/saldo/posições em papel — este adapter só
precisa fornecer preços. Usado pra validar o ciclo nascer→operar→clonar→
morrer em "simulação pura" (roadmap do CLAUDE.md, passo 4), sem precisar de
chaves de API nem rede.
"""

import random
from typing import Dict, List, Optional

from darwin_agent.markets.base import Candle, MarketAdapter, OrderSide, OrderType, Position, TimeFrame, TradeResult


class SimulatedMarketAdapter(MarketAdapter):
    def __init__(self, symbols: List[str], seed: Optional[int] = None,
                 base_price: float = 100.0, volatility: float = 0.006, drift: float = 0.0):
        super().__init__(name="simulated", config={"testnet": True})
        self._rng = random.Random(seed)
        self._volatility = volatility
        self._drift = drift
        self._history: Dict[str, List[Candle]] = {}
        self._min_trade_size = 0.0001
        for symbol in symbols:
            start = base_price * self._rng.uniform(0.3, 3.0)
            self._history[symbol] = self._seed_history(start, n=250)

    def _seed_history(self, start_price: float, n: int) -> List[Candle]:
        import datetime as _dt
        candles = []
        price = start_price
        now = _dt.datetime.now(_dt.timezone.utc)
        for i in range(n):
            candles.append(self._next_candle(price, now - _dt.timedelta(minutes=(n - i))))
            price = candles[-1].close
        return candles

    def _next_candle(self, open_price: float, ts) -> Candle:
        move = self._rng.gauss(self._drift, self._volatility)
        close = max(0.0001, open_price * (1.0 + move))
        high = max(open_price, close) * (1.0 + abs(self._rng.gauss(0, self._volatility * 0.3)))
        low = min(open_price, close) * (1.0 - abs(self._rng.gauss(0, self._volatility * 0.3)))
        volume = abs(self._rng.gauss(1000, 300))
        return Candle(timestamp=ts, open=open_price, high=high, low=low, close=close, volume=volume)

    def _ensure_symbol(self, symbol: str):
        if symbol not in self._history:
            start = 100.0 * self._rng.uniform(0.3, 3.0)
            self._history[symbol] = self._seed_history(start, n=250)

    async def connect(self) -> bool:
        self.is_connected = True
        return True

    async def disconnect(self):
        self.is_connected = False

    async def get_balance(self) -> float:
        return 0.0

    async def get_candles(self, symbol: str, timeframe: TimeFrame, limit: int = 100) -> List[Candle]:
        self._ensure_symbol(symbol)
        import datetime as _dt
        hist = self._history[symbol]
        last = hist[-1]
        new_candle = self._next_candle(last.close, _dt.datetime.now(_dt.timezone.utc))
        hist.append(new_candle)
        if len(hist) > 500:
            self._history[symbol] = hist[-500:]
        return list(self._history[symbol][-limit:])

    async def get_current_price(self, symbol: str) -> float:
        self._ensure_symbol(symbol)
        return self._history[symbol][-1].close

    async def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                          quantity: float, price: Optional[float] = None,
                          stop_loss: Optional[float] = None,
                          take_profit: Optional[float] = None) -> TradeResult:
        # Nunca chamado: PaperTradingAdapter executa ordens localmente e só
        # usa este adapter para preços/candles.
        return TradeResult(success=False, symbol=symbol, error="SimulatedMarketAdapter does not execute orders directly")

    async def close_position(self, position: Position) -> TradeResult:
        return TradeResult(success=False, symbol=position.symbol, error="SimulatedMarketAdapter does not execute orders directly")

    async def get_open_positions(self) -> List[Position]:
        return []

    async def get_min_trade_size(self, symbol: str) -> float:
        return self._min_trade_size

    async def get_tradeable_symbols(self) -> List[str]:
        return list(self._history.keys())
