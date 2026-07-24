"""Watchlist persistence boundary for the market module."""

from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import Lock
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from ...shared.db import ensure_db_pool_open
from .domain.models import (
    StockSearchItem,
    Watchlist,
    WatchlistCreate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistItemOrder,
    WatchlistUpdate,
)
from .market_ref import normalize_market

if TYPE_CHECKING:
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool
else:
    AsyncConnectionPool = Any
    DictRow = dict[str, Any]


class WatchlistRepository(ABC):
    @abstractmethod
    async def list_watchlists(self, user_id: str) -> list[Watchlist]:
        raise NotImplementedError

    @abstractmethod
    async def create_watchlist(self, user_id: str, watchlist: WatchlistCreate) -> Watchlist:
        raise NotImplementedError

    @abstractmethod
    async def update_watchlist(self, user_id: str, watchlist_id: UUID, patch: WatchlistUpdate) -> Watchlist | None:
        raise NotImplementedError

    @abstractmethod
    async def delete_watchlist(self, user_id: str, watchlist_id: UUID) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def list_watchlist_items(self, user_id: str, watchlist_id: UUID | None) -> list[WatchlistItem]:
        raise NotImplementedError

    @abstractmethod
    async def add_watchlist_item(self, user_id: str, watchlist_id: UUID | None, item: WatchlistItemCreate) -> WatchlistItem:
        raise NotImplementedError

    @abstractmethod
    async def remove_watchlist_item(self, user_id: str, watchlist_id: UUID | None, market: str, symbol: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def reorder_watchlist_items(
        self,
        user_id: str,
        watchlist_id: UUID | None,
        order: list[WatchlistItemOrder],
    ) -> list[WatchlistItem]:
        raise NotImplementedError


class InMemoryWatchlistRepository(WatchlistRepository):
    def __init__(self) -> None:
        self._lock = Lock()
        self._watchlists_by_user: dict[str, list[Watchlist]] = {}
        self._watchlist_items_by_user: dict[str, dict[UUID, list[WatchlistItem]]] = {}

    async def list_watchlists(self, user_id: str) -> list[Watchlist]:
        async with self._lock:
            self._ensure_default_watchlist(user_id)
            return list(self._watchlists_by_user[user_id])

    async def create_watchlist(self, user_id: str, watchlist: WatchlistCreate) -> Watchlist:
        async with self._lock:
            self._ensure_default_watchlist(user_id)
            name = watchlist.name.strip()
            for existing in self._watchlists_by_user[user_id]:
                if existing.name == name:
                    return existing
            now = datetime.now(UTC)
            created = Watchlist(
                id=uuid4(),
                name=name,
                is_default=False,
                sort_order=watchlist.sort_order,
                created_at=now,
                updated_at=now,
            )
            self._watchlists_by_user[user_id].append(created)
            self._watchlist_items_by_user.setdefault(user_id, {})[created.id] = []
            return created

    async def update_watchlist(self, user_id: str, watchlist_id: UUID, patch: WatchlistUpdate) -> Watchlist | None:
        async with self._lock:
            self._ensure_default_watchlist(user_id)
            user_watchlists = self._watchlists_by_user[user_id]
            for index, existing in enumerate(user_watchlists):
                if existing.id != watchlist_id:
                    continue
                updated = existing.model_copy(
                    update={
                        "name": patch.name.strip() if patch.name is not None else existing.name,
                        "sort_order": patch.sort_order if patch.sort_order is not None else existing.sort_order,
                        "updated_at": datetime.now(UTC),
                    }
                )
                user_watchlists[index] = updated
                return updated
            return None

    async def delete_watchlist(self, user_id: str, watchlist_id: UUID) -> bool:
        async with self._lock:
            self._ensure_default_watchlist(user_id)
            user_watchlists = self._watchlists_by_user[user_id]
            for existing in user_watchlists:
                if existing.id == watchlist_id and existing.is_default:
                    return False
            kept = [watchlist for watchlist in user_watchlists if watchlist.id != watchlist_id]
            deleted = len(kept) != len(user_watchlists)
            self._watchlists_by_user[user_id] = kept
            self._watchlist_items_by_user.setdefault(user_id, {}).pop(watchlist_id, None)
            return deleted

    async def list_watchlist_items(self, user_id: str, watchlist_id: UUID | None) -> list[WatchlistItem]:
        async with self._lock:
            resolved_id = self._resolve_watchlist_id(user_id, watchlist_id)
            if resolved_id is None:
                return []
            return list(self._watchlist_items_by_user[user_id].get(resolved_id, []))

    async def add_watchlist_item(self, user_id: str, watchlist_id: UUID | None, item: WatchlistItemCreate) -> WatchlistItem:
        async with self._lock:
            resolved_id = self._resolve_watchlist_id(user_id, watchlist_id)
            if resolved_id is None:
                raise KeyError("watchlist not found")
            items = self._watchlist_items_by_user[user_id].setdefault(resolved_id, [])
            normalized_market = normalize_market(item.market, item.symbol)
            for existing in items:
                if existing.instrument.symbol == item.symbol and existing.instrument.market == normalized_market:
                    return existing
            now = datetime.now(UTC)
            watchlist_item = WatchlistItem(
                id=uuid4(),
                instrument=_stock_from_create(item, normalized_market),
                sort_order=item.sort_order,
                note=item.note.strip(),
                created_at=now,
                updated_at=now,
            )
            items.insert(0, watchlist_item)
            return watchlist_item

    async def remove_watchlist_item(self, user_id: str, watchlist_id: UUID | None, market: str, symbol: str) -> bool:
        async with self._lock:
            resolved_id = self._resolve_watchlist_id(user_id, watchlist_id)
            if resolved_id is None:
                return False
            items = self._watchlist_items_by_user[user_id].setdefault(resolved_id, [])
            normalized_market = normalize_market(market, symbol)
            kept = [
                item
                for item in items
                if item.instrument.symbol != symbol or item.instrument.market != normalized_market
            ]
            self._watchlist_items_by_user[user_id][resolved_id] = kept
            return len(kept) != len(items)

    async def reorder_watchlist_items(
        self,
        user_id: str,
        watchlist_id: UUID | None,
        order: list[WatchlistItemOrder],
    ) -> list[WatchlistItem]:
        async with self._lock:
            resolved_id = self._resolve_watchlist_id(user_id, watchlist_id)
            if resolved_id is None:
                return []
            items = self._watchlist_items_by_user[user_id].setdefault(resolved_id, [])
            order_by_ref = {
                (normalize_market(entry.market, entry.symbol), entry.symbol): entry.sort_order
                for entry in order
            }
            updated = [
                item.model_copy(
                    update={
                        "sort_order": order_by_ref.get(
                            (item.instrument.market, item.instrument.symbol),
                            item.sort_order,
                        )
                    }
                )
                for item in items
            ]
            updated.sort(key=lambda item: (item.sort_order, item.created_at), reverse=False)
            self._watchlist_items_by_user[user_id][resolved_id] = updated
            return list(updated)

    def _ensure_default_watchlist(self, user_id: str) -> Watchlist:
        now = datetime.now(UTC)
        user_watchlists = self._watchlists_by_user.setdefault(user_id, [])
        for watchlist in user_watchlists:
            if watchlist.is_default:
                self._watchlist_items_by_user.setdefault(user_id, {}).setdefault(watchlist.id, [])
                return watchlist
        default_watchlist = Watchlist(
            id=uuid4(),
            name="default",
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        user_watchlists.append(default_watchlist)
        self._watchlist_items_by_user.setdefault(user_id, {})[default_watchlist.id] = []
        return default_watchlist

    def _resolve_watchlist_id(self, user_id: str, watchlist_id: UUID | None) -> UUID | None:
        if watchlist_id is None:
            return self._ensure_default_watchlist(user_id).id
        self._ensure_default_watchlist(user_id)
        if any(watchlist.id == watchlist_id for watchlist in self._watchlists_by_user[user_id]):
            self._watchlist_items_by_user.setdefault(user_id, {}).setdefault(watchlist_id, [])
            return watchlist_id
        return None


class PostgresWatchlistRepository(WatchlistRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def _open_pool(self) -> None:
        await ensure_db_pool_open(self._pool)

    async def list_watchlists(self, user_id: str) -> list[Watchlist]:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            await self._ensure_default_watchlist(conn, user_id)
            rows = await _fetch_all(
                conn,
                """
                    SELECT id, name, is_default, sort_order, created_at, updated_at
                    FROM market.watchlists
                    WHERE user_id = %s
                    ORDER BY sort_order, created_at
                    """,
                (user_id,),
            )
            return [_watchlist_from_row(row) for row in rows]

    async def create_watchlist(self, user_id: str, watchlist: WatchlistCreate) -> Watchlist:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            row = await _fetch_one(
                conn,
                """
                    INSERT INTO market.watchlists (user_id, name, is_default, sort_order)
                    VALUES (%s, %s, false, %s)
                    ON CONFLICT (user_id, name)
                    DO UPDATE SET sort_order = EXCLUDED.sort_order, updated_at = now()
                    RETURNING id, name, is_default, sort_order, created_at, updated_at
                    """,
                (user_id, watchlist.name.strip(), watchlist.sort_order),
            )
            return _watchlist_from_row(row)

    async def update_watchlist(self, user_id: str, watchlist_id: UUID, patch: WatchlistUpdate) -> Watchlist | None:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            row = await _fetch_optional(
                conn,
                """
                    UPDATE market.watchlists
                    SET
                      name = COALESCE(%s, name),
                      sort_order = COALESCE(%s, sort_order),
                      updated_at = now()
                    WHERE user_id = %s AND id = %s
                    RETURNING id, name, is_default, sort_order, created_at, updated_at
                    """,
                (patch.name.strip() if patch.name is not None else None, patch.sort_order, user_id, watchlist_id),
            )
            return _watchlist_from_row(row) if row is not None else None

    async def delete_watchlist(self, user_id: str, watchlist_id: UUID) -> bool:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            row = await _fetch_optional(
                conn,
                """
                    DELETE FROM market.watchlists
                    WHERE user_id = %s AND id = %s AND is_default = false
                    RETURNING id
                    """,
                (user_id, watchlist_id),
            )
            return row is not None

    async def list_watchlist_items(self, user_id: str, watchlist_id: UUID | None) -> list[WatchlistItem]:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            resolved_id = await self._resolve_watchlist_id(conn, user_id, watchlist_id)
            if resolved_id is None:
                return []
            rows = await _fetch_all(
                conn,
                """
                    SELECT
                      id,
                      symbol,
                      name,
                      market,
                      concept,
                      source,
                      stock_updated_at,
                      sort_order,
                      note,
                      created_at,
                      updated_at
                    FROM market.watchlist_items
                    WHERE user_id = %s AND watchlist_id = %s
                    ORDER BY sort_order, created_at DESC
                    """,
                (user_id, resolved_id),
            )
            return [_watchlist_item_from_row(row) for row in rows]

    async def add_watchlist_item(self, user_id: str, watchlist_id: UUID | None, item: WatchlistItemCreate) -> WatchlistItem:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            resolved_id = await self._resolve_watchlist_id(conn, user_id, watchlist_id)
            if resolved_id is None:
                raise KeyError("watchlist not found")
            normalized_market = normalize_market(item.market, item.symbol)
            row = await _fetch_one(
                conn,
                """
                    INSERT INTO market.watchlist_items (
                      user_id,
                      watchlist_id,
                      symbol,
                      name,
                      market,
                      concept,
                      source,
                      stock_updated_at,
                      sort_order,
                      note
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, watchlist_id, market, symbol)
                    DO UPDATE SET
                      name = EXCLUDED.name,
                      concept = EXCLUDED.concept,
                      source = EXCLUDED.source,
                      stock_updated_at = EXCLUDED.stock_updated_at,
                      updated_at = now()
                    RETURNING
                      id,
                      symbol,
                      name,
                      market,
                      concept,
                      source,
                      stock_updated_at,
                      sort_order,
                      note,
                      created_at,
                      updated_at
                    """,
                (
                    user_id,
                    resolved_id,
                    item.symbol.strip(),
                    item.name.strip(),
                    normalized_market,
                    item.concept.strip(),
                    item.source.strip(),
                    item.updated_at,
                    item.sort_order,
                    item.note.strip(),
                ),
            )
            return _watchlist_item_from_row(row)

    async def remove_watchlist_item(self, user_id: str, watchlist_id: UUID | None, market: str, symbol: str) -> bool:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            resolved_id = await self._resolve_watchlist_id(conn, user_id, watchlist_id)
            if resolved_id is None:
                return False
            normalized_market = normalize_market(market, symbol)
            row = await _fetch_optional(
                conn,
                """
                    DELETE FROM market.watchlist_items
                    WHERE user_id = %s AND watchlist_id = %s AND market = %s AND symbol = %s
                    RETURNING id
                    """,
                (user_id, resolved_id, normalized_market, symbol),
            )
            return row is not None

    async def reorder_watchlist_items(
        self,
        user_id: str,
        watchlist_id: UUID | None,
        order: list[WatchlistItemOrder],
    ) -> list[WatchlistItem]:
        await self._open_pool()
        async with self._pool.connection() as conn, conn.transaction():
            await _set_rls_user(conn, user_id)
            resolved_id = await self._resolve_watchlist_id(conn, user_id, watchlist_id)
            if resolved_id is None:
                return []
            for entry in order:
                await conn.execute(
                    """
                        UPDATE market.watchlist_items
                        SET sort_order = %s, updated_at = now()
                        WHERE user_id = %s AND watchlist_id = %s AND market = %s AND symbol = %s
                        """,
                    (
                        entry.sort_order,
                        user_id,
                        resolved_id,
                        normalize_market(entry.market, entry.symbol),
                        entry.symbol,
                    ),
                )
            rows = await _fetch_all(
                conn,
                """
                    SELECT
                      id,
                      symbol,
                      name,
                      market,
                      concept,
                      source,
                      stock_updated_at,
                      sort_order,
                      note,
                      created_at,
                      updated_at
                    FROM market.watchlist_items
                    WHERE user_id = %s AND watchlist_id = %s
                    ORDER BY sort_order, created_at DESC
                    """,
                (user_id, resolved_id),
            )
            return [_watchlist_item_from_row(row) for row in rows]

    async def _ensure_default_watchlist(self, conn: Any, user_id: str) -> UUID:
        row = await _fetch_one(
            conn,
            """
            INSERT INTO market.watchlists (user_id, name, is_default, sort_order)
            VALUES (%s, 'default', true, 0)
            ON CONFLICT (user_id, name)
            DO UPDATE SET is_default = true, updated_at = now()
            RETURNING id
            """,
            (user_id,),
        )
        return cast("UUID", row["id"])

    async def _resolve_watchlist_id(
        self,
        conn: Any,
        user_id: str,
        watchlist_id: UUID | None,
    ) -> UUID | None:
        if watchlist_id is None:
            return await self._ensure_default_watchlist(conn, user_id)
        row = await _fetch_optional(
            conn,
            """
                SELECT id
                FROM market.watchlists
                WHERE user_id = %s AND id = %s
                """,
            (user_id, watchlist_id),
        )
        return row["id"] if row is not None else None


async def _set_rls_user(conn: Any, user_id: str) -> None:
    await conn.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))


async def _fetch_one(conn: Any, sql: str, params: tuple[object, ...]) -> DictRow:
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("query returned no rows")
        return cast("DictRow", row)


async def _fetch_optional(conn: Any, sql: str, params: tuple[object, ...]) -> DictRow | None:
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        return cast("DictRow | None", await cur.fetchone())


async def _fetch_all(conn: Any, sql: str, params: tuple[object, ...]) -> list[DictRow]:
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        return list(await cur.fetchall())


def _stock_from_create(item: WatchlistItemCreate, market: str | None = None) -> StockSearchItem:
    return StockSearchItem(
        symbol=item.symbol.strip(),
        name=item.name.strip(),
        market=market if market is not None else normalize_market(item.market, item.symbol),
        latest_price=None,
        change_pct=None,
        concept=item.concept.strip(),
        source=item.source.strip(),
        updated_at=item.updated_at,
    )


def _watchlist_from_row(row: DictRow) -> Watchlist:
    return Watchlist(
        id=row["id"],
        name=row["name"],
        is_default=row["is_default"],
        sort_order=row["sort_order"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _watchlist_item_from_row(row: DictRow) -> WatchlistItem:
    return WatchlistItem(
        id=row["id"],
        instrument=StockSearchItem(
            symbol=row["symbol"],
            name=row["name"],
            market=row["market"],
            latest_price=None,
            change_pct=None,
            concept=row["concept"],
            source=row["source"],
            updated_at=row["stock_updated_at"],
        ),
        sort_order=row["sort_order"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
