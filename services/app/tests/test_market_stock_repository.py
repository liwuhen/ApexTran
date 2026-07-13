from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from apextran_app.modules.market.adapters import MockMarketSource
from apextran_app.modules.market.domain.models import (
    HotItem,
    IntradaySeries,
    KlineBar,
    StockQuoteItem,
    StockSearchItem,
    WatchlistItemCreate,
)
from apextran_app.modules.market.market_ref import MARKET_SH_A, MARKET_SZ_A
from apextran_app.modules.market.repository import InMemoryWatchlistRepository
from apextran_app.modules.market.service import MarketService
from apextran_app.modules.market.snapshot_repository import (
    SNAPSHOT_REASON_HOTLIST,
    SNAPSHOT_REASON_RECENT_CHART,
    SNAPSHOT_REASON_WATCHLIST,
    InMemoryMarketSnapshotRepository,
)
from apextran_app.modules.market.stock_repository import StockInstrumentRepository
from apextran_app.shared.cache import InMemoryTTLCache


class FakeStockRepository(StockInstrumentRepository):
    def __init__(self, search_results: list[StockSearchItem] | None = None) -> None:
        self.search_results = search_results or []
        self.search_calls: list[tuple[str, int]] = []
        self.upserted: list[StockSearchItem] = []
        self.replaced: list[StockSearchItem] = []
        self.replace_calls = 0

    async def search(self, query: str, limit: int) -> list[StockSearchItem]:
        self.search_calls.append((query, limit))
        return self.search_results[:limit]

    async def upsert_many(self, items: list[StockSearchItem]) -> None:
        self.upserted.extend(items)

    async def replace_all(self, items: list[StockSearchItem]) -> int:
        self.replace_calls += 1
        self.replaced = list(items)
        return len(self.replaced)


class CountingSource(MockMarketSource):
    def __init__(self) -> None:
        self.hotlist_calls = 0
        self.search_calls = 0
        self.list_calls = 0
        self.daily_calls = 0
        self.intraday_calls = 0

    async def fetch_hotlist(self) -> list[HotItem]:
        self.hotlist_calls += 1
        return await super().fetch_hotlist()

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
        self.search_calls += 1
        return await super().search_stocks(query, limit)

    async def list_stock_instruments(self) -> list[StockSearchItem]:
        self.list_calls += 1
        return await super().list_stock_instruments()

    async def fetch_daily_kline(self, symbol: str, limit: int = 180) -> list[KlineBar]:
        self.daily_calls += 1
        return await super().fetch_daily_kline(symbol, limit)

    async def fetch_intraday(self, symbol: str) -> IntradaySeries:
        self.intraday_calls += 1
        return await super().fetch_intraday(symbol)


class RecordingSnapshotRepository(InMemoryMarketSnapshotRepository):
    def __init__(self, now_factory: Callable[[], datetime] | None = None) -> None:
        super().__init__(now_factory=now_factory)
        self.interest_writes: list[list[tuple[str, str, str]]] = []

    async def record_snapshot_interests(self, refs: list[tuple[str, str, str]]) -> None:
        self.interest_writes.append(list(refs))
        await super().record_snapshot_interests(refs)


class EmptyPoolSource(CountingSource):
    async def list_stock_instruments(self) -> list[StockSearchItem]:
        self.list_calls += 1
        return []


def _service(source: CountingSource, stocks: FakeStockRepository) -> MarketService:
    return MarketService(
        source=source,
        cache=InMemoryTTLCache(),
        hotlist_ttl=30,
        headlines_ttl=30,
        news_ttl=30,
        flash_ttl=30,
        stock_repository=stocks,
    )


