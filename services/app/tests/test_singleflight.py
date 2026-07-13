"""Single-flight collapses concurrent misses into one upstream call."""

from __future__ import annotations

import asyncio

import pytest
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

