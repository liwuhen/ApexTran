"""Streaming events — project-owned (no longer a republic facade).

A turn surfaces incremental progress as a sequence of :class:`StreamEvent`.
``AsyncStreamEvents`` is the async wrapper carrying terminal ``StreamState``
(error / usage) alongside the event iterator.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from backend.core.errors import AgentError


@dataclass
class StreamState:
    """Terminal metadata for a stream (set once the stream is exhausted)."""

    error: AgentError | None = None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class StreamEvent:
    """A single incremental event emitted during a turn."""

    kind: Literal[
        "text",
        "tool_call",
        "tool_result",
        "usage",
        "error",
        "final",
    ]
    data: dict[str, Any]


class AsyncStreamEvents:
    """Async iterator of :class:`StreamEvent` plus terminal :class:`StreamState`."""

    def __init__(self, iterator: AsyncIterator[StreamEvent], *, state: StreamState | None = None) -> None:
        self._iterator = iterator
        self._state = state or StreamState()

    def __aiter__(self) -> AsyncIterator[StreamEvent]:
        return self._iterator

    @property
    def error(self) -> AgentError | None:
        return self._state.error

    @property
    def usage(self) -> dict[str, Any] | None:
        return self._state.usage


__all__ = ["AsyncStreamEvents", "StreamEvent", "StreamState"]
