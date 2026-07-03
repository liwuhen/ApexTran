"""Model turn execution — project-owned (LangGraph).

A single turn is a compiled ``StateGraph``:

    START → agent → (tool_calls?) → tools → END

(``tools`` goes straight to END — one turn per call; multi-step iteration stays
in the agent's outer policy loop.) The ``agent`` node calls the chat model and
promotes native *and* embedded ``<tool_call>`` calls; ``ToolNode`` executes them.

``run_step`` runs the graph non-streaming and returns a :class:`StepResult`;
``stream_step`` runs ``graph.astream(stream_mode=["messages","values"])`` —
``messages`` mode yields per-token deltas, ``values`` mode carries the terminal
state — translated into :class:`StreamEvent`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from loguru import logger

from backend.core.errors import AgentError, ErrorKind
from backend.core.events import AsyncStreamEvents, StreamEvent, StreamState
from backend.core.tape_types import TapeEntry
from backend.core.tools import ToolContext
from backend.llm.client import build_chat_model
from backend.llm.embedded_tools import extract_embedded_tool_calls
from backend.llm.messages import build_lc_tools, to_lc_messages

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import Runnable
    from langchain_core.tools import StructuredTool

    from backend.agent.settings import AgentSettings
    from backend.core.engine import Tape
    from backend.core.tools import Tool


@dataclass(frozen=True)
class StepResult:
    """Outcome of a single model turn (duck-compatible with ``ToolAutoResult``)."""

    kind: Literal["text", "tools", "error"]
    text: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    error: AgentError | None = None
    usage: dict[str, Any] | None = None

    @classmethod
    def text_result(cls, text: str) -> StepResult:
        return cls(kind="text", text=text)

    @classmethod
    def tools_result(cls, tool_calls: list[dict[str, Any]], tool_results: list[Any]) -> StepResult:
        return cls(kind="tools", tool_calls=tool_calls, tool_results=tool_results)

    @classmethod
    def error_result(cls, error: AgentError) -> StepResult:
        return cls(kind="error", error=error)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        return "".join(parts)
    return str(content) if content is not None else ""


def _user_payload(prompt: str | list[dict]) -> dict[str, Any]:
    return {"role": "user", "content": prompt}


def _openai_tool_call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _build_graph(model: Runnable, lc_tools: list[StructuredTool]):
    """Compile the single-turn ``START → agent → (tools?) → END`` graph."""

    async def agent_node(state: MessagesState) -> dict[str, list[BaseMessage]]:
        message = await model.ainvoke(state["messages"])
        if not getattr(message, "tool_calls", None):
            embedded = extract_embedded_tool_calls(_content_text(message.content))
            if embedded:
                message = AIMessage(content=message.content, tool_calls=embedded, id=getattr(message, "id", None))
        return {"messages": [message]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(lc_tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    builder.add_edge("tools", END)
    return builder.compile()


def _split_messages(messages: list[BaseMessage]) -> tuple[AIMessage | None, list[ToolMessage]]:
    ai_message: AIMessage | None = None
    tool_messages: list[ToolMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            tool_messages.append(message)
        elif isinstance(message, AIMessage):
            ai_message = message
    return ai_message, tool_messages


def _result_from_messages(messages: list[BaseMessage]) -> tuple[str, list[dict[str, Any]], list[Any]]:
    ai_message, tool_messages = _split_messages(messages)
    text = _content_text(ai_message.content) if ai_message is not None else ""
    tool_calls: list[dict[str, Any]] = []
    if ai_message is not None and ai_message.tool_calls:
        tool_calls = [
            _openai_tool_call(call["name"], call.get("args") or {}, call.get("id") or f"call_{i}")
            for i, call in enumerate(ai_message.tool_calls)
        ]
    tool_results = [tm.content for tm in tool_messages]
    return text, tool_calls, tool_results


async def _prepare(
    tape: Tape,
    prompt: str | list[dict],
    system_prompt: str | None,
    tools: list[Tool],
    model: str | None,
    settings: AgentSettings,
    chat_model: BaseChatModel | None,
) -> tuple[Any, str, list[BaseMessage]]:
    run_id = uuid.uuid4().hex
    chat_model = chat_model or build_chat_model(settings, model)
    context = ToolContext(tape=tape.name, run_id=run_id, state=dict(tape.context.state))
    lc_tools = build_lc_tools(tools, context)
    bound = chat_model.bind_tools(lc_tools) if lc_tools else chat_model
    graph = _build_graph(bound, lc_tools)

    history = await tape.read_messages_async(context=tape.context)
    lc_messages = to_lc_messages([*history, _user_payload(prompt)], system_prompt=system_prompt)
    await tape.append_async(TapeEntry.message(_user_payload(prompt), run_id=run_id))
    return graph, run_id, lc_messages


async def _record_outcome(
    tape: Tape,
    run_id: str,
    text: str,
    tool_calls: list[dict[str, Any]],
    tool_results: list[Any],
) -> None:
    if tool_calls:
        await tape.append_async(TapeEntry.tool_call(tool_calls, run_id=run_id))
        await tape.append_async(TapeEntry.tool_result(tool_results, run_id=run_id))
    else:
        await tape.append_async(TapeEntry.message({"role": "assistant", "content": text}, run_id=run_id))


async def run_step(
    *,
    tape: Tape,
    prompt: str | list[dict],
    system_prompt: str | None,
    tools: list[Tool],
    model: str | None,
    settings: AgentSettings,
    chat_model: BaseChatModel | None = None,
) -> StepResult:
    """Run one non-streaming model turn and persist the resulting tape entries."""
    graph, run_id, lc_messages = await _prepare(tape, prompt, system_prompt, tools, model, settings, chat_model)
    log = logger.bind(run_id=run_id)

    try:
        final_state = await graph.ainvoke({"messages": lc_messages})
    except Exception as exc:
        log.exception("llm.run_step.error tape={}", tape.name)
        error = AgentError(ErrorKind.PROVIDER, str(exc))
        await tape.append_async(TapeEntry.error(error, run_id=run_id))
        return StepResult.error_result(error)

    text, tool_calls, tool_results = _result_from_messages(final_state["messages"])
    await _record_outcome(tape, run_id, text, tool_calls, tool_results)
    if tool_calls:
        return StepResult.tools_result(tool_calls, tool_results)
    return StepResult.text_result(text)


async def stream_step(
    *,
    tape: Tape,
    prompt: str | list[dict],
    system_prompt: str | None,
    tools: list[Tool],
    model: str | None,
    settings: AgentSettings,
    chat_model: BaseChatModel | None = None,
) -> AsyncStreamEvents:
    """Run one streaming model turn, returning events plus terminal state."""
    graph, run_id, lc_messages = await _prepare(tape, prompt, system_prompt, tools, model, settings, chat_model)
    log = logger.bind(run_id=run_id)
    state = StreamState()

    async def _generate() -> AsyncIterator[StreamEvent]:
        final_messages: list[BaseMessage] = []
        try:
            async for mode, chunk in graph.astream({"messages": lc_messages}, stream_mode=["messages", "values"]):
                if mode == "messages":
                    message, meta = chunk
                    if meta.get("langgraph_node") == "agent" and isinstance(message, AIMessageChunk):
                        delta = _content_text(message.content)
                        if delta:
                            yield StreamEvent("text", {"delta": delta})
                elif mode == "values":
                    final_messages = chunk["messages"]
        except Exception as exc:
            log.exception("llm.stream_step.error tape={}", tape.name)
            error = AgentError(ErrorKind.PROVIDER, str(exc))
            state.error = error
            await tape.append_async(TapeEntry.error(error, run_id=run_id))
            yield StreamEvent("error", {"message": str(exc)})
            yield StreamEvent("final", {"text": "", "ok": False})
            return

        text, tool_calls, tool_results = _result_from_messages(final_messages)
        await _record_outcome(tape, run_id, text, tool_calls, tool_results)
        if tool_calls:
            yield StreamEvent("final", {"text": text, "tool_calls": tool_calls, "tool_results": tool_results})
        else:
            yield StreamEvent("final", {"text": text, "ok": True})

    return AsyncStreamEvents(_generate(), state=state)


__all__ = ["StepResult", "run_step", "stream_step"]
