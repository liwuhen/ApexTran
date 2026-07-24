"""Local market snapshot persistence for quotes and chart data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ...shared.db import ensure_db_pool_open
from .domain.models import HotItem, IntradayPoint, IntradaySeries, KlineBar, StockQuoteItem
from .market_ref import normalize_market

if TYPE_CHECKING:
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool
else:
    AsyncConnectionPool = Any
    DictRow = dict[str, Any]

SNAPSHOT_REASON_HOTLIST = "hotlist"
SNAPSHOT_REASON_RECENT_CHART = "recent_chart"
SNAPSHOT_REASON_WATCHLIST = "watchlist"
RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS = 60
_RECENT_INTEREST_DAYS = 14
_RECENT_CHART_INTEREST_UPDATE_INTERVAL = timedelta(seconds=RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS)
_REASON_RANK = {
    SNAPSHOT_REASON_WATCHLIST: 0,
    SNAPSHOT_REASON_RECENT_CHART: 1,
    SNAPSHOT_REASON_HOTLIST: 2,
}


class MarketSnapshotRepository(ABC):
    @abstractmethod
    async def get_hotlist(self, limit: int = 100) -> list[HotItem]:
        raise NotImplementedError

    @abstractmethod
    async def replace_hotlist(self, items: list[HotItem]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_quote(self, symbol: str, market: str = "") -> StockQuoteItem | None:
        raise NotImplementedError

    async def get_quotes(self, refs: Sequence[tuple[str, str]]) -> list[StockQuoteItem]:
        """Read multiple quote snapshots while preserving the requested order.

        Implementations backed by a database should override this method with a
        single batch query. The default keeps lightweight test/development
        repositories compatible and provides a safe fallback for custom ports.
        """
        quotes: list[StockQuoteItem] = []
        for market, symbol in refs:
            quote = await self.get_quote(symbol, market)
            if quote is not None:
                quotes.append(quote)
        return quotes

    @abstractmethod
    async def upsert_quotes(self, items: list[StockQuoteItem]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_daily_kline(self, symbol: str, limit: int, market: str = "") -> list[KlineBar]:
        raise NotImplementedError

    @abstractmethod
    async def replace_daily_kline(self, symbol: str, bars: list[KlineBar], market: str = "", source: str = "") -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_intraday(self, symbol: str, market: str = "") -> IntradaySeries | None:
        raise NotImplementedError

    @abstractmethod
    async def replace_intraday(self, series: IntradaySeries, market: str = "", source: str = "") -> None:
        raise NotImplementedError

    async def record_snapshot_interest(
        self,
        symbol: str,
        market: str = "",
        reason: str = SNAPSHOT_REASON_RECENT_CHART,
    ) -> None:
        await self.record_snapshot_interests([(market, symbol, reason)])

    @abstractmethod
    async def record_snapshot_interests(self, refs: list[tuple[str, str, str]]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_symbols_for_snapshot_refresh(self, limit: int) -> list[tuple[str, str]]:
        raise NotImplementedError


class NoopMarketSnapshotRepository(MarketSnapshotRepository):
    async def get_hotlist(self, limit: int = 100) -> list[HotItem]:
        return []

    async def replace_hotlist(self, items: list[HotItem]) -> None:
        return None

    async def get_quote(self, symbol: str, market: str = "") -> StockQuoteItem | None:
        return None

    async def get_quotes(self, refs: Sequence[tuple[str, str]]) -> list[StockQuoteItem]:
        return []

    async def upsert_quotes(self, items: list[StockQuoteItem]) -> None:
        return None

    async def get_daily_kline(self, symbol: str, limit: int, market: str = "") -> list[KlineBar]:
        return []

    async def replace_daily_kline(self, symbol: str, bars: list[KlineBar], market: str = "", source: str = "") -> None:
        return None

    async def get_intraday(self, symbol: str, market: str = "") -> IntradaySeries | None:
        return None

    async def replace_intraday(self, series: IntradaySeries, market: str = "", source: str = "") -> None:
        return None

    async def record_snapshot_interests(self, refs: list[tuple[str, str, str]]) -> None:
        return None

    async def list_symbols_for_snapshot_refresh(self, limit: int) -> list[tuple[str, str]]:
        return []


class InMemoryMarketSnapshotRepository(MarketSnapshotRepository):
    def __init__(self, now_factory: Callable[[], datetime] | None = None) -> None:
        self._hotlist: list[HotItem] = []
        self._quotes: dict[tuple[str, str], StockQuoteItem] = {}
        self._daily: dict[tuple[str, str], list[KlineBar]] = {}
        self._intraday: dict[tuple[str, str], IntradaySeries] = {}
        self._interests: dict[tuple[str, str, str], datetime] = {}
        self._now_factory = now_factory or _utcnow

    async def get_hotlist(self, limit: int = 100) -> list[HotItem]:
        bounded_limit = max(1, min(limit, 500))
        return sorted(self._hotlist, key=lambda item: item.rank)[:bounded_limit]

    async def replace_hotlist(self, items: list[HotItem]) -> None:
        self._hotlist = sorted(items, key=lambda item: item.rank)

    async def get_quote(self, symbol: str, market: str = "") -> StockQuoteItem | None:
        return self._quotes.get(_ref(market, symbol))

    async def get_quotes(self, refs: Sequence[tuple[str, str]]) -> list[StockQuoteItem]:
        quotes: list[StockQuoteItem] = []
        seen: set[tuple[str, str]] = set()
        for market, symbol in refs:
            ref = _ref(market, symbol)
            if not ref[1] or ref in seen:
                continue
            seen.add(ref)
            quote = self._quotes.get(ref)
            if quote is not None:
                quotes.append(quote)
        return quotes

    async def upsert_quotes(self, items: list[StockQuoteItem]) -> None:
        for item in items:
            symbol = item.symbol.strip()
            if not symbol:
                continue
            normalized_market = _market(item.market, symbol)
            ref = (normalized_market, symbol)
            existing = self._quotes.get(ref)
            updates: dict[str, object] = {"market": normalized_market}
            if existing is not None:
                updates.update({
                    "turnover_rate": item.turnover_rate if item.turnover_rate is not None else existing.turnover_rate,
                    "amount": item.amount if item.amount is not None else existing.amount,
                    "float_market_cap": item.float_market_cap
                    if item.float_market_cap is not None
                    else existing.float_market_cap,
                    "total_market_cap": item.total_market_cap
                    if item.total_market_cap is not None
                    else existing.total_market_cap,
                })
            self._quotes[ref] = item.model_copy(update=updates)

    async def get_daily_kline(self, symbol: str, limit: int, market: str = "") -> list[KlineBar]:
        bars = self._daily.get(_ref(market, symbol), [])
        return sorted(bars, key=lambda bar: bar.date)[-limit:]

    async def replace_daily_kline(self, symbol: str, bars: list[KlineBar], market: str = "", source: str = "") -> None:
        normalized = _ref(market, symbol)
        if bars:
            self._daily[normalized] = sorted(bars, key=lambda bar: bar.date)

    async def get_intraday(self, symbol: str, market: str = "") -> IntradaySeries | None:
        return self._intraday.get(_ref(market, symbol))

    async def replace_intraday(self, series: IntradaySeries, market: str = "", source: str = "") -> None:
        symbol = series.symbol.strip()
        if not symbol or not series.date:
            return
        self._intraday[_ref(market, symbol)] = series

    async def record_snapshot_interests(self, refs: list[tuple[str, str, str]]) -> None:
        now = self._now_factory()
        for market, symbol, reason in refs:
            cleaned_symbol = symbol.strip()
            cleaned_reason = reason.strip() or SNAPSHOT_REASON_RECENT_CHART
            if cleaned_symbol:
                ref = (_market(market, cleaned_symbol), cleaned_symbol, cleaned_reason)
                requested_at = self._interests.get(ref)
                if (
                    cleaned_reason == SNAPSHOT_REASON_RECENT_CHART
                    and requested_at is not None
                    and now - requested_at < _RECENT_CHART_INTEREST_UPDATE_INTERVAL
                ):
                    continue
                self._interests[ref] = now

    async def list_symbols_for_snapshot_refresh(self, limit: int) -> list[tuple[str, str]]:
        candidates: dict[tuple[str, str], tuple[bool, int, datetime]] = {}
        for (market, symbol, reason), requested_at in self._interests.items():
            ref = (market, symbol)
            is_missing = ref not in self._quotes or ref not in self._daily or ref not in self._intraday
            rank = _reason_rank(reason)
            current = candidates.get(ref)
            if current is None:
                candidates[ref] = (is_missing, rank, requested_at)
                continue
            current_missing, current_rank, current_requested_at = current
            candidates[ref] = (
                is_missing or current_missing,
                min(rank, current_rank),
                max(requested_at, current_requested_at),
            )
        ordered = sorted(
            candidates.items(),
            key=lambda item: (
                not item[1][0],
                item[1][1],
                -item[1][2].timestamp(),
            ),
        )
        return [ref for ref, _meta in ordered[:limit]]


class PostgresMarketSnapshotRepository(MarketSnapshotRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_hotlist(self, limit: int = 100) -> list[HotItem]:
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn:
            rows = await _fetch_all(
                conn,
                """
                SELECT
                  rank,
                  symbol,
                  name,
                  boards,
                  change_pct,
                  reason,
                  concept,
                  hot_score,
                  latest_price,
                  eastmoney_rank,
                  tonghuashun_rank,
                  kai_pan_la_rank,
                  tao_gu_ba_rank,
                  sources,
                  updated_at
                FROM market.stock_hotlist_snapshots
                ORDER BY rank, symbol
                LIMIT %s
                """,
                (max(1, min(limit, 500)),),
            )
        return [_hot_item_from_row(row) for row in rows]

    async def replace_hotlist(self, items: list[HotItem]) -> None:
        if not items:
            return

        # ``stock_hotlist_snapshots`` is a complete current-state snapshot: rows
        # that are absent from the new result must disappear. Keep that semantic,
        # but use psycopg's optimized batch API so a refresh does not pay one
        # Python/database round trip per stock.
        rows: list[tuple[object, ...]] = []
        for item in sorted(items, key=lambda row: row.rank):
            symbol = item.symbol.strip()
            name = item.name.strip() or symbol
            if not symbol or not name:
                continue
            rows.append(
                (
                    item.rank,
                    symbol,
                    name,
                    item.boards,
                    item.change_pct,
                    item.reason.strip(),
                    item.concept.strip(),
                    item.hot_score,
                    item.latest_price,
                    item.eastmoney_rank,
                    item.tonghuashun_rank,
                    item.kai_pan_la_rank,
                    item.tao_gu_ba_rank,
                    item.sources,
                    item.updated_at,
                )
            )
        if not rows:
            return

        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute("DELETE FROM market.stock_hotlist_snapshots")
            await cur.executemany(
                """
                INSERT INTO market.stock_hotlist_snapshots (
                  rank,
                  symbol,
                  name,
                  boards,
                  change_pct,
                  reason,
                  concept,
                  hot_score,
                  latest_price,
                  eastmoney_rank,
                  tonghuashun_rank,
                  kai_pan_la_rank,
                  tao_gu_ba_rank,
                  sources,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )

    async def get_quote(self, symbol: str, market: str = "") -> StockQuoteItem | None:
        normalized_market, normalized_symbol = _ref(market, symbol)
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn:
            rows = await _fetch_all(
                conn,
                """
                SELECT
                  symbol,
                  market,
                  latest_price,
                  change_pct,
                  turnover_rate,
                  amount,
                  float_market_cap,
                  total_market_cap,
                  source,
                  updated_at
                FROM market.stock_quote_snapshots
                WHERE symbol = %s
                  AND market = %s
                LIMIT 1
                """,
                (normalized_symbol, normalized_market),
            )
        return _quote_from_row(rows[0]) if rows else None

    async def get_quotes(self, refs: Sequence[tuple[str, str]]) -> list[StockQuoteItem]:
        normalized_refs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for market, symbol in refs:
            ref = _ref(market, symbol)
            if not ref[1] or ref in seen:
                continue
            seen.add(ref)
            normalized_refs.append(ref)
        if not normalized_refs:
            return []

        markets = [market for market, _symbol in normalized_refs]
        symbols = [symbol for _market_name, symbol in normalized_refs]
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn:
            rows = await _fetch_all(
                conn,
                """
                WITH requested(market, symbol) AS (
                  SELECT * FROM unnest(%s::text[], %s::text[])
                )
                SELECT
                  quote.symbol,
                  quote.market,
                  quote.latest_price,
                  quote.change_pct,
                  quote.turnover_rate,
                  quote.amount,
                  quote.float_market_cap,
                  quote.total_market_cap,
                  quote.source,
                  quote.updated_at
                FROM market.stock_quote_snapshots AS quote
                INNER JOIN requested
                  ON requested.market = quote.market
                 AND requested.symbol = quote.symbol
                """,
                (markets, symbols),
            )

        quotes_by_ref = {
            _ref(row["market"], row["symbol"]): _quote_from_row(row)
            for row in rows
        }
        return [quotes_by_ref[ref] for ref in normalized_refs if ref in quotes_by_ref]

    async def upsert_quotes(self, items: list[StockQuoteItem]) -> None:
        if not items:
            return
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            for item in items:
                symbol = item.symbol.strip()
                if not symbol:
                    continue
                await cur.execute(
                    """
                    INSERT INTO market.stock_quote_snapshots AS existing (
                      market,
                      symbol,
                      latest_price,
                      change_pct,
                      turnover_rate,
                      amount,
                      float_market_cap,
                      total_market_cap,
                      source,
                      updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (market, symbol)
                    DO UPDATE SET
                      latest_price = EXCLUDED.latest_price,
                      change_pct = EXCLUDED.change_pct,
                      turnover_rate = COALESCE(EXCLUDED.turnover_rate, existing.turnover_rate),
                      amount = COALESCE(EXCLUDED.amount, existing.amount),
                      float_market_cap = COALESCE(EXCLUDED.float_market_cap, existing.float_market_cap),
                      total_market_cap = COALESCE(EXCLUDED.total_market_cap, existing.total_market_cap),
                      source = EXCLUDED.source,
                      updated_at = EXCLUDED.updated_at
                    """,
                    (
                        _market(item.market, symbol),
                        symbol,
                        item.latest_price,
                        item.change_pct,
                        item.turnover_rate,
                        item.amount,
                        item.float_market_cap,
                        item.total_market_cap,
                        item.source.strip(),
                        item.updated_at,
                    ),
                )

    async def get_daily_kline(self, symbol: str, limit: int, market: str = "") -> list[KlineBar]:
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn:
            rows = await _fetch_all(
                conn,
                """
                SELECT
                  trade_date::text AS date,
                  open,
                  high,
                  low,
                  close,
                  volume
                FROM market.stock_daily_klines
                WHERE market = %s AND symbol = %s
                ORDER BY trade_date DESC
                LIMIT %s
                """,
                (*_ref(market, symbol), limit),
            )
        return [_bar_from_row(row) for row in reversed(rows)]

    async def replace_daily_kline(self, symbol: str, bars: list[KlineBar], market: str = "", source: str = "") -> None:
        if not bars:
            return
        normalized_market, normalized_symbol = _ref(market, symbol)
        updated_at = datetime.now(UTC)
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM market.stock_daily_klines
                WHERE market = %s AND symbol = %s
                """,
                (normalized_market, normalized_symbol),
            )
            for bar in bars:
                await cur.execute(
                    """
                    INSERT INTO market.stock_daily_klines (
                      market,
                      symbol,
                      trade_date,
                      open,
                      high,
                      low,
                      close,
                      volume,
                      source,
                      updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        normalized_market,
                        normalized_symbol,
                        bar.date,
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        source.strip(),
                        updated_at,
                    ),
                )

    async def get_intraday(self, symbol: str, market: str = "") -> IntradaySeries | None:
        normalized_market, normalized_symbol = _ref(market, symbol)
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn:
            series_rows = await _fetch_all(
                conn,
                """
                SELECT
                  symbol,
                  trade_date::text AS date,
                  prev_close,
                  updated_at
                FROM market.stock_intraday_series
                WHERE market = %s AND symbol = %s
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (normalized_market, normalized_symbol),
            )
            if not series_rows:
                return None
            series_row = series_rows[0]
            point_rows = await _fetch_all(
                conn,
                """
                SELECT minute_time AS time, price, avg_price
                FROM market.stock_intraday_points
                WHERE market = %s AND symbol = %s AND trade_date = %s
                ORDER BY minute_time
                """,
                (normalized_market, normalized_symbol, series_row["date"]),
            )
        return IntradaySeries(
            symbol=series_row["symbol"],
            date=series_row["date"],
            prev_close=series_row["prev_close"],
            points=[_point_from_row(row) for row in point_rows],
            updated_at=series_row["updated_at"],
        )

    async def replace_intraday(self, series: IntradaySeries, market: str = "", source: str = "") -> None:
        normalized_market, normalized_symbol = _ref(market, series.symbol)
        if not normalized_symbol or not series.date:
            return
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM market.stock_intraday_series
                WHERE market = %s AND symbol = %s
                """,
                (normalized_market, normalized_symbol),
            )
            await cur.execute(
                """
                INSERT INTO market.stock_intraday_series (
                  market,
                  symbol,
                  trade_date,
                  prev_close,
                  source,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    normalized_market,
                    normalized_symbol,
                    series.date,
                    series.prev_close,
                    source.strip(),
                    series.updated_at,
                ),
            )
            for point in series.points:
                await cur.execute(
                    """
                    INSERT INTO market.stock_intraday_points (
                      market,
                      symbol,
                      trade_date,
                      minute_time,
                      price,
                      avg_price,
                      updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        normalized_market,
                        normalized_symbol,
                        series.date,
                        point.time,
                        point.price,
                        point.avg_price,
                        series.updated_at,
                    ),
                )

    async def record_snapshot_interests(self, refs: list[tuple[str, str, str]]) -> None:
        if not refs:
            return
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            for market, symbol, reason in refs:
                cleaned_symbol = symbol.strip()
                cleaned_reason = reason.strip() or SNAPSHOT_REASON_RECENT_CHART
                if not cleaned_symbol:
                    continue
                await cur.execute(
                    """
                    INSERT INTO market.stock_snapshot_interests AS interest (
                      market,
                      symbol,
                      reason,
                      last_requested_at,
                      updated_at
                    )
                    VALUES (%s, %s, %s, now(), now())
                    ON CONFLICT (market, symbol, reason)
                    DO UPDATE SET
                      last_requested_at = EXCLUDED.last_requested_at,
                      updated_at = EXCLUDED.updated_at
                    WHERE EXCLUDED.reason <> %s
                      OR interest.last_requested_at <= now() - (%s * interval '1 second')
                    """,
                    (
                        _market(market, cleaned_symbol),
                        cleaned_symbol,
                        cleaned_reason,
                        SNAPSHOT_REASON_RECENT_CHART,
                        RECENT_CHART_INTEREST_UPDATE_INTERVAL_SECONDS,
                    ),
                )

    async def list_symbols_for_snapshot_refresh(self, limit: int) -> list[tuple[str, str]]:
        await ensure_db_pool_open(self._pool)
        async with self._pool.connection() as conn:
            rows = await _fetch_all(
                conn,
                """
                WITH candidates AS (
                  SELECT
                    market,
                    symbol,
                    max(last_requested_at) AS last_requested_at,
                    min(
                      CASE reason
                        WHEN 'watchlist' THEN 0
                        WHEN 'recent_chart' THEN 1
                        WHEN 'hotlist' THEN 2
                        ELSE 3
                      END
                    ) AS reason_rank
                  FROM market.stock_snapshot_interests
                  WHERE last_requested_at >= now() - (%s * interval '1 day')
                  GROUP BY market, symbol
                )
                SELECT candidates.market, candidates.symbol
                FROM candidates
                WHERE candidates.symbol <> ''
                ORDER BY
                  CASE
                    WHEN NOT EXISTS (
                      SELECT 1
                      FROM market.stock_quote_snapshots AS quote
                      WHERE quote.market = candidates.market
                        AND quote.symbol = candidates.symbol
                    )
                    OR NOT EXISTS (
                      SELECT 1
                      FROM market.stock_daily_klines AS daily
                      WHERE daily.market = candidates.market
                        AND daily.symbol = candidates.symbol
                    )
                    OR NOT EXISTS (
                      SELECT 1
                      FROM market.stock_intraday_series AS intraday
                      WHERE intraday.market = candidates.market
                        AND intraday.symbol = candidates.symbol
                    )
                    THEN 0
                    ELSE 1
                  END,
                  candidates.reason_rank,
                  candidates.last_requested_at DESC
                LIMIT %s
                """,
                (_RECENT_INTEREST_DAYS, limit),
            )
        return [(_market(row["market"]), row["symbol"]) for row in rows]


