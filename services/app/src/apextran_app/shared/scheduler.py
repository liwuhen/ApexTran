"""Minimal async periodic scheduler for the worker role.

Fixed-interval asyncio loops with error isolation. An optional ``gate`` (the
leader flag) is checked before each run so only the leader collector actually
fires — standbys spin idle until they win the lock. M4+ can make the cadence
trading-calendar aware.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

Job = Callable[[], Awaitable[None]]
Gate = Callable[[], bool]


@dataclass
class _ScheduledJob:
    name: str
    func: Job
    interval: float


class Scheduler:
    def __init__(self, *, gate: Gate | None = None) -> None:
        self._jobs: list[_ScheduledJob] = []
        # Default gate: always run (single-worker / no leader election).
        self._gate: Gate = gate or (lambda: True)

    def add_job(self, name: str, func: Job, *, interval: float) -> None:
        self._jobs.append(_ScheduledJob(name=name, func=func, interval=interval))

    async def _run_job(self, job: _ScheduledJob) -> None:
        while True:
            if self._gate():
                try:
                    await job.func()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("scheduled job {} failed", job.name)
            await asyncio.sleep(job.interval)

    async def run(self) -> None:
        if not self._jobs:
            logger.warning("scheduler has no jobs; worker idling")
        logger.info("scheduler starting {} job(s)", len(self._jobs))
        await asyncio.gather(*(self._run_job(job) for job in self._jobs))
