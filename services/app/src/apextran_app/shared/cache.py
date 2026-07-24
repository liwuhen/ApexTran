"""Cache port + adapters.

The ``Cache`` protocol is async so a Redis adapter drops in without touching any
module. ``InMemoryTTLCache`` is process-local (M1 / single instance);
``RedisCache`` is shared across API replicas + worker (M2), which is what makes
the fan-out work: the worker refreshes once, every replica reads the same value.
"""

from __future__ import annotations

import pickle
import time
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from redis.asyncio import Redis


@runtime_checkable
class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, *, ttl: float) -> None: ...


class InMemoryTTLCache:
    """Simple monotonic-clock TTL cache. Single-process only (M1)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, *, ttl: float) -> None:
        self._store[key] = (time.monotonic() + ttl, value)


class RedisCache:
    """Shared TTL cache backed by Redis (M2).

    Values are pickled — the cache is generic over ``Any`` and only ever holds
    our own objects on an internal, trusted Redis, so pickle is safe here.
    ``redis`` is an optional extra (``uv sync --extra redis``); import is lazy so
    the base install stays light.
    """

    def __init__(self, url: str) -> None:
        from redis.asyncio import from_url

        self._redis: Redis = from_url(url)

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return pickle.loads(cast("bytes", raw))  # noqa: S301 — internal trusted cache, our own objects

    async def set(self, key: str, value: Any, *, ttl: float) -> None:
        await self._redis.set(key, pickle.dumps(value), px=max(1, int(ttl * 1000)))
