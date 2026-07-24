"""Shared PostgreSQL connection pool for apextran-app modules."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import get_settings


@lru_cache
def get_db_pool() -> Any | None:
    db_url = get_settings().db_url.strip()
    if not db_url:
        return None
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
    except ModuleNotFoundError as exc:
        raise RuntimeError("PostgreSQL support requires psycopg[binary,pool]") from exc
    return AsyncConnectionPool(
        db_url,
        kwargs={"autocommit": False, "row_factory": dict_row},
        open=False,
    )


async def ensure_db_pool_open(pool: Any | None = None) -> Any | None:
    selected_pool = pool if pool is not None else get_db_pool()
    if selected_pool is not None and getattr(selected_pool, "closed", False):
        await selected_pool.open()
    return selected_pool


async def open_db_pool() -> None:
    pool = get_db_pool()
    await ensure_db_pool_open(pool)


async def close_db_pool() -> None:
    pool = get_db_pool()
    if pool is not None:
        await pool.close()
