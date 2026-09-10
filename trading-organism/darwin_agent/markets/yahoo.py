"""Yahoo Finance (via `yfinance`) — preços/candles de ações, índices,
commodities e futuros. Grátis, sem cadastro, sem chave de API (decisão
explícita do usuário sobre TradingView vs Yahoo vs Alpha Vantage/Twelve
Data — ver CLAUDE.md).

Ressalva importante: NÃO é uma API oficial da Yahoo (mesma categoria de
risco levantada sobre o TradingView, só que `yfinance` é uma lib madura e
amplamente usada na prática, ao contrário de scraping ad-hoc). Pode
quebrar se a Yahoo mudar algo no backend deles, sem aviso e sem SLA — é o
preço de não pagar/cadastrar nada. Se isso incomodar depois, trocar pra
Alpha Vantage/Twelve Data é só escrever outro adapter (mesma interface
`MarketAdapter`).

Só fornece PREÇOS — igual todo outro adapter deste projeto, nunca executa
ordem real (`place_order`/`close_position` nunca são chamados de verdade;
`PaperTradingAdapter` simula tudo localmente, ver markets/crypto.py).

`yfinance` é síncrono/bloqueante (chamadas de rede por baixo) — todo
acesso é envolto em `asyncio.to_thread` pra não travar o event loop
inteiro (e os outros robôs concorrentes) enquanto espera a Yahoo responder.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from darwin_agent.markets.base import Candle, MarketAdapter, OrderSide, OrderType, Position, TimeFrame, TradeResult

# yfinance não tem "4h" nativo — busca 1h e reamostra (ver _resample_4h).
_INTERVAL_BY_TIMEFRAME = {
    TimeFrame.M1: "1m", TimeFrame.M5: "5m", TimeFrame.M15: "15m",
    TimeFrame.H1: "1h", TimeFrame.D1: "1d", TimeFrame.W1: "1wk",
}

# Período de busca por intervalo — Yahoo limita quanto histórico intraday
# dá pra pedir (documentado: ~7d pra 1m, ~60d pra intervalos <1d). Valores
# conservadores pra ficar dentro do limite com folga; ajustar aqui se a
# Yahoo mudar as regras (não dá pra validar contra a API real neste
# sandbox — rede bloqueada por política, ver CLAUDE.md).
_PERIOD_BY_TIMEFRAME = {
    TimeFrame.M1: "5d", TimeFrame.M5: "5d", TimeFrame.M15: "1mo",
    TimeFrame.H1: "1mo", TimeFrame.D1: "2y", TimeFrame.W1: "5y",
}


class YahooFinanceAdapter(MarketAdapter):
    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="yahoo", config=config or {"testnet": True})
        self._min_trade_size = 0.0001  # fração de ação — paper trading, não precisa ser inteiro

    async def connect(self) -> bool:
        # Sem handshake de verdade (dado público, sem sessão) — a conexão
        # "falha" na prática só na primeira chamada de get_candles/preço,
        # que já lida com exceção sem derrubar o robô.
        self.is_connected = True
        return True

    async def disconnect(self):
        self.is_connected = False

    async def get_balance(self) -> float:
        return 0.0  # nunca lido de verdade — PaperTradingAdapter tem o saldo

    async def get_candles(self, symbol: str, timeframe: TimeFrame, limit: int = 100) -> List[Candle]:
        if timeframe == TimeFrame.H4:
            base = await self._fetch_history(symbol, TimeFrame.H1)
            candles = self._resample(base, "4h")
        else:
            candles = await self._fetch_history(symbol, timeframe)
        return candles[-limit:] if candles else []

    async def get_current_price(self, symbol: str) -> float:
        candles = await self.get_candles(symbol, TimeFrame.M1, limit=1)
        if candles:
            return candles[-1].close
        # Fallback pra símbolos sem dado de 1m (ex: fora do horário de
        # pregão) — pega o candle diário mais recente.
        daily = await self.get_candles(symbol, TimeFrame.D1, limit=1)
        return daily[-1].close if daily else 0.0

    async def _fetch_history(self, symbol: str, timeframe: TimeFrame) -> List[Candle]:
        interval = _INTERVAL_BY_TIMEFRAME.get(timeframe)
        period = _PERIOD_BY_TIMEFRAME.get(timeframe, "1mo")
        if not interval:
            return []
        try:
            df = await asyncio.to_thread(self._download_sync, symbol, period, interval)
        except Exception:
            return []
        return self._df_to_candles(df)

    def _download_sync(self, symbol: str, period: str, interval: str):
        """Roda em thread separada (asyncio.to_thread) — yfinance é
        síncrono e bloqueante, chamar direto travaria o event loop e todos
        os outros robôs concorrentes enquanto espera a rede."""
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        return ticker.history(period=period, interval=interval, auto_adjust=False)

    @staticmethod
    def _df_to_candles(df) -> List[Candle]:
        if df is None or len(df) == 0:
            return []
        candles = []
        for ts, row in df.iterrows():
            try:
                dt = ts.to_pydatetime()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                candles.append(Candle(
                    timestamp=dt, open=float(row["Open"]), high=float(row["High"]),
                    low=float(row["Low"]), close=float(row["Close"]),
                    volume=float(row.get("Volume", 0) or 0),
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return candles

    @staticmethod
    def _resample(candles: List[Candle], rule: str) -> List[Candle]:
        """Agrega candles menores num timeframe maior (usado só pra 4h a
        partir de 1h — yfinance não tem intervalo de 4h nativo). Open =
        primeiro, High = máximo, Low = mínimo, Close = último, Volume =
        soma — agregação OHLC padrão."""
        if not candles:
            return []
        try:
            import pandas as pd
        except ImportError:
            return []
        df = pd.DataFrame([{
            "ts": c.timestamp, "Open": c.open, "High": c.high,
            "Low": c.low, "Close": c.close, "Volume": c.volume,
        } for c in candles]).set_index("ts")
        agg = df.resample(rule).agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()
        return YahooFinanceAdapter._df_to_candles(agg)

    async def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                          quantity: float, price: Optional[float] = None,
                          stop_loss: Optional[float] = None,
                          take_profit: Optional[float] = None) -> TradeResult:
        # Nunca chamado: PaperTradingAdapter executa ordens localmente e só
        # usa este adapter pra preços/candles (mesmo padrão de
        # markets/simulated.py).
        return TradeResult(success=False, symbol=symbol, error="YahooFinanceAdapter does not execute orders directly")

    async def close_position(self, position: Position) -> TradeResult:
        return TradeResult(success=False, symbol=position.symbol, error="YahooFinanceAdapter does not execute orders directly")

    async def get_open_positions(self) -> List[Position]:
        return []

    async def get_min_trade_size(self, symbol: str) -> float:
        return self._min_trade_size
