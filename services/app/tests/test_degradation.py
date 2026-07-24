"""Stale-while-revalidate: a source outage serves the last good snapshot."""

from __future__ import annotations

import asyncio

import pytest
from apextran_app.modules.market.adapters import MockMarketSource
from apextran_app.modules.market.service import MarketService
from apextran_app.shared.cache import InMemoryTTLCache


class _FlakySource(MockMarketSource):
    def __init__(self) -> None:
        self.fail = False

    async def fetch_headlines(self, symbol: str | None = None):  # type: ignore[override]
        if self.fail:
            raise ConnectionError("upstream down")
        return await super().fetch_headlines(symbol)


def _service(source: _FlakySource) -> MarketService:
    return MarketService(
        source=source,
        cache=InMemoryTTLCache(),
        hotlist_ttl=30,
        headlines_ttl=0.01,  # expire fast so the second read re-fetches
        news_ttl=30,
        flash_ttl=30,
    )


@pytest.mark.asyncio
async def test_serves_stale_on_source_failure() -> None:
    source = _FlakySource()
    service = _service(source)

    first = await service.get_headlines("600519")  # success → mirrors to :last
    await asyncio.sleep(0.02)  # primary entry expires
    source.fail = True

    second = await service.get_headlines("600519")  # source down → stale snapshot, not an error
    assert [item.id for item in second] == [item.id for item in first]


@pytest.mark.asyncio
async def test_reraises_when_no_stale_available() -> None:
    source = _FlakySource()
    source.fail = True
    service = _service(source)

    with pytest.raises(ConnectionError):
        await service.get_headlines("600519")  # cold cache + source down → surface the error
