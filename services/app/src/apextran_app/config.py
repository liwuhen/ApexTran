"""Service configuration — read from ``APP_*`` env vars (isolated from ``ApexTran_*``).

Kept deliberately small for M1. M2+ adds redis/db URLs; M3 adds Centrifugo and
OTel exporters.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    app_name: str = "apextran-app"
    environment: str = "dev"

    # HTTP server (serve role).
    host: str = "127.0.0.1"
    port: int = 8100

    # Pluggable backends (default to the zero-dep M1 stack; flip via env for M2).
    cache_backend: str = "memory"  # "memory" | "redis"
    redis_url: str = "redis://127.0.0.1:6379/0"
    db_url: str = ""
    migration_db_url: str = ""
    market_source: str = "mock"  # "mock" | "akshare"

    # agent-service contract (used by the `analysis` module).
    agent_client: str = "local"  # "local" | "http"
    agent_base_url: str = "http://127.0.0.1:8000"
    proxy_secret: str = ""

    # Per-user rate limit (token bucket) on private/expensive endpoints.
    rate_limit_per_min: int = 60

    # BFF -> apextran-app internal JWT. Production should set a real secret, or
    # replace this HS256 bridge with asymmetric verification.
    internal_jwt_issuer: str = "apextran-bff"
    internal_jwt_audience: str = "apextran-app"
    internal_jwt_secret: str = ""

    # Centrifugo realtime push (worker publishes fresh snapshots after refresh).
    # Empty api_url disables it — the worker degrades to cache-only, browsers poll.
    centrifugo_api_url: str = ""  # e.g. http://centrifugo:8000/api
    centrifugo_api_key: str = ""

    # Cache TTLs (seconds). M1 uses the in-memory cache; M2 swaps in Redis.
    hotlist_ttl: float = 30.0
    headlines_ttl: float = 30.0
    news_ttl: float = 120.0
    flash_ttl: float = 10.0

    # Worker refresh cadence (seconds). M2 makes this trading-calendar aware.
    refresh_interval: float = 15.0
    stock_pool_refresh_interval: float = 86400.0

    # Worker leader-lock TTL (seconds). A dead leader is replaced within one TTL.
    leader_ttl: float = 15.0

    # Gray switch — comma-separated module names to disable at boot (serve+worker).
    # e.g. APP_DISABLED_MODULES=analysis rolls the whole module out of the service
    # without a code change. Empty = every discovered module is on.
    disabled_modules: str = ""

    @property
    def disabled_module_set(self) -> set[str]:
        return {m.strip() for m in self.disabled_modules.split(",") if m.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
