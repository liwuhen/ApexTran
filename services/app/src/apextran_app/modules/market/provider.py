"""Composition for the market module — builds the singleton service.

Kept separate from ``wiring`` to avoid an import cycle (router/ingest import the
service from here; wiring imports router/ingest). Cache and source are chosen by
config: default is the zero-dep ``memory`` + ``mock`` stack (M1); set
``APP_CACHE_BACKEND=redis`` / ``APP_MARKET_SOURCE=akshare`` for M2 — only this
file decides, nothing else changes.
"""

from __future__ import annotations

from functools import lru_cache

from loguru import logger

from ...config import Settings, get_settings
from ...shared.cache import Cache, InMemoryTTLCache, RedisCache
from ...shared.db import get_db_pool
from ...shared.realtime import build_publisher
from .ports import MarketSource
from .repository import InMemoryWatchlistRepository, PostgresWatchlistRepository, WatchlistRepository
from .service import MarketService
from .stock_repository import (
    NoopStockInstrumentRepository,
    PostgresStockInstrumentRepository,
    StockInstrumentRepository,
)


def _build_cache(settings: Settings) -> Cache:
    if settings.cache_backend == "redis":
        logger.info("market: using RedisCache at {}", settings.redis_url)
        return RedisCache(settings.redis_url)
    return InMemoryTTLCache()


def _build_source(settings: Settings) -> MarketSource:
    # "akshare"/"live" → live hotlist from official 同花顺 + 东方财富 + 腾讯 endpoints
    # (akshare's Eastmoney host is blocked here); news/flash still via akshare.
    if settings.market_source in ("akshare", "live"):
        from .adapters.live_source import LiveMarketSource

        logger.info("market: using LiveMarketSource (同花顺/东方财富/腾讯 直连热榜)")
        return LiveMarketSource()
    if settings.environment.lower() in {"prod", "production"}:
        raise RuntimeError("APP_MARKET_SOURCE=akshare or live is required in production")
    from .adapters import MockMarketSource

    return MockMarketSource()


def _build_watchlist_repository(settings: Settings) -> WatchlistRepository:
    if settings.db_url.strip():
        pool = get_db_pool()
        if pool is None:
            raise RuntimeError("APP_DB_URL is configured but DB pool is unavailable")
        logger.info("market: using PostgresWatchlistRepository")
        return PostgresWatchlistRepository(pool)
    if settings.environment.lower() in {"prod", "production"}:
        raise RuntimeError("APP_DB_URL is required for private market data in production")
    return InMemoryWatchlistRepository()


def _build_stock_repository(settings: Settings) -> StockInstrumentRepository:
    if settings.db_url.strip():
        pool = get_db_pool()
        if pool is None:
            raise RuntimeError("APP_DB_URL is configured but DB pool is unavailable")
        logger.info("market: using PostgresStockInstrumentRepository")
        return PostgresStockInstrumentRepository(pool)
    return NoopStockInstrumentRepository()


@lru_cache
def get_service() -> MarketService:
    settings = get_settings()
    return MarketService(
        source=_build_source(settings),
        cache=_build_cache(settings),
        hotlist_ttl=settings.hotlist_ttl,
        headlines_ttl=settings.headlines_ttl,
        news_ttl=settings.news_ttl,
        flash_ttl=settings.flash_ttl,
        publisher=build_publisher(),
        watchlist_repository=_build_watchlist_repository(settings),
        stock_repository=_build_stock_repository(settings),
    )
