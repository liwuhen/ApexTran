"""Single-flight collapses concurrent misses into one upstream call."""

from __future__ import annotations

import asyncio

import pytest
from apextran_app.modules.market.adapters import MockMarketSource
from apextran_app.modules.market.service import MarketService
from apextran_app.shared.cache import InMemoryTTLCache
from apextran_app.shared.singleflight import SingleFlight


@pytest.mark.asyncio
async def test_singleflight_coalesces_concurrent_calls() -> None:
    calls = 0

    async def produce() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return 42

    sf = SingleFlight()
    results = await asyncio.gather(*(sf.run("k", produce) for _ in range(20)))

    assert results == [42] * 20
    assert calls == 1  # 20 concurrent callers → exactly one production


class _CountingSource(MockMarketSource):
    def __init__(self) -> None:
        self.hotlist_calls = 0

    async def fetch_hotlist(self):  # type: ignore[override]
        self.hotlist_calls += 1
        await asyncio.sleep(0.02)
        return await super().fetch_hotlist()


@pytest.mark.asyncio
async def test_service_miss_hits_source_once() -> None:
    source = _CountingSource()
    service = MarketService(
        source=source,
        cache=InMemoryTTLCache(),
        hotlist_ttl=30,
        headlines_ttl=30,
        news_ttl=30,
        flash_ttl=30,
    )

    await asyncio.gather(*(service.get_hotlist() for _ in range(15)))
    assert source.hotlist_calls == 1  # cache miss stampede collapsed to one fetch
