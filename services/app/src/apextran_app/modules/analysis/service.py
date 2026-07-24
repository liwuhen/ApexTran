"""Analysis application service — thin orchestration over the AgentClient."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ...shared.clients.agent_client import AgentClient


class AnalysisService:
    def __init__(self, agent: AgentClient) -> None:
        self._agent = agent

    def analyze_stream(self, *, prompt: str, context: dict[str, Any] | None, user_id: str) -> AsyncIterator[str]:
        # Enrichment (e.g. pull hotlist via market's public service) would happen
        # here before delegating. Kept pass-through for now.
        return self._agent.analyze_stream(context=context, prompt=prompt, user_id=user_id)
