"""Token-bucket rate limiter (per key).

Process-local (M1/M2) — good enough per API replica. A Redis token bucket makes
it global across replicas (M4). Used to protect private/expensive endpoints
(analysis) and to stop the public proxy being abused as a free data scraper.
"""

from __future__ import annotations

import time


class TokenBucket:
    def __init__(self, rate_per_min: int, burst: int | None = None) -> None:
        self._rate = rate_per_min / 60.0  # tokens per second
        self._capacity = float(burst if burst is not None else rate_per_min)
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - last) * self._rate)
        if tokens < cost:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - cost, now)
        return True
