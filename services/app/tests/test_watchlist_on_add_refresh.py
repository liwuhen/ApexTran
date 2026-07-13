"""Adding a watchlist item seeds a day-level quote and queues an immediate
realtime refresh (bounded on-add fast path); every failure defers to the worker
cycle instead of breaking the add."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from apextran_app.modules.market.adapters import MockMarketSource
from apextran_app.modules.market.domain.models import (
    StockQuoteItem,
    StockSearchItem,
    WatchlistItemCreate,
)
from apextran_app.modules.market.market_ref import MARKET_SH_A
from apextran_app.modules.market.service import MarketService
from apextran_app.modules.market.snapshot_repository import InMemoryMarketSnapshotRepository
from apextran_app.modules.market.stock_repository import StockInstrumentRepository
from apextran_app.shared.cache import InMemoryTTLCache

_SYMBOL = "600519"
_NOW = datetime(2026, 7, 10, 6, 30, tzinfo=UTC)


class _CountingSource(MockMarketSource):
    """The on-add refresh resolves quotes through ``search_stocks`` — count it."""

    def __init__(self) -> None:
        self.quote_lookups = 0

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
        self.quote_lookups += 1
        return await super().search_stocks(query, limit)


class _PoolStockRepository(StockInstrumentRepository):
    """Stock pool with day-level stats, as stock_instruments provides after sync."""

    def __init__(self, items: list[StockSearchItem]) -> None:
        self._items = items

    async def search(self, query: str, limit: int) -> list[StockSearchItem]:
        return [item for item in self._items if query in item.symbol][:limit]

    async def upsert_many(self, items: list[StockSearchItem]) -> None:
        self._items.extend(items)

    async def replace_all(self, items: list[StockSearchItem]) -> int:
        self._items = list(items)
        return len(items)


def _pool_stock(symbol: str = _SYMBOL) -> StockSearchItem:
    return StockSearchItem(
        symbol=symbol,
        name="贵州茅台",
        market=MARKET_SH_A,
        latest_price=1888.0,
        change_pct=1.2,
        turnover_rate=0.4,
        amount=5_000_000_000.0,
        float_market_cap=2.3e12,
        total_market_cap=2.4e12,
        concept="白酒",
        source="eastmoney",
        updated_at=_NOW,
    )


def _create_payload(symbol: str = _SYMBOL) -> WatchlistItemCreate:
    return WatchlistItemCreate(symbol=symbol, name="贵州茅台", market=MARKET_SH_A, updated_at=_NOW)


def _service(
    *,
    source: MockMarketSource | None = None,
    snapshots: InMemoryMarketSnapshotRepository | None = None,
    stocks: StockInstrumentRepository | None = None,
    refresh_on_add: bool = True,
) -> MarketService:
    return MarketService(
        source=source or MockMarketSource(),
        cache=InMemoryTTLCache(),
        hotlist_ttl=30,
        headlines_ttl=30,
        news_ttl=30,
        flash_ttl=30,
        snapshot_repository=snapshots or InMemoryMarketSnapshotRepository(),
        stock_repository=stocks,
        refresh_on_add=refresh_on_add,
    )


@pytest.mark.asyncio
async def test_add_seeds_day_level_quote_from_stock_pool() -> None:
    snapshots = InMemoryMarketSnapshotRepository()
    service = _service(
        snapshots=snapshots,
        stocks=_PoolStockRepository([_pool_stock()]),
        refresh_on_add=False,  # isolate the seed from the queue
    )

    await service.add_default_watchlist_item("user-a", _create_payload())

    quotes = await snapshots.get_quotes([(MARKET_SH_A, _SYMBOL)])
    assert len(quotes) == 1
    assert quotes[0].latest_price == 1888.0
    assert quotes[0].source == "stock_pool"


@pytest.mark.asyncio
async def test_seed_never_overwrites_an_existing_quote() -> None:
    snapshots = InMemoryMarketSnapshotRepository()
    live = StockQuoteItem(symbol=_SYMBOL, market=MARKET_SH_A, latest_price=1901.5, source="live", updated_at=_NOW)
    await snapshots.upsert_quotes([live])
    service = _service(
        snapshots=snapshots,
        stocks=_PoolStockRepository([_pool_stock()]),
        refresh_on_add=False,
    )

    await service.add_default_watchlist_item("user-a", _create_payload())

    quotes = await snapshots.get_quotes([(MARKET_SH_A, _SYMBOL)])
    assert quotes[0].latest_price == 1901.5
    assert quotes[0].source == "live"


@pytest.mark.asyncio
async def test_add_queues_an_immediate_realtime_refresh() -> None:
    source = _CountingSource()
    snapshots = InMemoryMarketSnapshotRepository()
    service = _service(source=source, snapshots=snapshots)

    await service.add_default_watchlist_item("user-a", _create_payload())
    await service.wait_for_on_add_refreshes()

    quotes = await snapshots.get_quotes([(MARKET_SH_A, _SYMBOL)])
    assert len(quotes) == 1
    assert quotes[0].source == "MockWire"  # realtime fetch overwrote/filled the snapshot
    assert source.quote_lookups == 1

    # Charts are prefetched in the same pass (in parallel with the quote), so
    # the chart dialog is warm by the time the user opens it.
    bars = await snapshots.get_daily_kline(_SYMBOL, 180, MARKET_SH_A)
    assert len(bars) > 0
    intraday = await snapshots.get_intraday(_SYMBOL, MARKET_SH_A)
    assert intraday is not None
    assert len(intraday.points) > 0


@pytest.mark.asyncio
async def test_rapid_duplicate_adds_hit_upstream_once() -> None:
    source = _CountingSource()
    service = _service(source=source)

    await service.add_default_watchlist_item("user-a", _create_payload())
    await service.add_default_watchlist_item("user-b", _create_payload())
    await service.wait_for_on_add_refreshes()

    # Either the pending-set or the dedupe marker collapses the second request.
    assert source.quote_lookups == 1


@pytest.mark.asyncio
async def test_flag_off_leaves_refresh_to_the_worker_cycle() -> None:
    source = _CountingSource()
    service = _service(source=source, refresh_on_add=False)

    await service.add_default_watchlist_item("user-a", _create_payload())
    await asyncio.sleep(0)  # give any (wrongly) spawned task a chance to run

    assert source.quote_lookups == 0


@pytest.mark.asyncio
async def test_failed_refresh_does_not_break_the_add() -> None:
    class _BrokenSource(MockMarketSource):
        async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
            raise ConnectionError("upstream down")

    snapshots = InMemoryMarketSnapshotRepository()
    service = _service(source=_BrokenSource(), snapshots=snapshots)

    created = await service.add_default_watchlist_item("user-a", _create_payload())
    await service.wait_for_on_add_refreshes()

    assert created.instrument.symbol == _SYMBOL
    items = await service.list_default_watchlist_items("user-a")
    assert [item.instrument.symbol for item in items] == [_SYMBOL]

    # The quote fetch failed, but the parallel refresh isolates failures: the
    # chart snapshots still land.
    bars = await snapshots.get_daily_kline(_SYMBOL, 180, MARKET_SH_A)
    assert len(bars) > 0
    intraday = await snapshots.get_intraday(_SYMBOL, MARKET_SH_A)
    assert intraday is not None
