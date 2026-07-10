"""Worker leader election — exactly one collector hits upstream.

Scale the ``app-worker`` for availability, not for throughput: N workers run,
but only the *leader* actually collects, so upstream sees one caller regardless
of replica count. If the leader dies its lock expires and a standby takes over
within one TTL.

- ``AlwaysLeader`` — no Redis (memory mode / single worker): always leader.
- ``RedisLeaderLock`` — ``SET key token NX PX ttl`` to win; renew by extending
  the TTL only while we still hold it (compare-and-extend via a Lua script so we
  never stomp a lock a peer took after we lapsed).

The worker holds a ``LeadershipManager`` that keeps ``is_leader`` current in the
background; the scheduler gates every job on it.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from ..config import get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

_LEADER_KEY = "apextran-app:worker:leader"

# Compare-and-extend: only renew if the stored token is still ours.
_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
else
  return 0
end
"""


class LeaderLock(Protocol):
    async def acquire(self) -> bool:
        """Try to become leader. True if we now hold the lock."""
        ...

    async def renew(self) -> bool:
        """Extend our leadership. False if we lost it."""
        ...

    async def release(self) -> None:
        """Give up leadership (best-effort)."""
        ...


class AlwaysLeader:
    """Single-worker / no-Redis mode: this process is always the collector."""

    async def acquire(self) -> bool:
        return True

    async def renew(self) -> bool:
        return True

    async def release(self) -> None:
        return None


class RedisLeaderLock:
    def __init__(self, redis_url: str, ttl: float) -> None:
        self._url = redis_url
        self._ttl_ms = max(1000, int(ttl * 1000))
        self._token = uuid.uuid4().hex
        self._redis: Redis | None = None

    async def _client(self) -> Redis:
        if self._redis is None:
            from redis.asyncio import from_url

            self._redis = from_url(self._url)
        return self._redis

    async def acquire(self) -> bool:
        redis = await self._client()
        won = await redis.set(_LEADER_KEY, self._token, nx=True, px=self._ttl_ms)
        return bool(won)

    async def renew(self) -> bool:
        redis = await self._client()
        held = await redis.eval(_RENEW_LUA, 1, _LEADER_KEY, self._token, self._ttl_ms)
        return bool(held)

    async def release(self) -> None:
        redis = await self._client()
        # Only delete if it's still ours (same compare-and-act shape as renew).
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            _LEADER_KEY,
            self._token,
        )


class LeadershipManager:
    """Keeps ``is_leader`` current: acquire → renew loop with automatic failover."""

    def __init__(self, lock: LeaderLock, *, ttl: float) -> None:
        self._lock = lock
        self._ttl = ttl
        # Renew at a third of the TTL so a couple of misses still don't lapse it.
        # Floor well under any realistic TTL so renewal always beats expiry.
        self._renew_interval = max(0.1, ttl / 3)
        self.is_leader = False

    async def run(self) -> None:
        try:
            while True:
                if self.is_leader:
                    self.is_leader = await self._lock.renew()
                    if not self.is_leader:
                        logger.warning("worker: lost leadership, standing by")
                else:
                    self.is_leader = await self._lock.acquire()
                    if self.is_leader:
                        logger.info("worker: acquired leadership, now collecting")
                await asyncio.sleep(self._renew_interval)
        except asyncio.CancelledError:
            if self.is_leader:
                await self._lock.release()
            raise


def build_leader() -> LeaderLock:
    settings = get_settings()
    if settings.cache_backend == "redis":
        logger.info("worker: Redis leader election enabled")
        return RedisLeaderLock(settings.redis_url, settings.leader_ttl)
    return AlwaysLeader()
