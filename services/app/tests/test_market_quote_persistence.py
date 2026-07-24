from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from apextran_app.modules.market.domain.models import HotItem, StockQuoteItem
from apextran_app.modules.market.market_ref import MARKET_SH_A
from apextran_app.modules.market.snapshot_repository import (
    RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS,
    SNAPSHOT_REASON_RECENT_CHART,
    SNAPSHOT_REASON_WATCHLIST,
    InMemoryMarketSnapshotRepository,
    PostgresMarketSnapshotRepository,
)
from apextran_app.modules.market.stock_repository import PostgresStockInstrumentRepository


class _AsyncContext:
    def __init__(self, value: Any) -> None:
        self._value = value

    async def __aenter__(self) -> Any:
        return self._value

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executions.append((sql, params))

    async def executemany(self, sql: str, params: list[tuple[object, ...]]) -> None:
        self.executions.append((sql, tuple(params)))

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def transaction(self) -> _AsyncContext:
        return _AsyncContext(None)


class _FakePool:
    closed = False

    def __init__(self, cursor: _FakeCursor) -> None:
        self._connection = _FakeConnection(cursor)

    def connection(self) -> _AsyncContext:
        return _AsyncContext(self._connection)


def _quote(updated_at: datetime, **metrics: float | None) -> StockQuoteItem:
    return StockQuoteItem(
        symbol="600519",
        market=MARKET_SH_A,
        latest_price=1688.0,
        change_pct=1.2,
        turnover_rate=metrics.get("turnover_rate"),
        amount=metrics.get("amount"),
        float_market_cap=metrics.get("float_market_cap"),
        total_market_cap=metrics.get("total_market_cap"),
        source="test",
        updated_at=updated_at,
    )


def _hot_item(symbol: str, rank: int) -> HotItem:
    return HotItem(
        rank=rank,
        symbol=symbol,
        name=f"股票{symbol}",
        boards=0,
        change_pct=1.2,
        hot_score=100 - rank,
        sources=["测试"],
        updated_at=datetime.now(UTC),
    )


def test_postgres_hotlist_replace_uses_one_batch_insert() -> None:
    async def run() -> None:
        cursor = _FakeCursor()
        repository = PostgresMarketSnapshotRepository(_FakePool(cursor))  # type: ignore[arg-type]

        await repository.replace_hotlist([_hot_item("600519", 2), _hot_item("300750", 1)])

        insert_calls = [call for call in cursor.executions if "INSERT INTO market.stock_hotlist_snapshots" in call[0]]
        assert len(insert_calls) == 1
        insert_sql, params = insert_calls[0]
        assert "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)" in insert_sql
        assert len(params) == 2
        batch_params = cast(tuple[tuple[object, ...], ...], params)
        assert batch_params[0][1] == "300750"
        assert batch_params[1][1] == "600519"
        assert any(sql == "DELETE FROM market.stock_hotlist_snapshots" for sql, _params in cursor.executions)

    asyncio.run(run())


def test_in_memory_quote_upsert_keeps_existing_metrics_when_replacement_omits_them() -> None:
    async def run() -> None:
        repository = InMemoryMarketSnapshotRepository()
        updated_at = datetime.now(UTC)
        await repository.upsert_quotes([
            _quote(
                updated_at,
                turnover_rate=2.3,
                amount=4_500_000_000.0,
                float_market_cap=1_900_000_000_000.0,
                total_market_cap=2_100_000_000_000.0,
            )
        ])
        replacement = _quote(updated_at + timedelta(minutes=1))
        replacement.latest_price = 1690.0
        replacement.change_pct = 1.4
        replacement.source = "hotlist"

        await repository.upsert_quotes([replacement])

        stored = await repository.get_quote("600519", MARKET_SH_A)
        assert stored is not None
        assert stored.latest_price == 1690.0
        assert stored.change_pct == 1.4
        assert stored.turnover_rate == 2.3
        assert stored.amount == 4_500_000_000.0
        assert stored.float_market_cap == 1_900_000_000_000.0
        assert stored.total_market_cap == 2_100_000_000_000.0

    asyncio.run(run())


