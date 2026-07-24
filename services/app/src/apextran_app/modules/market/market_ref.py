"""Market reference helpers for A-share symbols."""

from __future__ import annotations

MARKET_SH_A = "沪市A股"
MARKET_SZ_A = "深市A股"
MARKET_BJ = "北交所"
DEFAULT_SNAPSHOT_MARKET = MARKET_SZ_A
_BROAD_MARKET_ALIASES = {"A_SHARE", "A股"}


def market_for_symbol(symbol: str) -> str:
    cleaned = symbol.strip()
    if cleaned.startswith("6"):
        return MARKET_SH_A
    if cleaned.startswith(("0", "3")):
        return MARKET_SZ_A
    if cleaned[:1] in ("4", "8") or cleaned.startswith("92"):
        return MARKET_BJ
    return DEFAULT_SNAPSHOT_MARKET


def normalize_market(market: str, symbol: str = "") -> str:
    cleaned = market.strip()
    if cleaned and cleaned not in _BROAD_MARKET_ALIASES:
        return cleaned
    return market_for_symbol(symbol)
