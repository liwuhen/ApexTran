from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apextran_app.modules.market.domain.models import (
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemOrder,
    WatchlistUpdate,
)
from apextran_app.modules.market.market_ref import MARKET_SH_A, MARKET_SZ_A
from apextran_app.modules.market.repository import InMemoryWatchlistRepository, _set_rls_user


def _item(symbol: str, market: str = MARKET_SH_A) -> WatchlistItemCreate:
    return WatchlistItemCreate(
        symbol=symbol,
        name=f"stock-{symbol}",
        market=market,
        source="test",
        updated_at=datetime(2026, 7, 8, 12, tzinfo=UTC),
    )


def test_in_memory_watchlist_repository_isolates_users_and_dedupes() -> None:
    async def run() -> None:
        repo = InMemoryWatchlistRepository()
        first = await repo.add_watchlist_item("user-a", None, _item("600519"))
        second = await repo.add_watchlist_item("user-a", None, _item("600519"))
        assert first.id == second.id
        assert [item.instrument.symbol for item in await repo.list_watchlist_items("user-a", None)] == ["600519"]
        assert first.instrument.latest_price is None
        assert first.instrument.change_pct is None
        assert await repo.list_watchlist_items("user-b", None) == []

        await repo.remove_watchlist_item("user-a", None, MARKET_SH_A, "600519")
        assert await repo.list_watchlist_items("user-a", None) == []

    asyncio.run(run())


def test_in_memory_watchlist_repository_removes_by_market_and_symbol() -> None:
    async def run() -> None:
        repo = InMemoryWatchlistRepository()
        await repo.add_watchlist_item("user-a", None, _item("000001", MARKET_SH_A))
        await repo.add_watchlist_item("user-a", None, _item("000001", MARKET_SZ_A))

        assert await repo.remove_watchlist_item("user-a", None, MARKET_SZ_A, "000001") is True

        remaining = await repo.list_watchlist_items("user-a", None)
        assert [(item.instrument.market, item.instrument.symbol) for item in remaining] == [(MARKET_SH_A, "000001")]

    asyncio.run(run())


def test_in_memory_watchlist_repository_supports_groups_and_ordering() -> None:
    async def run() -> None:
        repo = InMemoryWatchlistRepository()
        watchlist = await repo.create_watchlist("user-a", WatchlistCreate(name="long", sort_order=2))
        updated = await repo.update_watchlist("user-a", watchlist.id, WatchlistUpdate(name="long-term", sort_order=1))
        assert updated is not None
        assert updated.name == "long-term"
        assert updated.sort_order == 1

        await repo.add_watchlist_item("user-a", watchlist.id, _item("600519"))
        await repo.add_watchlist_item("user-a", watchlist.id, _item("300750"))
        ordered = await repo.reorder_watchlist_items(
            "user-a",
            watchlist.id,
            [
                WatchlistItemOrder(market=MARKET_SH_A, symbol="300750", sort_order=0),
                WatchlistItemOrder(market=MARKET_SH_A, symbol="600519", sort_order=1),
            ],
        )
        assert [item.instrument.symbol for item in ordered] == ["300750", "600519"]

        assert await repo.delete_watchlist("user-a", watchlist.id) is True
        assert await repo.list_watchlist_items("user-a", watchlist.id) == []

    asyncio.run(run())


def test_set_rls_user_uses_transaction_local_setting() -> None:
    class FakeConn:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[str]]] = []

        async def execute(self, sql: str, params: tuple[str]) -> None:
            self.calls.append((sql, params))

    async def run() -> None:
        conn = FakeConn()
        await _set_rls_user(conn, "user-a")
        assert conn.calls == [("SELECT set_config('app.user_id', %s, true)", ("user-a",))]

    asyncio.run(run())