def test_postgres_quote_repository_reads_and_upserts_metrics() -> None:
    async def run() -> None:
        updated_at = datetime.now(UTC)
        row = {
            "symbol": "600519",
            "market": MARKET_SH_A,
            "latest_price": 1688.0,
            "change_pct": 1.2,
            "turnover_rate": 2.3,
            "amount": 4_500_000_000.0,
            "float_market_cap": 1_900_000_000_000.0,
            "total_market_cap": 2_100_000_000_000.0,
            "source": "test",
            "updated_at": updated_at,
        }
        cursor = _FakeCursor([row])
        repository = PostgresMarketSnapshotRepository(_FakePool(cursor))  # type: ignore[arg-type]

        stored = await repository.get_quote("600519", MARKET_SH_A)
        assert stored is not None
        assert stored == _quote(
            updated_at,
            turnover_rate=2.3,
            amount=4_500_000_000.0,
            float_market_cap=1_900_000_000_000.0,
            total_market_cap=2_100_000_000_000.0,
        )

        await repository.upsert_quotes([stored])

        insert_sql, params = next(call for call in cursor.executions if "INSERT INTO" in call[0])
        assert "turnover_rate = COALESCE(EXCLUDED.turnover_rate, existing.turnover_rate)" in insert_sql
        assert "amount = COALESCE(EXCLUDED.amount, existing.amount)" in insert_sql
        assert "float_market_cap = COALESCE(EXCLUDED.float_market_cap, existing.float_market_cap)" in insert_sql
        assert "total_market_cap = COALESCE(EXCLUDED.total_market_cap, existing.total_market_cap)" in insert_sql
        assert params[4:8] == (2.3, 4_500_000_000.0, 1_900_000_000_000.0, 2_100_000_000_000.0)

    asyncio.run(run())


def test_postgres_quote_repository_reads_multiple_quotes_in_one_query() -> None:
    async def run() -> None:
        updated_at = datetime.now(UTC)
        common = {
            "market": MARKET_SH_A,
            "latest_price": 1688.0,
            "change_pct": 1.2,
            "turnover_rate": 2.3,
            "amount": 4_500_000_000.0,
            "float_market_cap": 1_900_000_000_000.0,
            "total_market_cap": 2_100_000_000_000.0,
            "source": "test",
            "updated_at": updated_at,
        }
        cursor = _FakeCursor([
            {**common, "symbol": "000001"},
            {**common, "symbol": "600519"},
        ])
        repository = PostgresMarketSnapshotRepository(_FakePool(cursor))  # type: ignore[arg-type]

        quotes = await repository.get_quotes([
            (MARKET_SH_A, "600519"),
            (MARKET_SH_A, "000001"),
        ])

        assert [quote.symbol for quote in quotes] == ["600519", "000001"]
        select_calls = [call for call in cursor.executions if "FROM market.stock_quote_snapshots" in call[0]]
        assert len(select_calls) == 1
        sql, params = select_calls[0]
        assert "SELECT * FROM unnest(%s::text[], %s::text[])" in sql
        assert params == ([MARKET_SH_A, MARKET_SH_A], ["600519", "000001"])

    asyncio.run(run())


def test_postgres_snapshot_interest_update_rate_limits_recent_chart_reason() -> None:
    async def run() -> None:
        cursor = _FakeCursor()
        repository = PostgresMarketSnapshotRepository(_FakePool(cursor))  # type: ignore[arg-type]

        await repository.record_snapshot_interests([
            (MARKET_SH_A, "600519", SNAPSHOT_REASON_RECENT_CHART),
            (MARKET_SH_A, "000001", SNAPSHOT_REASON_WATCHLIST),
        ])

        insert_calls = [call for call in cursor.executions if "INSERT INTO market.stock_snapshot_interests" in call[0]]
        assert len(insert_calls) == 2
        insert_sql, recent_chart_params = insert_calls[0]
        assert "INSERT INTO market.stock_snapshot_interests AS interest" in insert_sql
        assert "WHERE EXCLUDED.reason <> %s" in insert_sql
        assert "interest.last_requested_at <= now() - (%s * interval '1 second')" in insert_sql
        assert recent_chart_params == (
            MARKET_SH_A,
            "600519",
            SNAPSHOT_REASON_RECENT_CHART,
            SNAPSHOT_REASON_RECENT_CHART,
            RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS,
        )
        assert insert_calls[1][1] == (
            MARKET_SH_A,
            "000001",
            SNAPSHOT_REASON_WATCHLIST,
            SNAPSHOT_REASON_RECENT_CHART,
            RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS,
        )

    asyncio.run(run())


def test_postgres_stock_search_returns_quote_metrics() -> None:
    async def run() -> None:
        updated_at = datetime.now(UTC)
        cursor = _FakeCursor([
            {
                "symbol": "600519",
                "market": MARKET_SH_A,
                "name": "Kweichow Moutai",
                "latest_price": 1688.0,
                "change_pct": 1.2,
                "turnover_rate": 2.3,
                "amount": 4_500_000_000.0,
                "float_market_cap": 1_900_000_000_000.0,
                "total_market_cap": 2_100_000_000_000.0,
                "concept": "liquor",
                "source": "test",
                "updated_at": updated_at,
            }
        ])
        repository = PostgresStockInstrumentRepository(_FakePool(cursor))  # type: ignore[arg-type]

        results = await repository.search("600519", 20)

        assert len(results) == 1
        assert results[0].turnover_rate == 2.3
        assert results[0].amount == 4_500_000_000.0
        assert results[0].float_market_cap == 1_900_000_000_000.0
        assert results[0].total_market_cap == 2_100_000_000_000.0
        search_sql = cursor.executions[0][0]
        assert "quote.turnover_rate" in search_sql
        assert "quote.total_market_cap" in search_sql

    asyncio.run(run())
