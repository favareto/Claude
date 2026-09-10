"""Universo curado de ativos fora de cripto — índices globais, commodities,
futuros e ações. Diferente de `symbol_universe.py` (busca paginada real na
Bybit), a Yahoo Finance não tem um endpoint público de "lista todos os
símbolos negociáveis" — por isso aqui é uma lista curada à mão, o padrão
comum de qualquer ferramenta construída sobre `yfinance`.

Tickers seguem a convenção da Yahoo Finance (ex: `^GSPC` pra S&P 500,
`GC=F` pra futuro de ouro, `PETR4.SA` pra ação brasileira na B3).
"""

from typing import Dict, List

INDICES = [
    "^GSPC",   # S&P 500
    "^DJI",    # Dow Jones
    "^IXIC",   # Nasdaq Composite
    "^RUT",    # Russell 2000
    "^BVSP",   # Ibovespa
    "^GDAXI",  # DAX (Alemanha)
    "^FTSE",   # FTSE 100 (Reino Unido)
    "^N225",   # Nikkei 225 (Japão)
    "^HSI",    # Hang Seng (Hong Kong)
]

COMMODITIES_FUTURES = [
    "GC=F",  # Ouro
    "SI=F",  # Prata
    "CL=F",  # Petróleo WTI
    "BZ=F",  # Petróleo Brent
    "NG=F",  # Gás natural
    "ZC=F",  # Milho
    "ZS=F",  # Soja
    "KC=F",  # Café
    "HG=F",  # Cobre
]

STOCKS_US = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "JPM", "V", "WMT", "XOM", "JNJ", "PG", "MA", "HD",
]

STOCKS_BR = [
    "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "ABEV3.SA",
    "B3SA3.SA", "WEGE3.SA", "MGLU3.SA", "BBAS3.SA",
]

# symbol -> categoria (pro currículo do Professor / painel entenderem que
# tipo de ativo é, e pra classify_symbol() abaixo).
CATEGORY_BY_SYMBOL: Dict[str, str] = {}
for sym in INDICES:
    CATEGORY_BY_SYMBOL[sym] = "index"
for sym in COMMODITIES_FUTURES:
    CATEGORY_BY_SYMBOL[sym] = "commodity_future"
for sym in STOCKS_US + STOCKS_BR:
    CATEGORY_BY_SYMBOL[sym] = "stock"


def get_multi_asset_universe() -> List[str]:
    """Todos os símbolos curados (índices + commodities/futuros + ações
    US/BR), na ordem em que devem entrar no pool de especialização do
    Organism."""
    return list(INDICES) + list(COMMODITIES_FUTURES) + list(STOCKS_US) + list(STOCKS_BR)


def category_of(symbol: str) -> str:
    return CATEGORY_BY_SYMBOL.get(symbol, "unknown")
