"""Error model — project-owned (no longer a republic facade).

``AgentError`` is the runtime error type; ``RepublicError`` is kept as an alias so
existing call sites keep working during the migration.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorKind(StrEnum):
    """Coarse error categories (values match the wire/event ``kind`` strings)."""

    INVALID_INPUT = "invalid_input"
    CONFIG = "config"
    PROVIDER = "provider"
    TOOL = "tool"
    TEMPORARY = "temporary"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class AgentError(Exception):
    """A runtime error carrying a coarse :class:`ErrorKind` and a message."""

    def __init__(self, kind: ErrorKind, message: str, details: dict[str, Any] | None = None) -> None:
        self.kind = kind
        self.message = message
        self.details = details
        super().__init__(message)

    def __str__(self) -> str:
        kind = getattr(self.kind, "value", self.kind)
        return f"[{kind}] {self.message}"

    def as_dict(self) -> dict[str, Any]:
        kind = getattr(self.kind, "value", self.kind)
        payload: dict[str, Any] = {"kind": kind, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


# Backward-compatible alias; call sites migrate to ``AgentError`` over time.
RepublicError = AgentError

__all__ = ["AgentError", "ErrorKind", "RepublicError"]
