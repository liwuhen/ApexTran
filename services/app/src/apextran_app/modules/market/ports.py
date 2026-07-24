"""Ports (interfaces) the market module depends on.

``MarketSource`` is the upstream data port. Adapters implement it (mock now;
akshare/eastmoney in M2). The service depends on this protocol, not on any
concrete source.
"""

from __future__ import annotations

from typing import Protocol

from .domain.models import FlashItem, HotItem, IntradaySeries, KlineBar, NewsItem, StockSearchItem


class MarketSource(Protocol):
    async def fetch_hotlist(self) -> list[HotItem]: ...

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]: ...

    async def list_stock_instruments(self) -> list[StockSearchItem]: ...

    async def fetch_daily_kline(self, symbol: str, limit: int = 180) -> list[KlineBar]: ...

    async def fetch_intraday(self, symbol: str) -> IntradaySeries: ...

    async def fetch_headlines(self, symbol: str | None = None) -> list[NewsItem]: ...

    async def fetch_news(self, category: str | None = None) -> list[NewsItem]: ...

    async def fetch_ai_hotspots(self) -> list[NewsItem]: ...

    async def fetch_flash(self) -> list[FlashItem]: ...
