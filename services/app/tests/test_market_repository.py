from __future__ import annotations

import asyncio

from apextran_app.modules.market.domain.models import (
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemOrder,
    WatchlistUpdate,
)
from apextran_app.modules.market.repository import InMemoryWatchlistRepository, _set_rls_user


def _item(symbol: str) -> WatchlistItemCreate:
    return WatchlistItemCreate(
        symbol=symbol,
        name=f"stock-{symbol}",
        market="A_SHARE",
        source="test",
        updated_at="2026-07-08T12:00:00Z",
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

        await repo.remove_watchlist_item("user-a", None, "600519")
        assert await repo.list_watchlist_items("user-a", None) == []

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
            [WatchlistItemOrder(symbol="300750", sort_order=0), WatchlistItemOrder(symbol="600519", sort_order=1)],
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
        await _set_rls_user(conn, "user-a")  # type: ignore[arg-type]
        assert conn.calls == [("SELECT set_config('app.user_id', %s, true)", ("user-a",))]

    asyncio.run(run())
