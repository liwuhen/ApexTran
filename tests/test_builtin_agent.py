from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.agent.agent import Agent
from backend.agent.settings import AgentSettings
from backend.core.tape_types import TapeContext

# ---------------------------------------------------------------------------
# Agent.run() tests: merge_back logic and model passthrough
# ---------------------------------------------------------------------------


def _make_agent() -> Agent:
    """Build an Agent with a mocked framework, bypassing real LLM/tape init."""
    framework = MagicMock()
    framework.get_tape_store.return_value = None
    framework.get_system_prompt.return_value = ""

    with patch.object(Agent, "__init__", lambda self, fw: None):
        agent = Agent.__new__(Agent)

    agent.settings = AgentSettings(model="test:model", api_key="k", api_base="b")
    agent.framework = framework
    return agent


class _ForkCapture:
    """Captures the merge_back kwarg passed to fork_tape."""

    def __init__(self) -> None:
        self.merge_back_values: list[bool] = []

    @contextlib.asynccontextmanager
    async def fork_tape(self, tape_name: str, merge_back: bool = True) -> AsyncGenerator[None, None]:
        self.merge_back_values.append(merge_back)
        yield


class _FakeTape:
    """A tape whose async storage methods are real coroutines (MagicMock isn't awaitable)."""

    def __init__(self) -> None:
        self.name = "test-tape"
        self.context = TapeContext(state={})

    async def append_async(self, entry: Any) -> None:
        return None

    async def read_messages_async(self, *, context: Any = None) -> list[dict]:
        return []


class _FakeTapeService:
    """Minimal TapeService stand-in for testing Agent.run_stream()."""

    def __init__(self, fork_capture: _ForkCapture) -> None:
        self._fork = fork_capture

    def session_tape(self, session_id: str, workspace: Any) -> _FakeTape:
        return _FakeTape()

    async def ensure_bootstrap_anchor(self, tape_name: str) -> None:
        pass

    async def append_event(self, tape_name: str, name: str, payload: dict) -> None:
        pass

    @contextlib.asynccontextmanager
    async def fork_tape(self, tape_name: str, merge_back: bool = True) -> AsyncGenerator[None, None]:
        async with self._fork.fork_tape(tape_name, merge_back=merge_back):
            yield


def _fake_chat_model():
    """An offline streaming chat model that emits a single 'done' chunk."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

    class _Model(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessageChunk(content="done"))])

        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content="done"))

        def bind_tools(self, tools, **kwargs):
            return self

    return _Model()


def _capture_model(monkeypatch) -> list[str | None]:
    """Patch the chat-model factory to record the requested model and return a fake."""
    captured: list[str | None] = []

    def factory(settings, model=None):
        captured.append(model)
        return _fake_chat_model()

    monkeypatch.setattr("backend.llm.graph.build_chat_model", factory)
    return captured


@pytest.mark.asyncio
async def test_agent_run_regular_session_merges_back(monkeypatch) -> None:
    """A regular (non-temp) session should merge tape entries back."""
    _capture_model(monkeypatch)
    agent = _make_agent()
    fork_capture = _ForkCapture()
    agent.tapes = _FakeTapeService(fork_capture)  # type: ignore[assignment]

    result = await agent.run_stream(session_id="user/session1", prompt="hello", state={"_runtime_workspace": "/tmp"})  # noqa: S108
    [event async for event in result]

    assert fork_capture.merge_back_values == [True]


@pytest.mark.asyncio
async def test_agent_run_temp_session_does_not_merge_back(monkeypatch) -> None:
    """A temp/ session should NOT merge tape entries back."""
    _capture_model(monkeypatch)
    agent = _make_agent()
    fork_capture = _ForkCapture()
    agent.tapes = _FakeTapeService(fork_capture)  # type: ignore[assignment]

    result = await agent.run_stream(session_id="temp/abc123", prompt="hello", state={"_runtime_workspace": "/tmp"})  # noqa: S108
    [event async for event in result]

    assert fork_capture.merge_back_values == [False]


@pytest.mark.asyncio
async def test_agent_run_passes_model_to_llm(monkeypatch) -> None:
    """The model parameter should be forwarded to the chat-model factory."""
    captured = _capture_model(monkeypatch)
    agent = _make_agent()
    agent.tapes = _FakeTapeService(_ForkCapture())  # type: ignore[assignment]

    result = await agent.run_stream(
        session_id="user/s1",
        prompt="hello",
        state={"_runtime_workspace": "/tmp"},  # noqa: S108
        model="openai:gpt-4o",
    )
    [event async for event in result]

    assert captured == ["openai:gpt-4o"]


@pytest.mark.asyncio
async def test_agent_run_empty_prompt_returns_error() -> None:
    agent = _make_agent()
    agent.tapes = MagicMock()  # type: ignore[assignment]

    result = await agent.run_stream(session_id="user/s1", prompt="", state={})
    events = [event async for event in result]

    assert [(event.kind, event.data) for event in events] == [
        ("text", {"delta": "error: empty prompt"}),
        ("final", {"ok": False, "text": "error: empty prompt"}),
    ]


@pytest.mark.asyncio
async def test_agent_run_model_defaults_to_none(monkeypatch) -> None:
    """When model is not specified, None is forwarded to the chat-model factory."""
    captured = _capture_model(monkeypatch)
    agent = _make_agent()
    agent.tapes = _FakeTapeService(_ForkCapture())  # type: ignore[assignment]

    result = await agent.run_stream(session_id="user/s1", prompt="hello", state={"_runtime_workspace": "/tmp"})  # noqa: S108
    [event async for event in result]

    assert captured == [None]
