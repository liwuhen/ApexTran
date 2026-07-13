"""On-read chart fill: the first reader of a symbol with no chart snapshot
fills it from the source (single-flight, bounded, time-boxed) and persists it;
a slow upstream answers empty while the fill completes in the background."""

from __future__ import annotations

import asyncio

import pytest
from apextran_app.modules.market.adapters import MockMarketSource
from apextran_app.modules.market.domain.models import IntradaySeries, KlineBar
from apextran_app.modules.market.market_ref import MARKET_SH_A
from apextran_app.modules.market.service import MarketService
from apextran_app.modules.market.snapshot_repository import InMemoryMarketSnapshotRepository
from apextran_app.shared.cache import InMemoryTTLCache

_SYMBOL = "600519"


class _ChartCountingSource(MockMarketSource):
    """Count chart fetches; optionally stall them to exercise the timeout."""

    def __init__(self, delay: float = 0.0) -> None:
        self.kline_fetches = 0
        self.intraday_fetches = 0
        self._delay = delay

    async def fetch_daily_kline(self, symbol: str, limit: int = 180) -> list[KlineBar]:
        self.kline_fetches += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return await super().fetch_daily_kline(symbol, limit)

    async def fetch_intraday(self, symbol: str) -> IntradaySeries:
        self.intraday_fetches += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return await super().fetch_intraday(symbol)


def _service(
    source: _ChartCountingSource,
    snapshots: InMemoryMarketSnapshotRepository,
    *,
    chart_fill_on_read: bool = True,
    chart_fill_timeout: float = 3.0,
) -> MarketService:
    # request_source_fallback stays False: this mirrors production (DB-backed),
    # where the only on-request source access is the guarded chart fill.
    return MarketService(
        source=source,
        cache=InMemoryTTLCache(),
        hotlist_ttl=30,
        headlines_ttl=30,
        news_ttl=30,
        flash_ttl=30,
        snapshot_repository=snapshots,
        chart_fill_on_read=chart_fill_on_read,
        chart_fill_timeout=chart_fill_timeout,
    )


@pytest.mark.asyncio
async def test_first_kline_read_fills_from_source_and_persists() -> None:
    source = _ChartCountingSource()
    snapshots = InMemoryMarketSnapshotRepository()
    service = _service(source, snapshots)

    bars = await service.get_daily_kline(_SYMBOL, market=MARKET_SH_A)
    assert len(bars) > 0
    assert len(await snapshots.get_daily_kline(_SYMBOL, 180, MARKET_SH_A)) > 0

    # Second read is served by the snapshot — no second upstream call.
    await service.get_daily_kline(_SYMBOL, market=MARKET_SH_A)
    assert source.kline_fetches == 1


@pytest.mark.asyncio
async def test_first_intraday_read_fills_from_source_and_persists() -> None:
    source = _ChartCountingSource()
    snapshots = InMemoryMarketSnapshotRepository()
    service = _service(source, snapshots)

    series = await service.get_intraday(_SYMBOL, market=MARKET_SH_A)
    assert len(series.points) > 0
    assert await snapshots.get_intraday(_SYMBOL, MARKET_SH_A) is not None

    await service.get_intraday(_SYMBOL, market=MARKET_SH_A)
    assert source.intraday_fetches == 1


@pytest.mark.asyncio
async def test_concurrent_readers_collapse_to_one_fetch() -> None:
    source = _ChartCountingSource(delay=0.05)
    service = _service(source, InMemoryMarketSnapshotRepository())

    results = await asyncio.gather(*(service.get_daily_kline(_SYMBOL, market=MARKET_SH_A) for _ in range(5)))

    assert all(len(bars) > 0 for bars in results)
    assert source.kline_fetches == 1


@pytest.mark.asyncio
async def test_slow_source_returns_empty_then_backfills_in_background() -> None:
    source = _ChartCountingSource(delay=0.2)
    snapshots = InMemoryMarketSnapshotRepository()
    service = _service(source, snapshots, chart_fill_timeout=0.05)

    bars = await service.get_daily_kline(_SYMBOL, market=MARKET_SH_A)
    assert bars == []  # timed out — request answered immediately with empty

    await asyncio.sleep(0.3)  # the detached fill finishes and persists
    assert len(await snapshots.get_daily_kline(_SYMBOL, 180, MARKET_SH_A)) > 0

    # The next poll is served from the snapshot without another fetch.
    assert len(await service.get_daily_kline(_SYMBOL, market=MARKET_SH_A)) > 0
    assert source.kline_fetches == 1


@pytest.mark.asyncio
async def test_fill_failure_degrades_to_empty() -> None:
    class _BrokenChartSource(_ChartCountingSource):
        async def fetch_daily_kline(self, symbol: str, limit: int = 180) -> list[KlineBar]:
            raise ConnectionError("upstream down")

    service = _service(_BrokenChartSource(), InMemoryMarketSnapshotRepository())

    bars = await service.get_daily_kline(_SYMBOL, market=MARKET_SH_A)
    assert bars == []  # graceful: empty now, worker cycle fills later


@pytest.mark.asyncio
async def test_flag_off_returns_empty_without_touching_the_source() -> None:
    source = _ChartCountingSource()
    service = _service(source, InMemoryMarketSnapshotRepository(), chart_fill_on_read=False)

    assert await service.get_daily_kline(_SYMBOL, market=MARKET_SH_A) == []
    series = await service.get_intraday(_SYMBOL, market=MARKET_SH_A)
    assert series.points == []
    assert source.kline_fetches == 0
    assert source.intraday_fetches == 0