async def _fetch_all(conn: Any, sql: str, params: tuple[object, ...]) -> list[DictRow]:
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        return list(await cur.fetchall())


def _ref(market: str, symbol: str) -> tuple[str, str]:
    cleaned_symbol = symbol.strip()
    return (_market(market, cleaned_symbol), cleaned_symbol)


def _market(market: str, symbol: str = "") -> str:
    return normalize_market(market, symbol)


def _reason_rank(reason: str) -> int:
    return _REASON_RANK.get(reason.strip(), 3)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _hot_item_from_row(row: DictRow) -> HotItem:
    return HotItem(
        rank=row["rank"],
        symbol=row["symbol"],
        name=row["name"],
        boards=row["boards"],
        change_pct=row["change_pct"],
        reason=row["reason"],
        concept=row["concept"],
        hot_score=row["hot_score"],
        latest_price=row["latest_price"],
        eastmoney_rank=row["eastmoney_rank"],
        tonghuashun_rank=row["tonghuashun_rank"],
        kai_pan_la_rank=row["kai_pan_la_rank"],
        tao_gu_ba_rank=row["tao_gu_ba_rank"],
        sources=list(row["sources"] or []),
        updated_at=row["updated_at"],
    )


def _quote_from_row(row: DictRow) -> StockQuoteItem:
    return StockQuoteItem(
        symbol=row["symbol"],
        market=row["market"],
        latest_price=row["latest_price"],
        change_pct=row["change_pct"],
        turnover_rate=row["turnover_rate"],
        amount=row["amount"],
        float_market_cap=row["float_market_cap"],
        total_market_cap=row["total_market_cap"],
        source=row["source"],
        updated_at=row["updated_at"],
    )


def _bar_from_row(row: DictRow) -> KlineBar:
    return KlineBar(
        date=row["date"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
    )


def _point_from_row(row: DictRow) -> IntradayPoint:
    return IntradayPoint(time=row["time"], price=row["price"], avg_price=row["avg_price"])
