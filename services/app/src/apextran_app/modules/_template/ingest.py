"""Optional worker jobs. Delete this file (and register_jobs in wiring) if the
module has no background work."""

from __future__ import annotations

from ...shared.scheduler import Scheduler
from .provider import get_service


def register_jobs(scheduler: Scheduler) -> None:
    service = get_service()
    scheduler.add_job("_template.refresh", service.refresh, interval=30.0)
