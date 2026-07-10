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

    async def fetch_hotlist(self):  # type: ignore[override]
        if self.fail:
            raise ConnectionError("upstream down")
        return await super().fetch_hotlist()


def _service(source: _FlakySource) -> MarketService:
    return MarketService(
        source=source,
        cache=InMemoryTTLCache(),
        hotlist_ttl=0.01,  # expire fast so the second read re-fetches
        headlines_ttl=30,
        news_ttl=30,
        flash_ttl=30,
    )


@pytest.mark.asyncio
async def test_serves_stale_on_source_failure() -> None:
    source = _FlakySource()
    service = _service(source)

    first = await service.get_hotlist()  # success → mirrors to :last
    await asyncio.sleep(0.02)  # primary entry expires
    source.fail = True

    second = await service.get_hotlist()  # source down → stale snapshot, not an error
    assert [h.symbol for h in second] == [h.symbol for h in first]


@pytest.mark.asyncio
async def test_reraises_when_no_stale_available() -> None:
    source = _FlakySource()
    source.fail = True
    service = _service(source)

    with pytest.raises(ConnectionError):
        await service.get_hotlist()  # cold cache + source down → surface the error
