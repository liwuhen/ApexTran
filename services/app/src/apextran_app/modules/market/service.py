"""Market application service — orchestrates source + cache.

Reads serve from cache; on miss they fetch from the source through a
**single-flight** so concurrent misses on the same key collapse to one upstream
call (no thundering herd). ``refresh_*`` force a fetch and are what the worker
calls on a schedule. The cache is the fan-out point: one fetch, served to N.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar, cast
from uuid import UUID

from loguru import logger
from pydantic import BaseModel

from ...shared.cache import Cache
from ...shared.realtime import NoopPublisher, RealtimePublisher
from ...shared.singleflight import SingleFlight
from .domain.models import (
    FlashItem,
    HotItem,
    IntradaySeries,
    KlineBar,
    NewsItem,
    StockQuoteItem,
    StockSearchItem,
    Watchlist,
    WatchlistCreate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistItemOrder,
    WatchlistItemWithQuote,
    WatchlistUpdate,
)
from .market_ref import normalize_market
from .ports import MarketSource
from .repository import InMemoryWatchlistRepository, WatchlistRepository
from .snapshot_repository import (
    RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS,
    SNAPSHOT_REASON_RECENT_CHART,
    SNAPSHOT_REASON_WATCHLIST,
    MarketSnapshotRepository,
    NoopMarketSnapshotRepository,
)
from .stock_repository import NoopStockInstrumentRepository, StockInstrumentRepository

T = TypeVar("T")

_HOTLIST_KEY = "market:hotlist"
_FLASH_KEY = "market:flash"
_AI_HOTSPOTS_KEY = "market:ai-hotspots"
_RECENT_CHART_INTEREST_UPDATE_INTERVAL = timedelta(seconds=RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS)

# A long-lived mirror of the last good value per key, so a source outage serves
# stale data instead of an error (stale-while-revalidate). §8.1.
_STALE_TTL = 86400.0

# On-add refresh fast path: a bounded in-process queue drained by a fixed pool of
# consumers, so a burst of concurrent adds can never flood the upstream source or
# the to_thread executor. Overflow is dropped — the interest row is already
# recorded, so the worker cycle refreshes the symbol within one interval anyway.
_ON_ADD_QUEUE_SIZE = 256
_ON_ADD_CONCURRENCY = 2
# Cross-replica dedupe marker TTL (best-effort get+set; upserts are idempotent).
_ON_ADD_MARKER_TTL = 10.0

# On-read chart fill: the first reader of a symbol with no chart snapshot fills
# it from the source (single-flight, bounded, time-boxed) and persists it, so
# every later reader — any user — hits the snapshot. A slow upstream answers
# empty instead of stalling the request; the fill keeps running in the
# background and the client's regular poll picks up the persisted result.
_CHART_FILL_CONCURRENCY = 4


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
        snapshot_repository: MarketSnapshotRepository | None = None,
        request_source_fallback: bool = False,
        snapshot_symbol_limit: int = 100,
        refresh_on_add: bool = False,
        chart_fill_on_read: bool = False,
        chart_fill_timeout: float = 3.0,
        now_factory: Callable[[], datetime] | None = None,
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
        self._snapshots = snapshot_repository or NoopMarketSnapshotRepository()
        self._request_source_fallback = request_source_fallback
        self._snapshot_symbol_limit = max(1, snapshot_symbol_limit)
        self._now_factory = now_factory or _utcnow
        self._snapshot_interest_recorded_at: dict[tuple[str, str, str], datetime] = {}
        self._refresh_on_add = refresh_on_add
        self._on_add_queue: asyncio.Queue[tuple[str, str]] | None = None
        self._on_add_pending: set[tuple[str, str]] = set()
        self._on_add_consumers: list[asyncio.Task[None]] = []
        self._chart_fill_on_read = chart_fill_on_read
        self._chart_fill_timeout = chart_fill_timeout
        self._chart_fill_semaphore = asyncio.Semaphore(_CHART_FILL_CONCURRENCY)
        self._chart_fill_tasks: set[asyncio.Task[Any]] = set()

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
        snapshot = await self._snapshots.get_hotlist()
        if snapshot or not self._request_source_fallback:
            return snapshot
        data = await self.refresh_hotlist()
        return data

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
        refs = _dedupe_refs(_raw_quote_refs(symbols), 100)
        quotes_by_ref = await self._get_quotes_by_ref(refs)
        return [quotes_by_ref[ref] for ref in refs if ref in quotes_by_ref]

    async def _get_quotes_by_ref(self, refs: Sequence[tuple[str, str]]) -> dict[tuple[str, str], StockQuoteItem]:
        quotes_by_ref = {
            (normalize_market(quote.market, quote.symbol), quote.symbol): quote
            for quote in await self._snapshots.get_quotes(refs)
        }
        if self._request_source_fallback:
            for market, symbol in refs:
                if (market, symbol) in quotes_by_ref:
                    continue
                quote = await self._refresh_quote_snapshot(market, symbol)
                if quote is not None:
                    quotes_by_ref[(market, symbol)] = quote
        return quotes_by_ref

    async def _fetch_quote(self, market: str, symbol: str) -> StockQuoteItem | None:
        results = await self._source.search_stocks(symbol, 5)
        for item in results:
            if item.symbol == symbol and (not market or item.market == market):
                return _quote_from_stock(item)
        if results:
            return _quote_from_stock(results[0])
        return StockQuoteItem(symbol=symbol, market=market, updated_at=datetime.now(UTC))

    async def get_daily_kline(self, symbol: str, limit: int = 180, market: str = "") -> list[KlineBar]:
        snapshot_market = normalize_market(market, symbol)
        await self._record_snapshot_interests([(snapshot_market, symbol)], SNAPSHOT_REASON_RECENT_CHART)
        bars = await self._snapshots.get_daily_kline(symbol, limit, snapshot_market)
        if bars:
            return bars
        if self._request_source_fallback:
            return await self._refresh_daily_kline_snapshot(snapshot_market, symbol, limit)
        if self._chart_fill_on_read:
            return await self._fill_chart_on_read(
                f"kline:{snapshot_market}:{symbol}",
                lambda: self._refresh_daily_kline_snapshot(snapshot_market, symbol, limit),
                default=[],
            )
        return bars

    async def get_intraday(self, symbol: str, market: str = "") -> IntradaySeries:
        snapshot_market = normalize_market(market, symbol)
        await self._record_snapshot_interests([(snapshot_market, symbol)], SNAPSHOT_REASON_RECENT_CHART)
        series = await self._snapshots.get_intraday(symbol, snapshot_market)
        if series is not None:
            return series
        if self._request_source_fallback:
            return await self._refresh_intraday_snapshot(snapshot_market, symbol)
        empty = IntradaySeries(symbol=symbol, date="", prev_close=None, points=[], updated_at=datetime.now(UTC))
        if self._chart_fill_on_read:
            return await self._fill_chart_on_read(
                f"intraday:{snapshot_market}:{symbol}",
                lambda: self._refresh_intraday_snapshot(snapshot_market, symbol),
                default=empty,
            )
        return empty

    async def _fill_chart_on_read(self, key: str, fill: Callable[[], Awaitable[T]], *, default: T) -> T:
        """First reader fills the missing chart snapshot from the source.

        Guards, in order: single-flight collapses concurrent readers of the same
        symbol; a semaphore bounds how many distinct symbols fill at once; the
        fill runs as a detached task so a timeout abandons only the *wait* — the
        fetch itself finishes in the background and persists the snapshot for
        the client's next poll. (Cancelling inside the single-flight producer
        would strand its followers, hence shield + detached task.)
        """

        async def _bounded_fill() -> T:
            async with self._chart_fill_semaphore:
                return await fill()

        task = asyncio.create_task(self._sf.run(f"chartfill:{key}", _bounded_fill))
        self._chart_fill_tasks.add(task)
        task.add_done_callback(self._chart_fill_tasks.discard)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self._chart_fill_timeout)
        except TimeoutError:
            logger.warning("market: chart fill for {} timed out; continuing in background", key)
            task.add_done_callback(_log_background_fill_failure(key))
            return default
        except Exception as exc:
            logger.warning("market: chart fill for {} failed: {}", key, exc)
            return default

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

    async def list_default_watchlist_items(
        self,
        user_id: str,
        *,
        include_quotes: bool = False,
    ) -> list[WatchlistItemWithQuote]:
        return await self.list_watchlist_items(user_id, None, include_quotes=include_quotes)

    async def list_watchlist_items(
        self,
        user_id: str,
        watchlist_id: UUID | None,
        *,
        include_quotes: bool = False,
    ) -> list[WatchlistItemWithQuote]:
        items = [
            WatchlistItemWithQuote(**item.model_dump())
            for item in await self._watchlists.list_watchlist_items(user_id, watchlist_id)
        ]
        if not include_quotes:
            return items
        return await self._attach_watchlist_quotes(items)

    async def _attach_watchlist_quotes(
        self,
        items: Sequence[WatchlistItem],
    ) -> list[WatchlistItemWithQuote]:
        refs = _dedupe_refs(
            [(item.instrument.market, item.instrument.symbol) for item in items],
            max(len(items), 1),
        )
        quotes_by_ref = await self._get_quotes_by_ref(refs)
        return [
            WatchlistItemWithQuote(
                **item.model_dump(exclude={"quote"}),
                quote=quotes_by_ref.get(_watchlist_item_ref(item)),
            )
            for item in items
        ]

    async def add_default_watchlist_item(self, user_id: str, item: WatchlistItemCreate) -> WatchlistItem:
        return await self.add_watchlist_item(user_id, None, item)

    async def add_watchlist_item(
        self,
        user_id: str,
        watchlist_id: UUID | None,
        item: WatchlistItemCreate,
    ) -> WatchlistItem:
        created = await self._watchlists.add_watchlist_item(user_id, watchlist_id, item)
        market = normalize_market(created.instrument.market, created.instrument.symbol)
        symbol = created.instrument.symbol
        await self._record_snapshot_interests([(market, symbol)], SNAPSHOT_REASON_WATCHLIST)
        await self._seed_watchlist_quote(market, symbol)
        self._enqueue_on_add_refresh(market, symbol)
        return created

    async def _seed_watchlist_quote(self, market: str, symbol: str) -> None:
        """Best-effort day-level seed from the stock pool, so a brand-new symbol
        renders numbers on the very next read instead of "--" until the realtime
        refresh lands. Never overwrites an existing (possibly realtime) quote."""
        try:
            if await self._snapshots.get_quotes([(market, symbol)]):
                return
            for stock in await self._stocks.search(symbol, 5):
                if stock.symbol == symbol and (not market or normalize_market(stock.market, stock.symbol) == market):
                    seeded = _quote_from_stock(stock).model_copy(update={"market": market, "source": "stock_pool"})
                    await self._snapshots.upsert_quotes([seeded])
                    return
        except Exception as exc:
            logger.warning("market: seeding quote for {}:{} failed: {}", market, symbol, exc)

    # ---- on-add refresh fast path (bounded queue + fixed consumers) ---------

    def _enqueue_on_add_refresh(self, market: str, symbol: str) -> None:
        if not self._refresh_on_add:
            return
        ref = (market, symbol)
        if ref in self._on_add_pending:
            return
        queue = self._ensure_on_add_refresh_workers()
        try:
            queue.put_nowait(ref)
            self._on_add_pending.add(ref)
        except asyncio.QueueFull:
            logger.warning("market: on-add refresh queue full; {}:{} defers to the worker cycle", market, symbol)

    def _ensure_on_add_refresh_workers(self) -> asyncio.Queue[tuple[str, str]]:
        # Lazily created so the service can be constructed outside an event loop.
        if self._on_add_queue is None:
            self._on_add_queue = asyncio.Queue(maxsize=_ON_ADD_QUEUE_SIZE)
            self._on_add_consumers = [
                asyncio.create_task(self._consume_on_add_refreshes()) for _ in range(_ON_ADD_CONCURRENCY)
            ]
        return self._on_add_queue

    async def _consume_on_add_refreshes(self) -> None:
        queue = self._on_add_queue
        if queue is None:  # pragma: no cover — consumers only start after queue creation
            return
        while True:
            market, symbol = await queue.get()
            try:
                await self._refresh_on_add_ref(market, symbol)
            except Exception as exc:
                # The interest row is already recorded; the worker cycle is the retry.
                logger.warning("market: on-add refresh for {}:{} failed: {}", market, symbol, exc)
            finally:
                self._on_add_pending.discard((market, symbol))
                queue.task_done()

    async def _refresh_on_add_ref(self, market: str, symbol: str) -> None:
        marker = f"market:onadd:{market}:{symbol}"
        if await self._cache.get(marker) is not None:
            return
        await self._cache.set(marker, True, ttl=_ON_ADD_MARKER_TTL)
        await self._sf.run(f"onadd:{market}:{symbol}", lambda: self._refresh_on_add_snapshots(market, symbol))

    async def _refresh_on_add_snapshots(self, market: str, symbol: str) -> None:
        # Quote and charts in parallel: the item's wall time stays ~one upstream
        # call, so prefetching charts never slows the queue down (and never
        # delays the quotes of later-queued symbols). Each part fails alone.
        results = await asyncio.gather(
            self._refresh_quote_snapshot(market, symbol),
            self._refresh_daily_kline_snapshot(market, symbol),
            self._refresh_intraday_snapshot(market, symbol),
            return_exceptions=True,
        )
        for kind, result in zip(("quote", "kline", "intraday"), results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("market: on-add {} refresh for {}:{} failed: {}", kind, market, symbol, result)

    async def wait_for_on_add_refreshes(self) -> None:
        """Drain the on-add refresh queue. Intended for tests and shutdown hooks."""
        if self._on_add_queue is not None:
            await self._on_add_queue.join()

    async def remove_default_watchlist_item(self, user_id: str, market: str, symbol: str) -> None:
        await self.remove_watchlist_item(user_id, None, market, symbol)

    async def remove_watchlist_item(self, user_id: str, watchlist_id: UUID | None, market: str, symbol: str) -> bool:
        return await self._watchlists.remove_watchlist_item(user_id, watchlist_id, market, symbol)

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
        await self._record_hotlist_snapshots(data)
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

    async def refresh_market_snapshots(self, symbols: Sequence[str] | None = None) -> int:
        refs = (
            _dedupe_refs(_raw_quote_refs(symbols), self._snapshot_symbol_limit)
            if symbols is not None
            else await self._snapshot_refresh_candidates()
        )
        refreshed = 0
        for market, symbol in refs:
            try:
                await self._refresh_quote_snapshot(market, symbol)
                await self._refresh_daily_kline_snapshot(market, symbol)
                await self._refresh_intraday_snapshot(market, symbol)
                refreshed += 1
            except Exception as exc:
                logger.warning("market: snapshot refresh for {}:{} failed: {}", market, symbol, exc)
        if refreshed:
            logger.info("market: refreshed {} stock snapshot(s)", refreshed)
        return refreshed

    async def _record_hotlist_snapshots(self, items: list[HotItem]) -> None:
        await self._snapshots.replace_hotlist(items)

    async def _record_snapshot_interests(self, refs: Sequence[tuple[str, str]], reason: str) -> None:
        now = self._now_factory()
        cleaned_reason = reason.strip() or SNAPSHOT_REASON_RECENT_CHART
        interests: list[tuple[str, str, str]] = []
        for market, symbol in refs:
            cleaned_symbol = symbol.strip()
            if not cleaned_symbol:
                continue
            interest = (normalize_market(market, cleaned_symbol), cleaned_symbol, cleaned_reason)
            if cleaned_reason == SNAPSHOT_REASON_RECENT_CHART:
                recorded_at = self._snapshot_interest_recorded_at.get(interest)
                if recorded_at is not None and now - recorded_at < _RECENT_CHART_INTEREST_UPDATE_INTERVAL:
                    continue
            interests.append(interest)
        if not interests:
            return
        try:
            await self._snapshots.record_snapshot_interests(interests)
            for interest in interests:
                if interest[2] == SNAPSHOT_REASON_RECENT_CHART:
                    self._snapshot_interest_recorded_at[interest] = now
        except Exception as exc:
            logger.warning("market: recording snapshot interest failed: {}", exc)

    async def _snapshot_refresh_candidates(self) -> list[tuple[str, str]]:
        return await self._snapshots.list_symbols_for_snapshot_refresh(self._snapshot_symbol_limit)

    async def _refresh_quote_snapshot(self, market: str, symbol: str) -> StockQuoteItem | None:
        quote = await self._fetch_quote(market, symbol)
        if quote is not None and _quote_has_data(quote):
            stored_quote = quote.model_copy(update={"market": normalize_market(market or quote.market, symbol)})
            await self._snapshots.upsert_quotes([stored_quote])
            return stored_quote
        return quote

    async def _refresh_daily_kline_snapshot(
        self,
        market: str,
        symbol: str,
        limit: int = 180,
    ) -> list[KlineBar]:
        bars = await self._source.fetch_daily_kline(symbol, limit)
        if bars:
            await self._snapshots.replace_daily_kline(symbol, bars, market)
        return bars

    async def _refresh_intraday_snapshot(self, market: str, symbol: str) -> IntradaySeries:
        series = await self._source.fetch_intraday(symbol)
        if series.date:
            await self._snapshots.replace_intraday(series, market)
        return series

    async def refresh_all(self) -> None:
        await self.refresh_hotlist()
        await self.refresh_ai_hotspots()
        await self.refresh_flash()


def _raw_quote_refs(symbols: Sequence[str]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for raw in symbols:
        market, _, symbol = raw.strip().partition(":")
        if not symbol:
            symbol = market
            market = ""
        symbol = symbol.strip()
        market = market.strip()
        if not symbol:
            continue
        refs.append((market, symbol))
    return refs


def _dedupe_refs(refs: Sequence[tuple[str, str]], limit: int) -> list[tuple[str, str]]:
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for market, symbol in refs:
        cleaned_symbol = symbol.strip()
        normalized = (normalize_market(market, cleaned_symbol), cleaned_symbol)
        if not normalized[1] or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def _watchlist_item_ref(item: WatchlistItem) -> tuple[str, str]:
    return (normalize_market(item.instrument.market, item.instrument.symbol), item.instrument.symbol)


def _quote_has_data(item: StockQuoteItem) -> bool:
    values = (
        item.latest_price,
        item.change_pct,
        item.turnover_rate,
        item.amount,
        item.float_market_cap,
        item.total_market_cap,
    )
    return any(value is not None for value in values) or bool(item.source.strip())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _log_background_fill_failure(key: str) -> Callable[[asyncio.Task[Any]], None]:
    # Retrieve the abandoned task's exception so the loop never reports
    # "exception was never retrieved" for a fill we deliberately walked away from.
    def _callback(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("market: background chart fill for {} failed: {}", key, exc)

    return _callback


def _quote_from_stock(item: StockSearchItem) -> StockQuoteItem:
    return StockQuoteItem(
        symbol=item.symbol,
        market=item.market,
        latest_price=item.latest_price,
        change_pct=item.change_pct,
        turnover_rate=item.turnover_rate,
        amount=item.amount,
        float_market_cap=item.float_market_cap,
        total_market_cap=item.total_market_cap,
        source=item.source,
        updated_at=item.updated_at,
    )
