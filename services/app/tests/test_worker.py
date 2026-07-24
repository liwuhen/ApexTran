"""M4 tests — leader election, scheduler gating, and the module gray switch."""

from __future__ import annotations

import asyncio

import pytest
from apextran_app.shared.leader import AlwaysLeader, LeadershipManager
from apextran_app.shared.scheduler import Scheduler


@pytest.mark.asyncio
async def test_always_leader_is_always_leader() -> None:
    lock = AlwaysLeader()
    assert await lock.acquire()
    assert await lock.renew()
    await lock.release()  # no-op, must not raise


class _FlakyLock:
    """Grants leadership once, then loses it on the next renew."""

    def __init__(self) -> None:
        self._held = False
        self.renews = 0

    async def acquire(self) -> bool:
        self._held = True
        return True

    async def renew(self) -> bool:
        self.renews += 1
        self._held = False  # simulate losing the lock
        return False

    async def release(self) -> None:
        self._held = False


@pytest.mark.asyncio
async def test_leadership_manager_tracks_and_recovers() -> None:
    lock = _FlakyLock()
    mgr = LeadershipManager(lock, ttl=0.3)  # renew interval ~0.1s
    task = asyncio.create_task(mgr.run())
    await asyncio.sleep(0.05)
    assert mgr.is_leader  # acquired on first tick
    await asyncio.sleep(0.15)
    assert not mgr.is_leader  # lost on renew, standing by
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_scheduler_gate_blocks_non_leader() -> None:
    hits = 0

    async def job() -> None:
        nonlocal hits
        hits += 1

    is_leader = False
    sched = Scheduler(gate=lambda: is_leader)
    sched.add_job("j", job, interval=0.01)
    task = asyncio.create_task(sched.run())
    await asyncio.sleep(0.05)
    assert hits == 0  # gate closed → never fired

    is_leader = True
    await asyncio.sleep(0.05)
    assert hits > 0  # gate opened → fires

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_gray_switch_disables_module(monkeypatch: pytest.MonkeyPatch) -> None:
    from apextran_app.config import get_settings
    from apextran_app.shared import discovery

    monkeypatch.setenv("APP_DISABLED_MODULES", "analysis")
    get_settings.cache_clear()
    try:
        names = {spec.name for spec in discovery.discover_modules()}
        assert "analysis" not in names
        assert "market" in names  # others still load
    finally:
        get_settings.cache_clear()  # restore for other tests
