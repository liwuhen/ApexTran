"""Single-flight — collapse concurrent work on the same key into one call.

At high concurrency, a cache miss must not let N requests all stampede the
upstream (thundering herd). The first caller for a key runs the producer; the
rest await its result. See docs/business-service-架构方案.md §8.1.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class SingleFlight:
    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future] = {}

    async def run(self, key: str, producer: Callable[[], Awaitable[T]]) -> T:
        existing = self._inflight.get(key)
        if existing is not None:
            return await existing  # type: ignore[no-any-return]

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._inflight[key] = future
        try:
            result = await producer()
        except Exception as exc:
            future.set_exception(exc)
            future.add_done_callback(lambda done: done.exception())
            raise
        else:
            future.set_result(result)
            return result
        finally:
            self._inflight.pop(key, None)