def _snapshot_service(
    source: CountingSource,
    snapshots: InMemoryMarketSnapshotRepository,
    watchlists: InMemoryWatchlistRepository | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> MarketService:
    return MarketService(
        source=source,
        cache=InMemoryTTLCache(),
        hotlist_ttl=30,
        headlines_ttl=30,
        news_ttl=30,
        flash_ttl=30,
        watchlist_repository=watchlists,
        stock_repository=FakeStockRepository(),
        snapshot_repository=snapshots,
        now_factory=now_factory,
    )


def test_stock_search_prefers_repository_results() -> None:
    async def run() -> None:
        source = CountingSource()
        stocks = FakeStockRepository([
            StockSearchItem(
                symbol="600519",
                name="贵州茅台",
                market=MARKET_SH_A,
                latest_price=None,
                change_pct=None,
                concept="白酒",
                source="db",
                updated_at=datetime.now(UTC),
            )
        ])
        result = await _service(source, stocks).search_stocks("600519")
        assert [item.symbol for item in result] == ["600519"]
        assert source.search_calls == 0
        assert stocks.upserted == []

    asyncio.run(run())


def test_stock_search_uses_repository_only_when_repository_is_configured() -> None:
    async def run() -> None:
        source = CountingSource()
        stocks = FakeStockRepository()
        result = await _service(source, stocks).search_stocks("600519")
        assert result == []
        assert source.search_calls == 0
        assert stocks.upserted == []

    asyncio.run(run())


def test_sync_stock_pool_replaces_repository_pool() -> None:
    async def run() -> None:
        source = CountingSource()
        stocks = FakeStockRepository()
        synced = await _service(source, stocks).sync_stock_pool()
        assert synced == len(stocks.replaced)
        assert source.list_calls == 1
        assert {item.symbol for item in stocks.replaced} >= {"600519", "300750"}

    asyncio.run(run())


def test_sync_stock_pool_does_not_create_realtime_quote_snapshots() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        service = _snapshot_service(source, snapshots)

        synced = await service.sync_stock_pool()

        assert synced > 0
        assert source.list_calls == 1
        assert await snapshots.get_quote("600519", MARKET_SH_A) is None
        assert await snapshots.list_symbols_for_snapshot_refresh(10) == []

    asyncio.run(run())


def test_sync_stock_pool_keeps_existing_pool_when_source_is_empty() -> None:
    async def run() -> None:
        source = EmptyPoolSource()
        stocks = FakeStockRepository()
        synced = await _service(source, stocks).sync_stock_pool()
        assert synced == 0
        assert source.list_calls == 1
        assert stocks.replace_calls == 0

    asyncio.run(run())


def test_hotlist_reads_snapshot_without_source_fetch() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        service = _snapshot_service(source, snapshots)
        items = await source.fetch_hotlist()
        source.hotlist_calls = 0
        await snapshots.replace_hotlist(items)

        hotlist = await service.get_hotlist()

        assert [item.symbol for item in hotlist] == [item.symbol for item in items]
        assert source.hotlist_calls == 0

    asyncio.run(run())


def test_hotlist_returns_empty_snapshot_without_source_fetch_when_db_backed() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        service = _snapshot_service(source, snapshots)

        hotlist = await service.get_hotlist()

        assert hotlist == []
        assert source.hotlist_calls == 0

    asyncio.run(run())


def test_refresh_hotlist_writes_only_hotlist_snapshot() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        service = _snapshot_service(source, snapshots)

        refreshed = await service.refresh_hotlist()

        assert refreshed
        assert source.hotlist_calls == 1
        assert [item.symbol for item in await snapshots.get_hotlist()] == [item.symbol for item in refreshed]
        assert await snapshots.get_quote(refreshed[0].symbol, MARKET_SH_A) is None
        assert await snapshots.list_symbols_for_snapshot_refresh(20) == []
        assert await service.refresh_market_snapshots() == 0
        assert source.search_calls == 0
        assert source.daily_calls == 0
        assert source.intraday_calls == 0

    asyncio.run(run())


def test_stock_display_reads_snapshots_without_source_fetch() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        now = datetime.now(UTC)
        await snapshots.upsert_quotes([
            StockQuoteItem(
                symbol="600519",
                market=MARKET_SH_A,
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ])
        bars = [
            KlineBar(date="2026-07-08", open=10, high=11, low=9, close=10.5, volume=100),
            KlineBar(date="2026-07-09", open=10.5, high=12, low=10, close=11.5, volume=120),
        ]
        await snapshots.replace_daily_kline("600519", bars, MARKET_SH_A)
        series = IntradaySeries(
            symbol="600519",
            date="2026-07-10",
            prev_close=11.5,
            points=[],
            updated_at=now,
        )
        await snapshots.replace_intraday(series, MARKET_SH_A)

        service = _snapshot_service(source, snapshots)

        assert await service.get_quotes([f"{MARKET_SH_A}:600519"]) == [
            StockQuoteItem(
                symbol="600519",
                market=MARKET_SH_A,
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ]
        assert await service.get_daily_kline("600519") == bars
        assert await service.get_intraday("600519") == series
        assert source.search_calls == 0
        assert source.daily_calls == 0
        assert source.intraday_calls == 0

    asyncio.run(run())


def test_a_share_market_alias_normalizes_to_symbol_market() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        now = datetime.now(UTC)
        await snapshots.upsert_quotes([
            StockQuoteItem(
                symbol="600519",
                market=MARKET_SH_A,
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ])
        service = _snapshot_service(source, snapshots)

        quotes = await service.get_quotes(["A_SHARE:600519"])

        assert quotes == [
            StockQuoteItem(
                symbol="600519",
                market=MARKET_SH_A,
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ]
        assert await snapshots.list_symbols_for_snapshot_refresh(10) == []

    asyncio.run(run())


def test_snapshot_quote_write_infers_market_when_market_is_empty() -> None:
    async def run() -> None:
        snapshots = InMemoryMarketSnapshotRepository()
        now = datetime.now(UTC)
        await snapshots.upsert_quotes([
            StockQuoteItem(
                symbol="600519",
                market="",
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ])

        quote = await snapshots.get_quote("600519", MARKET_SH_A)

        assert quote == StockQuoteItem(
            symbol="600519",
            market=MARKET_SH_A,
            latest_price=1688.0,
            change_pct=1.2,
            source="snapshot",
            updated_at=now,
        )

    asyncio.run(run())


def test_quote_refs_dedupe_broad_market_aliases() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        now = datetime.now(UTC)
        await snapshots.upsert_quotes([
            StockQuoteItem(
                symbol="600519",
                market=MARKET_SH_A,
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ])
        service = _snapshot_service(source, snapshots)

        quotes = await service.get_quotes(["600519", "A_SHARE:600519", "A股:600519"])

        assert len(quotes) == 1
        assert quotes[0].market == MARKET_SH_A
        assert await snapshots.list_symbols_for_snapshot_refresh(10) == []

    asyncio.run(run())


def test_chart_snapshots_use_requested_market() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        market = MARKET_SZ_A
        now = datetime.now(UTC)
        bars = [
            KlineBar(date="2026-07-08", open=10, high=11, low=9, close=10.5, volume=100),
            KlineBar(date="2026-07-09", open=10.5, high=12, low=10, close=11.5, volume=120),
        ]
        series = IntradaySeries(
            symbol="300907",
            date="2026-07-10",
            prev_close=11.5,
            points=[],
            updated_at=now,
        )
        await snapshots.replace_daily_kline("300907", bars, market)
        await snapshots.replace_intraday(series, market)
        service = _snapshot_service(source, snapshots)

        assert await service.get_daily_kline("300907", market=market) == bars
        assert await service.get_intraday("300907", market=market) == series
        assert await service.get_daily_kline("300907") == bars
        assert await snapshots.list_symbols_for_snapshot_refresh(10) == [
            (market, "300907"),
        ]

    asyncio.run(run())


def test_missing_chart_snapshot_returns_empty_and_records_interest_without_source_fetch() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        service = _snapshot_service(source, snapshots)

        assert await service.get_daily_kline("600519") == []
        intraday = await service.get_intraday("600519")
        assert intraday.symbol == "600519"
        assert intraday.points == []
        assert source.daily_calls == 0
        assert source.intraday_calls == 0
        assert await snapshots.list_symbols_for_snapshot_refresh(10) == [(MARKET_SH_A, "600519")]

    asyncio.run(run())


def test_recent_chart_interest_is_rate_limited_between_chart_polls() -> None:
    async def run() -> None:
        clock = [datetime(2026, 7, 10, tzinfo=UTC)]

        def now() -> datetime:
            return clock[0]

        source = CountingSource()
        snapshots = RecordingSnapshotRepository(now_factory=now)
        service = _snapshot_service(source, snapshots, now_factory=now)

        await service.get_intraday("600519")
        await service.get_intraday("600519")
        await service.get_daily_kline("600519")

        assert snapshots.interest_writes == [[(MARKET_SH_A, "600519", SNAPSHOT_REASON_RECENT_CHART)]]

        clock[0] += timedelta(seconds=59)
        await service.get_intraday("600519")

        assert snapshots.interest_writes == [[(MARKET_SH_A, "600519", SNAPSHOT_REASON_RECENT_CHART)]]

        clock[0] += timedelta(seconds=1)
        await service.get_intraday("600519")

        assert snapshots.interest_writes == [
            [(MARKET_SH_A, "600519", SNAPSHOT_REASON_RECENT_CHART)],
            [(MARKET_SH_A, "600519", SNAPSHOT_REASON_RECENT_CHART)],
        ]

    asyncio.run(run())


def test_listing_existing_watchlist_items_does_not_record_snapshot_interest() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        watchlists = InMemoryWatchlistRepository()
        await watchlists.add_watchlist_item(
            "user-a",
            None,
            WatchlistItemCreate(
                symbol="600519",
                name="贵州茅台",
                market=MARKET_SH_A,
                updated_at=datetime.now(UTC),
            ),
        )
        service = _snapshot_service(source, snapshots, watchlists)

        items = await service.list_default_watchlist_items("user-a")

        assert [item.instrument.symbol for item in items] == ["600519"]
        assert await snapshots.list_symbols_for_snapshot_refresh(10) == []
        assert source.daily_calls == 0
        assert source.intraday_calls == 0

    asyncio.run(run())


def test_default_watchlist_items_can_include_quotes_by_market_and_symbol() -> None:
    async def run() -> None:
        now = datetime.now(UTC)
        source = CountingSource()
        snapshots = RecordingSnapshotRepository()
        watchlists = InMemoryWatchlistRepository()
        await watchlists.add_watchlist_item(
            "user-a",
            None,
            WatchlistItemCreate(
                symbol="600519",
                name="贵州茅台",
                market=MARKET_SH_A,
                updated_at=now,
            ),
        )
        await watchlists.add_watchlist_item(
            "user-a",
            None,
            WatchlistItemCreate(
                symbol="600519",
                name="same-code-other-market",
                market=MARKET_SZ_A,
                updated_at=now,
            ),
        )
        await snapshots.upsert_quotes([
            StockQuoteItem(
                symbol="600519",
                market=MARKET_SH_A,
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ])
        service = _snapshot_service(source, snapshots, watchlists)

        items = await service.list_default_watchlist_items("user-a", include_quotes=True)

        quotes_by_market = {item.instrument.market: item.quote for item in items}
        sh_quote = quotes_by_market[MARKET_SH_A]
        assert sh_quote is not None
        assert sh_quote.latest_price == 1688.0
        assert quotes_by_market[MARKET_SZ_A] is None
        assert snapshots.interest_writes == []

    asyncio.run(run())


def test_adding_watchlist_item_records_snapshot_interest_once() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = RecordingSnapshotRepository()
        watchlists = InMemoryWatchlistRepository()
        service = _snapshot_service(source, snapshots, watchlists)

        created = await service.add_default_watchlist_item(
            "user-a",
            WatchlistItemCreate(
                symbol="600519",
                name="贵州茅台",
                market="A_SHARE",
                updated_at=datetime.now(UTC),
            ),
        )

        assert created.instrument.market == MARKET_SH_A
        assert await snapshots.list_symbols_for_snapshot_refresh(10) == [(MARKET_SH_A, "600519")]
        assert snapshots.interest_writes == [[(MARKET_SH_A, "600519", SNAPSHOT_REASON_WATCHLIST)]]

        await service.list_default_watchlist_items("user-a")
        await service.get_quotes([f"{MARKET_SH_A}:600519"])
        await service.get_quotes([f"{MARKET_SH_A}:600519"])

        assert snapshots.interest_writes == [[(MARKET_SH_A, "600519", SNAPSHOT_REASON_WATCHLIST)]]

    asyncio.run(run())


def test_snapshot_refresh_candidates_prioritize_missing_watchlist_data() -> None:
    async def run() -> None:
        snapshots = InMemoryMarketSnapshotRepository()
        now = datetime.now(UTC)
        await snapshots.record_snapshot_interest("600519", MARKET_SH_A, SNAPSHOT_REASON_HOTLIST)
        await snapshots.record_snapshot_interest("000060", MARKET_SZ_A, SNAPSHOT_REASON_WATCHLIST)
        await snapshots.upsert_quotes([
            StockQuoteItem(
                symbol="600519",
                market=MARKET_SH_A,
                latest_price=1688.0,
                change_pct=1.2,
                source="snapshot",
                updated_at=now,
            )
        ])
        await snapshots.replace_daily_kline(
            "600519",
            [KlineBar(date="2026-07-10", open=10, high=11, low=9, close=10.5, volume=100)],
            MARKET_SH_A,
        )
        await snapshots.replace_intraday(
            IntradaySeries(
                symbol="600519",
                date="2026-07-10",
                prev_close=10,
                points=[],
                updated_at=now,
            ),
            MARKET_SH_A,
        )

        assert await snapshots.list_symbols_for_snapshot_refresh(2) == [
            (MARKET_SZ_A, "000060"),
            (MARKET_SH_A, "600519"),
        ]

    asyncio.run(run())


def test_refresh_market_snapshots_fetches_source_for_interested_symbols() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        await snapshots.record_snapshot_interest("600519", MARKET_SH_A, SNAPSHOT_REASON_RECENT_CHART)
        service = _snapshot_service(source, snapshots)

        refreshed = await service.refresh_market_snapshots()

        assert refreshed == 1
        assert source.search_calls == 1
        assert source.daily_calls == 1
        assert source.intraday_calls == 1
        assert await snapshots.get_quote("600519", MARKET_SH_A) is not None
        assert await snapshots.get_daily_kline("600519", 180, MARKET_SH_A)
        assert await snapshots.get_intraday("600519", MARKET_SH_A) is not None

    asyncio.run(run())


def test_refresh_market_snapshots_accepts_explicit_symbols() -> None:
    async def run() -> None:
        source = CountingSource()
        snapshots = InMemoryMarketSnapshotRepository()
        service = _snapshot_service(source, snapshots)

        refreshed = await service.refresh_market_snapshots(["600519"])

        assert refreshed == 1
        assert source.search_calls == 1
        assert source.daily_calls == 1
        assert source.intraday_calls == 1
        assert await snapshots.get_daily_kline("600519", 180, MARKET_SH_A)
        assert await snapshots.get_intraday("600519", MARKET_SH_A) is not None

    asyncio.run(run())
