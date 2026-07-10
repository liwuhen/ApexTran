"""Stock instrument persistence and search boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ...shared.db import ensure_db_pool_open
from .domain.models import StockSearchItem

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool
else:
    AsyncConnection = Any
    AsyncConnectionPool = Any
    DictRow = dict[str, Any]


class StockInstrumentRepository(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int) -> list[StockSearchItem]:
        raise NotImplementedError

    @abstractmethod
    async def upsert_many(self, items: list[StockSearchItem]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def replace_all(self, items: list[StockSearchItem]) -> int:
        raise NotImplementedError


class NoopStockInstrumentRepository(StockInstrumentRepository):
    async def search(self, query: str, limit: int) -> list[StockSearchItem]:
        return []

    async def upsert_many(self, items: list[StockSearchItem]) -> None:
        return None

    async def replace_all(self, items: list[StockSearchItem]) -> int:
        return 0


class PostgresStockInstrumentRepository(StockInstrumentRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def search(self, query: str, limit: int) -> list[StockSearchItem]:
        prefix = f"{query}%"
        contains = f"%{query}%"
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn:
            rows = await _fetch_all(
                conn,
                """
                SELECT
                  symbol,
                  market,
                  name,
                  NULL::double precision AS latest_price,
                  NULL::double precision AS change_pct,
                  concept,
                  source,
                  updated_at
                FROM market.stock_instruments
                WHERE status = 'active'
                  AND (
                    symbol ILIKE %s
                    OR name ILIKE %s
                    OR pinyin ILIKE %s
                    OR pinyin_abbr ILIKE %s
                    OR similarity(name, %s) > 0.3
                  )
                ORDER BY
                  CASE
                    WHEN symbol = %s THEN 0
                    WHEN symbol ILIKE %s THEN 1
                    WHEN name = %s THEN 2
                    WHEN name ILIKE %s THEN 3
                    WHEN pinyin_abbr ILIKE %s THEN 4
                    ELSE 5
                  END,
                  symbol
                LIMIT %s
                """,
                (prefix, contains, contains, prefix, query, query, prefix, query, prefix, prefix, limit),
            )
            return [_stock_from_row(row) for row in rows]

    async def upsert_many(self, items: list[StockSearchItem]) -> None:
        if not items:
            return
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            for item in items:
                await _upsert_stock(cur, item)

    async def replace_all(self, items: list[StockSearchItem]) -> int:
        if not items:
            return 0
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TEMP TABLE tmp_stock_instrument_sync (
                  market TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  PRIMARY KEY (market, symbol)
                ) ON COMMIT DROP
                """
            )
            markets: set[str] = set()
            synced = 0
            for item in items:
                symbol = item.symbol.strip()
                name = item.name.strip() or symbol
                if not symbol or not name:
                    continue
                market = item.market.strip()
                markets.add(market)
                await _upsert_stock(cur, item)
                await cur.execute(
                    """
                    INSERT INTO tmp_stock_instrument_sync (market, symbol)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (market, symbol),
                )
                synced += 1

            if markets:
                await cur.execute(
                    """
                    UPDATE market.stock_instruments AS stock
                    SET status = 'inactive',
                        updated_at = now()
                    WHERE stock.status = 'active'
                      AND stock.market = ANY(%s)
                      AND NOT EXISTS (
                        SELECT 1
                        FROM tmp_stock_instrument_sync AS synced
                        WHERE synced.market = stock.market
                          AND synced.symbol = stock.symbol
                      )
                    """,
                    (sorted(markets),),
                )
            return synced


async def _fetch_all(conn: AsyncConnection[DictRow], sql: str, params: tuple[object, ...]) -> list[DictRow]:
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        return list(await cur.fetchall())


async def _upsert_stock(cur: Any, item: StockSearchItem) -> None:
    symbol = item.symbol.strip()
    name = item.name.strip() or symbol
    if not symbol or not name:
        return
    await cur.execute(
        """
        INSERT INTO market.stock_instruments (
          symbol,
          market,
          exchange,
          name,
          industry,
          concept,
          source,
          status,
          updated_at
        )
        VALUES (%s, %s, %s, %s, '', %s, %s, 'active', %s)
        ON CONFLICT (market, symbol)
        DO UPDATE SET
          name = EXCLUDED.name,
          exchange = EXCLUDED.exchange,
          concept = EXCLUDED.concept,
          source = EXCLUDED.source,
          status = 'active',
          updated_at = EXCLUDED.updated_at
        """,
        (
            symbol,
            item.market.strip(),
            _exchange_for_symbol(symbol),
            name,
            item.concept.strip(),
            item.source.strip(),
            item.updated_at,
        ),
    )


def _stock_from_row(row: DictRow) -> StockSearchItem:
    return StockSearchItem(
        symbol=row["symbol"],
        name=row["name"],
        market=row["market"],
        latest_price=row["latest_price"],
        change_pct=row["change_pct"],
        concept=row["concept"],
        source=row["source"],
        updated_at=row["updated_at"],
    )


def _exchange_for_symbol(symbol: str) -> str:
    if symbol.startswith(("60", "68", "90")):
        return "SSE"
    if symbol.startswith(("00", "30", "20")):
        return "SZSE"
    if symbol.startswith(("43", "83", "87", "88")):
        return "BSE"
    return ""
