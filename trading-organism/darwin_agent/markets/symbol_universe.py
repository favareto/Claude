"""Universo de ativos operáveis — busca a lista real de símbolos
negociáveis na Bybit (REST pública, sem chave de API) via
`GET /v5/market/instruments-info`. Não é uma lista fixa pequena: o
objetivo é uma população de até ~1000 ativos (spot + perpétuos USDT
combinados), de onde o Macro-organismo distribui especialistas.

Docs: https://bybit-exchange.github.io/docs/v5/market/instrument

Nota: buscar isso exige rede até api(-testnet).bybit.com — bloqueado no
sandbox de desenvolvimento do Claude Code por política de egress (mesma
razão pela qual todo o resto do projeto roda sobre
`markets/simulated.py` aqui). Funciona normalmente em produção (VPS, ver
GUIA_DEPLOY.md). `fetch_symbol_universe` cai num fallback curado se a rede
falhar, pra nunca deixar a população sem ativos pra operar.
"""

import aiohttp
from typing import List, Optional

BASE_URL = "https://api.bybit.com"
CATEGORIES = ("spot", "linear")  # spot (à vista) + perpétuos USDT

# Fallback se a Bybit estiver inacessível (rede, rate limit, manutenção) —
# os pares mais líquidos, pra população nunca ficar sem ativo pra operar.
FALLBACK_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT", "BCHUSDT",
    "UNIUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT", "NEARUSDT", "APTUSDT",
    "FILUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT", "INJUSDT", "TIAUSDT",
    "SEIUSDT", "RUNEUSDT", "AAVEUSDT", "MKRUSDT", "SANDUSDT", "AXSUSDT",
]


async def _fetch_category(session: "aiohttp.ClientSession", category: str,
                          quote: str, limit_per_page: int = 1000) -> List[str]:
    """Pagina por `nextPageCursor` até esgotar a categoria."""
    symbols: List[str] = []
    cursor: Optional[str] = None
    while True:
        params = {"category": category, "limit": str(limit_per_page)}
        if cursor:
            params["cursor"] = cursor
        async with session.get(f"{BASE_URL}/v5/market/instruments-info",
                               params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        if data.get("retCode") != 0:
            break
        result = data.get("result", {})
        for item in result.get("list", []):
            if item.get("quoteCoin") != quote:
                continue
            if item.get("status") not in ("Trading", None):
                continue
            symbols.append(item["symbol"])
        cursor = result.get("nextPageCursor")
        if not cursor:
            break
    return symbols


async def fetch_symbol_universe(target_size: int = 1000, quote: str = "USDT") -> List[str]:
    """Combina spot + linear (perpétuos USDT), deduplicado, até
    `target_size` símbolos. Cai em `FALLBACK_SYMBOLS` se a rede falhar."""
    seen: List[str] = []
    seen_set = set()
    try:
        async with aiohttp.ClientSession() as session:
            for category in CATEGORIES:
                if len(seen) >= target_size:
                    break
                for symbol in await _fetch_category(session, category, quote):
                    if symbol not in seen_set:
                        seen_set.add(symbol)
                        seen.append(symbol)
                        if len(seen) >= target_size:
                            break
    except Exception:
        return list(FALLBACK_SYMBOLS)

    if not seen:
        return list(FALLBACK_SYMBOLS)
    return seen[:target_size]
