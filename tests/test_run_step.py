"""Phase 2: non-streaming model engine (llm.graph.run_step) on LangChain.

Uses a fully offline fake chat model — no network, no API key. Verifies the
text path, the tool-call path, tape bookkeeping, and an end-to-end Agent.run.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk

from backend.agent.agent import Agent
from backend.context.context import default_tape_context
from backend.core.engine import ModelEngine
from backend.core.store import InMemoryTapeStore
from backend.llm.graph import run_step, stream_step
from backend.tools.tools import REGISTRY, tool


class FakeChatModel(BaseChatModel):
    """Returns a preset AIMessage; ignores bound tools."""

    reply: AIMessage

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=self.reply)])

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


class StreamFakeChatModel(BaseChatModel):
    """Streams a preset list of AIMessageChunks via ``_astream``."""

    chunks: list

    @property
    def _llm_type(self) -> str:
        return "stream-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        from langchain_core.outputs import ChatGeneration, ChatResult

        merged = self.chunks[0]
        for chunk in self.chunks[1:]:
            merged = merged + chunk
        return ChatResult(generations=[ChatGeneration(message=merged)])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        from langchain_core.outputs import ChatGenerationChunk

        for chunk in self.chunks:
            yield ChatGenerationChunk(message=chunk)

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


async def _new_tape(name: str = "t1"):
    engine = ModelEngine(InMemoryTapeStore(), default_tape_context())
    tape = engine.tape(name)
    # Agent.run seeds this via ensure_bootstrap_anchor; reproduce it here.
    await tape.handoff_async("session/start", state={"owner": "human"})
    return tape


def _settings():
    from backend.agent.settings import AgentSettings

    return AgentSettings(model="fake:test")


@pytest.mark.asyncio
async def test_run_step_text_path_records_messages() -> None:
    tape = await _new_tape()
    fake = FakeChatModel(reply=AIMessage(content="hello there"))

    result = await run_step(
        tape=tape,
        prompt="hi",
        system_prompt="you are a bot",
        tools=[],
        model=None,
        settings=_settings(),
        chat_model=fake,
    )

    assert result.kind == "text"
    assert result.text == "hello there"

    messages = await tape.read_messages_async(context=tape.context)
    assert {"role": "user", "content": "hi"} in messages
    assert {"role": "assistant", "content": "hello there"} in messages


@pytest.mark.asyncio
async def test_run_step_embedded_tool_call_is_promoted_and_executed() -> None:
    """Providers that embed <tool_call> in text should still drive ToolNode."""
    tool_name = "tests.embed_step"
    REGISTRY.pop(tool_name, None)

    @tool(name=tool_name)
    def embed_step(text: str) -> str:
        return f"embedded:{text}"

    tape = await _new_tape("t_embed")
    fake = FakeChatModel(
        reply=AIMessage(content='<tool_call>{"name": "tests_embed_step", "arguments": {"text": "hi"}}</tool_call>')
    )

    result = await run_step(
        tape=tape,
        prompt="do it",
        system_prompt=None,
        tools=[embed_step],
        model=None,
        settings=_settings(),
        chat_model=fake,
    )

    assert result.kind == "tools"
    assert result.tool_results == ["embedded:hi"]
    REGISTRY.pop(tool_name, None)


@pytest.mark.asyncio
async def test_run_step_tool_call_path_executes_and_records() -> None:
    tool_name = "tests.echo_step"
    REGISTRY.pop(tool_name, None)

    @tool(name=tool_name)
    def echo_step(text: str) -> str:
        return f"echoed:{text}"

    tape = await _new_tape("t2")
    fake = FakeChatModel(
        reply=AIMessage(
            content="",
            tool_calls=[{"name": "tests_echo_step", "args": {"text": "yo"}, "id": "call_1"}],
        )
    )

    result = await run_step(
        tape=tape,
        prompt="please echo",
        system_prompt=None,
        tools=[echo_step],
        model=None,
        settings=_settings(),
        chat_model=fake,
    )

    assert result.kind == "tools"
    assert result.tool_results == ["echoed:yo"]
    assert result.tool_calls[0]["function"]["name"] == "tests_echo_step"

    # Tape replays the tool call + result back into the message stream.
    messages = await tape.read_messages_async(context=tape.context)
    assert any(msg.get("role") == "tool" and "echoed:yo" in str(msg.get("content")) for msg in messages)

    REGISTRY.pop(tool_name, None)


@pytest.mark.asyncio
async def test_run_step_model_error_returns_error_result() -> None:
    class BoomModel(FakeChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            raise RuntimeError("model exploded")

    tape = await _new_tape("t3")
    result = await run_step(
        tape=tape,
        prompt="hi",
        system_prompt=None,
        tools=[],
        model=None,
        settings=_settings(),
        chat_model=BoomModel(reply=AIMessage(content="x")),
    )

    assert result.kind == "error"
    assert result.error is not None
    assert "model exploded" in result.error.message


@pytest.mark.asyncio
async def test_agent_run_end_to_end_text(monkeypatch, tmp_path) -> None:
    from backend.app.framework import ApexTranFramework

    fake = FakeChatModel(reply=AIMessage(content="final answer"))
    monkeypatch.setattr(
        "backend.llm.graph.build_chat_model",
        lambda settings, model=None: fake,
    )

    framework = ApexTranFramework()
    framework.get_tape_store = lambda: InMemoryTapeStore()  # type: ignore[method-assign]
    framework.build_tape_context = lambda: default_tape_context()  # type: ignore[method-assign]
    agent = Agent(framework)

    output = await agent.run(
        session_id="temp/e2e",
        prompt="what is up",
        state={"_runtime_workspace": str(tmp_path)},
    )

    assert output == "final answer"


# --- Phase 3: streaming (stream_step / run_stream) ---


@pytest.mark.asyncio
async def test_stream_step_text_streams_deltas_and_final() -> None:
    tape = await _new_tape("s1")
    fake = StreamFakeChatModel(chunks=[AIMessageChunk(content="hel"), AIMessageChunk(content="lo")])

    stream = await stream_step(
        tape=tape,
        prompt="hi",
        system_prompt="sys",
        tools=[],
        model=None,
        settings=_settings(),
        chat_model=fake,
    )
    events = [event async for event in stream]

    deltas = [e.data["delta"] for e in events if e.kind == "text"]
    finals = [e for e in events if e.kind == "final"]
    assert deltas == ["hel", "lo"]
    assert finals and finals[-1].data.get("text") == "hello"
    assert stream.error is None

    messages = await tape.read_messages_async(context=tape.context)
    assert {"role": "assistant", "content": "hello"} in messages


@pytest.mark.asyncio
async def test_stream_step_tool_call_emits_final_with_tools() -> None:
    tool_name = "tests.echo_stream"
    REGISTRY.pop(tool_name, None)

    @tool(name=tool_name)
    def echo_stream(text: str) -> str:
        return f"streamed:{text}"

    tape = await _new_tape("s2")
    fake = FakeChatModel(
        reply=AIMessage(
            content="",
            tool_calls=[{"name": "tests_echo_stream", "args": {"text": "yo"}, "id": "call_1"}],
        )
    )

    stream = await stream_step(
        tape=tape,
        prompt="echo it",
        system_prompt=None,
        tools=[echo_stream],
        model=None,
        settings=_settings(),
        chat_model=fake,
    )
    events = [event async for event in stream]

    final = next(e for e in events if e.kind == "final")
    assert final.data["tool_results"] == ["streamed:yo"]
    assert final.data["tool_calls"][0]["function"]["name"] == "tests_echo_stream"

    REGISTRY.pop(tool_name, None)


@pytest.mark.asyncio
async def test_stream_step_error_emits_error_event_and_state() -> None:
    class BoomStream(StreamFakeChatModel):
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            raise RuntimeError("stream exploded")
            yield  # pragma: no cover - makes this an async generator

    tape = await _new_tape("s3")
    stream = await stream_step(
        tape=tape,
        prompt="hi",
        system_prompt=None,
        tools=[],
        model=None,
        settings=_settings(),
        chat_model=BoomStream(chunks=[AIMessageChunk(content="x")]),
    )
    events = [event async for event in stream]

    assert any(e.kind == "error" and "stream exploded" in e.data["message"] for e in events)
    assert stream.error is not None
    assert "stream exploded" in stream.error.message


@pytest.mark.asyncio
async def test_agent_run_stream_end_to_end(monkeypatch, tmp_path) -> None:
    from backend.app.framework import ApexTranFramework

    fake = StreamFakeChatModel(chunks=[AIMessageChunk(content="strea"), AIMessageChunk(content="med!")])
    monkeypatch.setattr(
        "backend.llm.graph.build_chat_model",
        lambda settings, model=None: fake,
    )

    framework = ApexTranFramework()
    framework.get_tape_store = lambda: InMemoryTapeStore()  # type: ignore[method-assign]
    framework.build_tape_context = lambda: default_tape_context()  # type: ignore[method-assign]
    agent = Agent(framework)

    stream = await agent.run_stream(
        session_id="temp/stream",
        prompt="go",
        state={"_runtime_workspace": str(tmp_path)},
    )
    text = "".join(e.data.get("delta", "") for e in [ev async for ev in stream] if e.kind == "text")

    assert text == "streamed!"
