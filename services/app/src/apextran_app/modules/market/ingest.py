"""Worker jobs for the market module — proactive cache refresh.

M1: a single fixed-interval ``refresh_all``. M2 splits cadence per data type
(flash faster than news) and adds the Redis leader lock so only one collector
hits upstream.
"""

from __future__ import annotations

from ...config import get_settings
from ...shared.scheduler import Scheduler
from .provider import get_service


def register_jobs(scheduler: Scheduler) -> None:
    service = get_service()
    settings = get_settings()
    scheduler.add_job("market.refresh_all", service.refresh_all, interval=settings.refresh_interval)
    if settings.stock_pool_refresh_interval > 0:
        scheduler.add_job(
            "market.sync_stock_pool",
            _sync_stock_pool,
            interval=settings.stock_pool_refresh_interval,
        )
    if settings.snapshot_refresh_interval > 0:
        scheduler.add_job(
            "market.refresh_snapshots",
            _refresh_snapshots,
            interval=settings.snapshot_refresh_interval,
        )


async def _sync_stock_pool() -> None:
    await get_service().sync_stock_pool()


async def _refresh_snapshots() -> None:
    await get_service().refresh_market_snapshots()
