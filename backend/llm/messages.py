"""LangChain message/tool conversion — project-owned.

Bridges ApexTran's role-dict messages and core ``Tool`` objects to the LangChain
``BaseMessage`` / ``StructuredTool`` shapes the chat model understands, and back.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool

from backend.tools.tools import model_tools  # noqa: F401  (kept for API parity)

if TYPE_CHECKING:
    from backend.core.tools import Tool, ToolContext


def _model_name(name: str) -> str:
    return name.replace(".", "_")


def _make_coroutine(tool: Tool, context: ToolContext):
    async def _run(**kwargs: Any) -> str:
        try:
            output = tool.run(context=context, **kwargs) if tool.context else tool.run(**kwargs)
            if inspect.isawaitable(output):
                output = await output
        except Exception as exc:
            return f"error: {exc}"
        return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)

    return _run


def build_lc_tools(tools: Iterable[Tool], context: ToolContext) -> list[StructuredTool]:
    """Wrap core ``Tool`` objects as LangChain ``StructuredTool`` (model-facing names)."""
    lc_tools: list[StructuredTool] = []
    for tool in tools:
        lc_tools.append(
            StructuredTool(
                name=_model_name(tool.name),
                description=tool.description or "",
                args_schema=tool.parameters or {"type": "object", "properties": {}},
                coroutine=_make_coroutine(tool, context),
            )
        )
    return lc_tools


def _to_lc_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function", {}) if isinstance(call, dict) else {}
        name = function.get("name") or call.get("name", "")
        raw_args = function.get("arguments", call.get("args", {}))
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except (ValueError, TypeError):
                args = {}
        else:
            args = raw_args or {}
        converted.append({"name": name, "args": args, "id": call.get("id", "")})
    return converted


def to_lc_messages(messages: Iterable[dict[str, Any]], *, system_prompt: str | None = None) -> list[BaseMessage]:
    """Convert role-dict messages into LangChain ``BaseMessage`` objects."""
    lc_messages: list[BaseMessage] = []
    if system_prompt:
        lc_messages.append(SystemMessage(content=system_prompt))
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role in ("user", "human"):
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            tool_calls = message.get("tool_calls")
            if tool_calls:
                lc_messages.append(AIMessage(content=content or "", tool_calls=_to_lc_tool_calls(tool_calls)))
            else:
                lc_messages.append(AIMessage(content=content))
        elif role == "tool":
            lc_messages.append(ToolMessage(content=content, tool_call_id=message.get("tool_call_id", "")))
    return lc_messages


def tape_payloads_from_messages(messages: Iterable[BaseMessage | dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert LangChain messages (or role dicts) back into tape message payloads."""
    payloads: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, dict):
            payloads.append(dict(message))
            continue
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, ToolMessage):
            role = "tool"
        else:
            role = "assistant"
        payloads.append({"role": role, "content": message.content})
    return payloads


__all__ = ["build_lc_tools", "tape_payloads_from_messages", "to_lc_messages"]
