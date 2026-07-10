"""Composition for the analysis module — picks the AgentClient by config."""

from __future__ import annotations

from functools import lru_cache

from loguru import logger

from ...config import get_settings
from ...shared.clients.agent_client import AgentClient, HttpAgentClient, LocalAgentClient
from .service import AnalysisService


@lru_cache
def get_agent_client() -> AgentClient:
    settings = get_settings()
    if settings.agent_client == "http":
        logger.info("analysis: using HttpAgentClient -> {}", settings.agent_base_url)
        return HttpAgentClient(settings.agent_base_url, settings.proxy_secret)
    return LocalAgentClient()


@lru_cache
def get_service() -> AnalysisService:
    return AnalysisService(get_agent_client())
