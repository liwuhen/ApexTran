"""FastAPI assembly (serve role).

Does no business logic — it just discovers modules and mounts their routers.
Adding a module needs no change here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from loguru import logger

from . import __version__
from .config import get_settings
from .shared.db import close_db_pool, open_db_pool
from .shared.discovery import discover_modules
from .shared.metrics import metrics_endpoint, metrics_middleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await open_db_pool()
    try:
        yield
    finally:
        await close_db_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ApexTran business service",
        version=__version__,
        summary="Market data & business modules. See docs/business-service-架构方案.md.",
        lifespan=lifespan,
    )

    app.middleware("http")(metrics_middleware)

    for spec in discover_modules():
        if spec.router is not None:
            app.include_router(spec.router)
            logger.info("mounted module router: {}", spec.name)

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus scrape target — request counts + latency histogram."""
        return metrics_endpoint()

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        """Liveness — process is up."""
        return {"status": "ok", "service": settings.app_name}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, str]:
        """Readiness — M2 will also check Redis/DB/upstream reachability."""
        return {"status": "ready"}

    return app
