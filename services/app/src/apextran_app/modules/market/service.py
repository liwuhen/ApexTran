"""Market application service — orchestrates source + cache.

Reads serve from cache; on miss they fetch from the source through a
**single-flight** so concurrent misses on the same key collapse to one upstream
call (no thundering herd). ``refresh_*`` force a fetch and are what the worker
calls on a schedule. The cache is the fan-out point: one fetch, served to N.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TypeVar, cast
from uuid import UUID

from loguru import logger
from pydantic import BaseModel

from ...shared.cache import Cache
from ...shared.realtime import NoopPublisher, RealtimePublisher
from ...shared.singleflight import SingleFlight
from .domain.models import (
    FlashItem,
    HotItem,
    NewsItem,
    StockQuoteItem,
    StockSearchItem,
    Watchlist,
    WatchlistCreate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistItemOrder,
    WatchlistUpdate,
)
from .ports import MarketSource
from .repository import InMemoryWatchlistRepository, WatchlistRepository
from .stock_repository import NoopStockInstrumentRepository, StockInstrumentRepository

T = TypeVar("T")

_HOTLIST_KEY = "market:hotlist"
_FLASH_KEY = "market:flash"
_AI_HOTSPOTS_KEY = "market:ai-hotspots"
_QUOTE_TTL = 2.0

# A long-lived mirror of the last good value per key, so a source outage serves
# stale data instead of an error (stale-while-revalidate). §8.1.
_STALE_TTL = 86400.0


class MarketService:
    def __init__(
        self,
        *,
        source: MarketSource,
        cache: Cache,
        hotlist_ttl: float,
        headlines_ttl: float,
        news_ttl: float,
        flash_ttl: float,
        publisher: RealtimePublisher | None = None,
        watchlist_repository: WatchlistRepository | None = None,
        stock_repository: StockInstrumentRepository | None = None,
    ) -> None:
        self._source = source
        self._cache = cache
        self._hotlist_ttl = hotlist_ttl
        self._headlines_ttl = headlines_ttl
        self._news_ttl = news_ttl
        self._flash_ttl = flash_ttl
        self._publisher = publisher or NoopPublisher()
        self._sf = SingleFlight()
        self._watchlists = watchlist_repository or InMemoryWatchlistRepository()
        self._stocks = stock_repository or NoopStockInstrumentRepository()

    async def _load(self, key: str, fetch: Callable[[], Awaitable[T]], ttl: float) -> T:
        """Cache-first read; misses fetch once (single-flight) and populate cache."""
        cached = await self._cache.get(key)
        if cached is not None:
            return cast("T", cached)
        return await self._sf.run(key, lambda: self._fill(key, fetch, ttl))

    async def _fill(self, key: str, fetch: Callable[[], Awaitable[T]], ttl: float) -> T:
        try:
            data = await fetch()
        except Exception:
            stale = await self._cache.get(f"{key}:last")
            if stale is not None:
                logger.warning("market: source failed for {}, serving stale snapshot", key)
                return cast("T", stale)
            raise
        await self._cache.set(key, data, ttl=ttl)
        await self._cache.set(f"{key}:last", data, ttl=_STALE_TTL)
        return data

    # ---- reads (cache-first, single-flight fallback) -----------------------

    async def get_hotlist(self) -> list[HotItem]:
        return await self._load(_HOTLIST_KEY, self._source.fetch_hotlist, self._hotlist_ttl)

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
        cleaned = query.strip()
        if not cleaned:
            return []
        bounded_limit = max(1, min(limit, 50))
        stored = await self._stocks.search(cleaned, bounded_limit)
        if stored or not isinstance(self._stocks, NoopStockInstrumentRepository):
            return stored
        # Development-only compatibility for the zero-DB mock stack. Production
        # refuses to start without APP_DB_URL, so configured deployments always
        # search the maintained stock_instruments pool.
        return await self._source.search_stocks(cleaned, bounded_limit)

    async def get_quotes(self, symbols: Sequence[str]) -> list[StockQuoteItem]:
        refs = _dedupe_quote_refs(symbols)
        quotes: list[StockQuoteItem] = []
        for market, symbol in refs[:100]:
            quote = await self._load(
                f"market:quote:{market}:{symbol}",
                lambda market=market, symbol=symbol: self._fetch_quote(market, symbol),
                _QUOTE_TTL,
            )
            if quote is not None:
                quotes.append(quote)
        return quotes

    async def _fetch_quote(self, market: str, symbol: str) -> StockQuoteItem | None:
        results = await self._source.search_stocks(symbol, 5)
        for item in results:
            if item.symbol == symbol and (not market or item.market == market):
                return _quote_from_stock(item)
        if results:
            return _quote_from_stock(results[0])
        return StockQuoteItem(symbol=symbol, market=market, updated_at=datetime.now(UTC))

    async def get_headlines(self, symbol: str | None = None) -> list[NewsItem]:
        key = f"market:headlines:{symbol or '*'}"
        return await self._load(key, lambda: self._source.fetch_headlines(symbol), self._headlines_ttl)

    async def get_news(self, category: str | None = None) -> list[NewsItem]:
        key = f"market:news:{category or '*'}"
        return await self._load(key, lambda: self._source.fetch_news(category), self._news_ttl)

    async def get_ai_hotspots(self) -> list[NewsItem]:
        return await self._load(_AI_HOTSPOTS_KEY, self._source.fetch_ai_hotspots, self._news_ttl)

    async def get_flash(self) -> list[FlashItem]:
        return await self._load(_FLASH_KEY, self._source.fetch_flash, self._flash_ttl)

    # ---- private watchlists -------------------------------------------------

    async def list_watchlists(self, user_id: str) -> list[Watchlist]:
        return await self._watchlists.list_watchlists(user_id)

    async def create_watchlist(self, user_id: str, watchlist: WatchlistCreate) -> Watchlist:
        return await self._watchlists.create_watchlist(user_id, watchlist)

    async def update_watchlist(self, user_id: str, watchlist_id: UUID, patch: WatchlistUpdate) -> Watchlist | None:
        return await self._watchlists.update_watchlist(user_id, watchlist_id, patch)

    async def delete_watchlist(self, user_id: str, watchlist_id: UUID) -> bool:
        return await self._watchlists.delete_watchlist(user_id, watchlist_id)

    async def list_default_watchlist_items(self, user_id: str) -> list[WatchlistItem]:
        return await self.list_watchlist_items(user_id, None)

    async def list_watchlist_items(self, user_id: str, watchlist_id: UUID | None) -> list[WatchlistItem]:
        return await self._watchlists.list_watchlist_items(user_id, watchlist_id)

    async def add_default_watchlist_item(self, user_id: str, item: WatchlistItemCreate) -> WatchlistItem:
        return await self.add_watchlist_item(user_id, None, item)

    async def add_watchlist_item(
        self,
        user_id: str,
        watchlist_id: UUID | None,
        item: WatchlistItemCreate,
    ) -> WatchlistItem:
        return await self._watchlists.add_watchlist_item(user_id, watchlist_id, item)

    async def remove_default_watchlist_item(self, user_id: str, symbol: str) -> None:
        await self.remove_watchlist_item(user_id, None, symbol)

    async def remove_watchlist_item(self, user_id: str, watchlist_id: UUID | None, symbol: str) -> bool:
        return await self._watchlists.remove_watchlist_item(user_id, watchlist_id, symbol)

    async def reorder_watchlist_items(
        self,
        user_id: str,
        watchlist_id: UUID | None,
        order: list[WatchlistItemOrder],
    ) -> list[WatchlistItem]:
        return await self._watchlists.reorder_watchlist_items(user_id, watchlist_id, order)

    # ---- refreshes (force fetch → cache → push; called by the worker) ------

    async def _publish(self, channel: str, items: Sequence[BaseModel]) -> None:
        # Best-effort: the cache is already fresh, so a push failure (whatever the
        # publisher impl) must never break the refresh. Log and move on.
        try:
            await self._publisher.publish(channel, {"items": [m.model_dump(mode="json") for m in items]})
        except Exception as exc:
            logger.warning("market: realtime publish to {} failed: {}", channel, exc)

    async def refresh_hotlist(self) -> list[HotItem]:
        data = await self._fill(_HOTLIST_KEY, self._source.fetch_hotlist, self._hotlist_ttl)
        await self._publish("market:hotlist", data)
        return data

    async def refresh_flash(self) -> list[FlashItem]:
        data = await self._fill(_FLASH_KEY, self._source.fetch_flash, self._flash_ttl)
        await self._publish("market:flash", data)
        return data

    async def refresh_ai_hotspots(self) -> list[NewsItem]:
        data = await self._fill(_AI_HOTSPOTS_KEY, self._source.fetch_ai_hotspots, self._news_ttl)
        await self._publish("market:ai-hotspots", data)
        return data

    async def sync_stock_pool(self) -> int:
        if isinstance(self._stocks, NoopStockInstrumentRepository):
            logger.info("market: skipped stock instrument sync because APP_DB_URL is not configured")
            return 0
        items = await self._source.list_stock_instruments()
        if not items:
            logger.warning("market: stock instrument source returned no rows; keeping existing pool")
            return 0
        synced = await self._stocks.replace_all(items)
        logger.info("market: synced {} stock instrument(s)", synced)
        return synced

    async def refresh_all(self) -> None:
        await self.refresh_hotlist()
        await self.refresh_ai_hotspots()
        await self.refresh_flash()


def _dedupe_quote_refs(symbols: Sequence[str]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in symbols:
        market, _, symbol = raw.strip().partition(":")
        if not symbol:
            symbol = market
            market = ""
        symbol = symbol.strip()
        market = market.strip()
        if not symbol:
            continue
        ref = (market, symbol)
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _quote_from_stock(item: StockSearchItem) -> StockQuoteItem:
    return StockQuoteItem(
        symbol=item.symbol,
        market=item.market,
        latest_price=item.latest_price,
        change_pct=item.change_pct,
        source=item.source,
        updated_at=item.updated_at,
    )
