from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apextran_app.modules.market.adapters import MockMarketSource
from apextran_app.modules.market.domain.models import StockSearchItem
from apextran_app.modules.market.service import MarketService
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
        self.search_calls = 0
        self.list_calls = 0

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
        self.search_calls += 1
        return await super().search_stocks(query, limit)

    async def list_stock_instruments(self) -> list[StockSearchItem]:
        self.list_calls += 1
        return await super().list_stock_instruments()


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


def test_stock_search_prefers_repository_results() -> None:
    async def run() -> None:
        source = CountingSource()
        stocks = FakeStockRepository(
            [
                StockSearchItem(
                    symbol="600519",
                    name="贵州茅台",
                    market="A_SHARE",
                    latest_price=None,
                    change_pct=None,
                    concept="白酒",
                    source="db",
                    updated_at=datetime.now(UTC),
                )
            ]
        )
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


def test_sync_stock_pool_keeps_existing_pool_when_source_is_empty() -> None:
    async def run() -> None:
        source = EmptyPoolSource()
        stocks = FakeStockRepository()
        synced = await _service(source, stocks).sync_stock_pool()
        assert synced == 0
        assert source.list_calls == 1
        assert stocks.replace_calls == 0

    asyncio.run(run())
