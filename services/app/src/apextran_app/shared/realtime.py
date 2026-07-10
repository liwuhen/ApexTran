"""RealtimePublisher — the worker's push side (fresh snapshot → browsers).

The worker refreshes the shared cache on a schedule; after a successful refresh
it *publishes* the new snapshot to a Centrifugo channel so connected clients get
it pushed instead of polling. Two implementations:

- ``NoopPublisher`` — default when no Centrifugo is configured; the worker still
  fills the cache, clients just fall back to CDN polling.
- ``CentrifugoPublisher`` — POSTs to Centrifugo's server HTTP API.

The publish path is best-effort: a Centrifugo outage must never break the cache
refresh, so failures are logged and swallowed.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from loguru import logger

from ..config import get_settings


class RealtimePublisher(Protocol):
    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        """Push ``data`` to everyone subscribed to ``channel``."""
        ...


class NoopPublisher:
    """No realtime backend configured — clients poll the CDN instead."""

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        return None


class CentrifugoPublisher:
    """Publishes via Centrifugo's server API (``POST {api_url}/publish``)."""

    def __init__(self, api_url: str, api_key: str, timeout: float = 3.0) -> None:
        self._url = api_url.rstrip("/") + "/publish"
        self._key = api_key
        self._timeout = timeout

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        headers = {"X-API-Key": self._key} if self._key else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._url,
                    json={"channel": channel, "data": data},
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            # Best-effort: the cache is already fresh; a failed push just means
            # clients pick it up on their next poll.
            logger.warning("centrifugo publish to {} failed: {}", channel, exc)


def build_publisher() -> RealtimePublisher:
    settings = get_settings()
    if settings.centrifugo_api_url:
        logger.info("realtime: CentrifugoPublisher -> {}", settings.centrifugo_api_url)
        return CentrifugoPublisher(settings.centrifugo_api_url, settings.centrifugo_api_key)
    return NoopPublisher()
