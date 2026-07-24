"""AgentClient — the port through which business modules reach agent-service.

The ``analysis`` module depends only on the ``AgentClient`` protocol. Two
implementations:

- ``LocalAgentClient`` — a canned stub so the service runs without agent-service
  (default; used in tests).
- ``HttpAgentClient`` — POSTs to ``{base_url}/analyze`` with the shared
  proxy-secret + user identity and yields the model's streamed deltas.

Streaming (not a job id) keeps it simple and reuses agent-service's existing SSE
infra: the caller proxies these chunks straight to the browser. A detached
job-store (submit → poll) is a later upgrade if we need to survive disconnects.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from loguru import logger


class AgentClient(Protocol):
    def analyze_stream(self, *, context: dict[str, Any] | None, prompt: str, user_id: str) -> AsyncIterator[str]:
        """Stream an analysis as text deltas."""
        ...


class LocalAgentClient:
    """M1/M2 stub — no network; emits a canned analysis in chunks."""

    async def analyze_stream(self, *, context: dict[str, Any] | None, prompt: str, user_id: str) -> AsyncIterator[str]:
        for chunk in (
            "[本地模拟分析] ",
            f"已收到请求:「{prompt[:60]}」。 ",
            "接入 agent-service 后此处为真实 LLM 流式结果。",
        ):
            yield chunk


class HttpAgentClient:
    """Calls agent-service ``POST /analyze`` and yields streamed deltas."""

    def __init__(self, base_url: str, proxy_secret: str = "", timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = proxy_secret
        self._timeout = timeout

    async def analyze_stream(self, *, context: dict[str, Any] | None, prompt: str, user_id: str) -> AsyncIterator[str]:
        headers = {"X-ApexTran-User": user_id or "default"}
        if self._secret:
            headers["X-ApexTran-Proxy-Secret"] = self._secret
        payload = {"prompt": prompt, "context": context}

        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("POST", f"{self._base_url}/analyze", json=payload, headers=headers) as resp,
            ):
                resp.raise_for_status()
                event: str | None = None
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event == "delta":
                        delta = json.loads(line[5:].strip()).get("delta", "")
                        if delta:
                            yield delta
                    elif event == "end":
                        break
        except httpx.HTTPError as exc:
            # Circuit-breaker-lite: agent down must not 500 the whole request.
            logger.warning("agent-service analyze failed: {}", exc)
            yield "\n[分析服务暂不可用,请稍后重试]"
