"""CLI — two process roles of the one service: ``serve`` and ``worker``."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn

from .config import get_settings

app = typer.Typer(help="ApexTran business microservice.", no_args_is_help=True)


@app.command()
def serve(
    host: str | None = None,
    port: int | None = None,
    reload: bool = False,
) -> None:
    """Run the HTTP API (serve role)."""
    settings = get_settings()
    uvicorn.run(
        "apextran_app.main:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@app.command()
def worker() -> None:
    """Run scheduled collectors / background jobs (worker role)."""
    from .worker import run_worker

    asyncio.run(run_worker())


@app.command()
def sync_stock_pool() -> None:
    """Refresh market.stock_instruments from the configured market source."""

    from .modules.market.provider import get_service
    from .shared.db import close_db_pool

    async def _run() -> None:
        try:
            count = await get_service().sync_stock_pool()
            typer.echo(f"synced {count} stock instrument(s)")
        finally:
            await close_db_pool()

    settings = get_settings()
    if not settings.db_url.strip():
        raise typer.BadParameter("APP_DB_URL is required to sync the stock pool")
    asyncio.run(_run())


@app.command()
def migrate() -> None:
    """Apply SQL migrations for apextran-app."""
    import psycopg

    settings = get_settings()
    db_url = settings.migration_db_url.strip() or settings.db_url.strip()
    if not db_url:
        raise typer.BadParameter("APP_MIGRATION_DB_URL or APP_DB_URL is required")
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        typer.echo("no migrations found")
        return
    with psycopg.connect(db_url) as conn, conn.transaction():
        for path in files:
            typer.echo(f"applying {path.name}")
            conn.execute(path.read_text(encoding="utf-8"))
    typer.echo("migrations applied")


if __name__ == "__main__":
    app()
