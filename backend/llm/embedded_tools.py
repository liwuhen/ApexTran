"""Embedded tool-call extraction — project-owned.

Some providers emit tool calls as ``<tool_call>{...}</tool_call>`` blocks inside
the assistant text instead of using the native tool-call channel. This module
parses those blocks back into structured tool calls so the runtime can execute
them like any other tool call.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def extract_embedded_tool_calls(text: str | None) -> list[dict[str, Any]]:
    """Parse ``<tool_call>{...}</tool_call>`` blocks into LangChain-style tool calls."""
    if not text:
        return []
    calls: list[dict[str, Any]] = []
    for index, match in enumerate(_TOOL_CALL_RE.finditer(text)):
        try:
            payload = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            continue
        args = payload.get("arguments", payload.get("args", {}))
        if not isinstance(args, dict):
            args = {}
        calls.append({"name": name, "args": args, "id": f"embedded_{index}"})
    return calls


__all__ = ["extract_embedded_tool_calls"]
