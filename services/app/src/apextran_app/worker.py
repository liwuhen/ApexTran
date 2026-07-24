"""Worker role — runs each module's scheduled jobs (proactive cache refresh).

Same image as ``serve``, different entrypoint. Scale it for availability: a
Redis leader lock means only the leader collects, so upstream sees one caller no
matter how many replicas run. A dead leader is replaced within one lock TTL.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from .config import get_settings
from .shared.discovery import discover_modules
from .shared.leader import LeadershipManager, build_leader
from .shared.scheduler import Scheduler


async def run_worker() -> None:
    settings = get_settings()
    leadership = LeadershipManager(build_leader(), ttl=settings.leader_ttl)

    scheduler = Scheduler(gate=lambda: leadership.is_leader)
    for spec in discover_modules():
        if spec.register_jobs is not None:
            spec.register_jobs(scheduler)
            logger.info("registered jobs for module: {}", spec.name)

    # Leadership loop and scheduler run together; the gate keeps standbys idle.
    await asyncio.gather(leadership.run(), scheduler.run())
