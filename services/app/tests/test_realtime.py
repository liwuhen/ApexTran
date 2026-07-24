"""M3 realtime tests — refresh publishes fresh snapshots; failures are swallowed."""

from __future__ import annotations

from typing import Any

import pytest
from apextran_app.modules.market.adapters import MockMarketSource
from apextran_app.modules.market.service import MarketService
from apextran_app.shared.cache import InMemoryTTLCache


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        self.calls.append((channel, data))


class _BrokenPublisher:
    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        raise RuntimeError("centrifugo down")


def _service(publisher: Any) -> MarketService:
    return MarketService(
        source=MockMarketSource(),
        cache=InMemoryTTLCache(),
        hotlist_ttl=30.0,
        headlines_ttl=30.0,
        news_ttl=120.0,
        flash_ttl=10.0,
        publisher=publisher,
    )


@pytest.mark.asyncio
async def test_refresh_publishes_snapshots() -> None:
    pub = _RecordingPublisher()
    svc = _service(pub)
    await svc.refresh_all()

    channels = {c for c, _ in pub.calls}
    assert channels == {"market:hotlist", "market:ai-hotspots", "market:flash"}
    for _, payload in pub.calls:
        assert isinstance(payload["items"], list)
        assert payload["items"]  # non-empty snapshot


@pytest.mark.asyncio
async def test_publish_failure_does_not_break_refresh() -> None:
    # A publisher that raises must be swallowed — the cache refresh still returns.
    svc = _service(_BrokenPublisher())
    data = await svc.refresh_hotlist()
    assert data  # refresh succeeded despite the broken publisher
