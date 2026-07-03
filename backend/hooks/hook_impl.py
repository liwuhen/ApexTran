import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import typer
from loguru import logger

from backend.agent.agent import Agent
from backend.app.framework import ApexTranFramework
from backend.channels.base import Channel
from backend.channels.message import ChannelMessage, MediaItem
from backend.context.context import default_tape_context
from backend.core.events import AsyncStreamEvents
from backend.core.store import TapeStore
from backend.core.tape_types import TapeContext
from backend.hooks.hookspecs import hookimpl
from backend.inventory.logicfunction import _inventory_embedding_signal
from backend.inventory.postprocess import LLMPostprocess
from backend.inventory.sqlconstant import (
    _INVENTORY_KEYWORDS,
    INTENT_INVENTORY_SCORE_THRESHOLD,
    INTENT_WEIGHT_EMBEDDING,
    INTENT_WEIGHT_KEYWORD,
    INTENT_WEIGHT_MODEL,
)
from backend.llm.embedding import Embedding
from backend.utils.envelope import content_of, field_of
from backend.utils.types import Envelope, MessageHandler, State

AGENTS_FILE_NAME = "AGENTS.md"
DEFAULT_SYSTEM_PROMPT = """\
<general_instruct>
Call tools or skills to finish the task.
</general_instruct>
<response_instruct>
Before ending this run, you MUST determine whether a response needs to be sent via channel, checking the following conditions:
1. Has the user asked you a question waiting for your answer?
2. Is there any error or important information that needs to be sent to the user immediately?
3. If it is a casual chat, does the conversation need to be continued?

**IMPORTANT:** ApexTran will automatically send your final response through the correct channel.
Do not call channel delivery tools such as feishu, telegram, or discord.
When a response is needed, output the final reply text directly.
</response_instruct>
<context_contract>
Excessively long context may cause model call failures. In this case, you MAY use tape.info to retrieve the token usage and you SHOULD use tape.handoff tool to shorten the retrieved history.
</context_contract>
"""


class BuiltinImpl:
    """Default hook implementations for basic runtime operations."""

    def __init__(self, framework: ApexTranFramework) -> None:
        from backend.tools import toolimpl  # noqa: F401

        self.framework = framework
        self.agent = Agent(framework)
        self.llm_postprocess = LLMPostprocess()
        self._intent_embedding_client: Embedding | None = None
        self._inventory_proto_embeddings: list[list[float]] | None = None

    @hookimpl
    def resolve_session(self, message: ChannelMessage) -> str:
        session_id = field_of(message, "session_id")
        if session_id is not None and str(session_id).strip():
            return str(session_id)
        channel = str(field_of(message, "channel", "default"))
        chat_id = str(field_of(message, "chat_id", "default"))
        return f"{channel}:{chat_id}"

    @hookimpl
    async def load_state(self, message: ChannelMessage, session_id: str) -> State:
        lifespan = field_of(message, "lifespan")
        if lifespan is not None:
            await lifespan.__aenter__()
        state = {"session_id": session_id, "_runtime_agent": self.agent}
        if context := field_of(message, "context_str"):
            state["context"] = context
        return state

    @hookimpl
    async def save_state(self, session_id: str, state: State, message: ChannelMessage, model_output: str) -> None:
        tp, value, traceback = sys.exc_info()
        lifespan = field_of(message, "lifespan")
        if lifespan is not None:
            await lifespan.__aexit__(tp, value, traceback)

    @hookimpl
    async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
        content = content_of(message)
        if content.startswith("/"):
            message.kind = "command"
            state["kind"] = "command"
            return content
        context = field_of(message, "context_str")
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
        text = f"{context_prefix}{content}"

        media = field_of(message, "media") or []
        if not media:
            # logger.info("session.run.prompt state: text")
            return text

        media_parts: list[dict] = []
        for item in cast("list[MediaItem]", media):
            match item.type:
                case "image":
                    data_url = await item.get_url()
                    if not data_url:
                        continue
                    media_parts.append({"type": "image_url", "image_url": {"url": data_url}})
                case _:
                    attachment_desc = f"[Attached {item.type}: {item.mime_type}"
                    if item.filename:
                        attachment_desc += f", filename={item.filename}"
                    attachment_desc += "]"
                    media_parts.append({"type": "text", "text": attachment_desc})
        if media_parts:
            # logger.info("session.run.prompt state: media")
            return [{"type": "text", "text": text}, *media_parts]
        return text

    @hookimpl
    async def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
        return await self.agent.run(session_id=session_id, prompt=prompt, state=state)

    @hookimpl
    async def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
        return await self.agent.run_stream(session_id=session_id, prompt=prompt, state=state)

    @hookimpl
    def register_cli_commands(self, app: typer.Typer) -> None:
        from backend.cli import cli

        app.command("run")(cli.run)
        app.command("cli")(cli.chat)
        app.command("web")(cli.web)
        app.add_typer(cli.login_app)
        app.command("hooks", hidden=True)(cli.list_hooks)
        app.command("gateway")(cli.gateway)
        app.command("install")(cli.install)
        app.command("uninstall")(cli.uninstall)
        app.command("update")(cli.update)

    def _read_agents_file(self, state: State) -> str:
        workspace = state.get("_runtime_workspace", str(Path.cwd()))
        prompt_path = Path(workspace) / AGENTS_FILE_NAME
        if not prompt_path.is_file():
            return ""
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @hookimpl
    def system_prompt(self, prompt: str | list[dict], state: State) -> str:
        base = DEFAULT_SYSTEM_PROMPT + "\n\n" + self._read_agents_file(state)
        return base

    @hookimpl
    def provide_channels(self, message_handler: MessageHandler) -> list[Channel]:
        from backend.channels.cli import CliChannel
        from backend.channels.feishu import FeishuChannel
        from backend.channels.telegram import TelegramChannel
        from backend.channels.web import WebChannel

        return [
            TelegramChannel(on_receive=message_handler),
            FeishuChannel(on_receive=message_handler),
            CliChannel(on_receive=message_handler, agent=self.agent),
            WebChannel(on_receive=message_handler),
        ]

    @hookimpl
    async def on_error(self, stage: str, error: Exception, message: Envelope | None) -> None:
        if message is not None:
            outbound = ChannelMessage(
                session_id=field_of(message, "session_id", "unknown"),
                channel=field_of(message, "channel", "default"),
                chat_id=field_of(message, "chat_id", "default"),
                content=f"An error occurred at stage '{stage}': {error}",
                kind="error",
            )
            await self.framework._hook_runtime.call_many("dispatch_outbound", message=outbound)

    @hookimpl
    async def dispatch_outbound(self, message: Envelope) -> bool:
        content_of(message)
        session_id = field_of(message, "session_id")
        if field_of(message, "output_channel") != "cli":
            logger.info("session.run.outbound session_id={}", session_id)
        return await self.framework.dispatch_via_router(message)

    @hookimpl
    def render_outbound(
        self,
        message: Envelope,
        session_id: str,
        state: State,
        model_output: str,
    ) -> list[ChannelMessage]:
        outbound = ChannelMessage(
            session_id=session_id,
            channel=field_of(message, "channel", "default"),
            chat_id=field_of(message, "chat_id", "default"),
            content=model_output,
            output_channel=field_of(message, "output_channel", "default"),
            kind=field_of(message, "kind", "normal"),
        )
        return [outbound]

    @hookimpl
    def provide_tape_store(self) -> TapeStore:
        """Provide the default tape storage backend for the framework."""
        from backend.memory.store import FileTapeStore

        return FileTapeStore(directory=self.agent.settings.home / "tapes")

    @hookimpl
    def build_tape_context(self) -> TapeContext:
        return default_tape_context()

    @hookimpl
    def intent_detection(self, message: ChannelMessage, model_output: str, state: State) -> None:  # noqa: C901 - inventory intent scoring (keyword + model + embedding)
        if state.get("kind") == "command":
            return
        parsed: dict[str, object] = {}
        if isinstance(model_output, str) and model_output.strip():
            try:
                loaded = json.loads(model_output)
                if isinstance(loaded, dict):
                    parsed = loaded
            except Exception:
                parsed = {}
        elif isinstance(model_output, dict):
            parsed = model_output

        clarify = parsed.get("intent")
        if clarify == "clarify_intent" or clarify == "clarify_target":
            state["intent"] = clarify
            # logger.info("session.run.intent_detection intent: {}", clarify)
            return

        try:
            content = json.loads(content_of(message))
        except Exception:
            content = content_of(message)
        # Channels wrap content as {"message": ...}; the CLI sends a plain string.
        if isinstance(content, dict):
            content = content.get("message", "")
        content = str(content)
        keyword_score = 1.0 if any(keyword in content for keyword in _INVENTORY_KEYWORDS) else 0.0
        model_score = 1.0 if str(parsed.get("intent", "")).strip() == "query_inventory" else 0.0
        embedding_score, embedding_ok = _inventory_embedding_signal(
            self._intent_embedding_client, content, self._inventory_proto_embeddings
        )

        w_kw = float(INTENT_WEIGHT_KEYWORD)
        w_mo = float(INTENT_WEIGHT_MODEL)
        w_em = float(INTENT_WEIGHT_EMBEDDING)
        if not embedding_ok:
            denom = w_kw + w_mo
            if denom > 0.0:
                w_kw, w_mo = w_kw / denom, w_mo / denom
            w_em = 0.0

        fused = w_kw * keyword_score + w_mo * model_score + w_em * embedding_score
        threshold = float(INTENT_INVENTORY_SCORE_THRESHOLD)
        intent = "query_inventory" if fused >= threshold else "chat"

        state["intent"] = intent
        # logger.info("session.run.intent_detection intent: {}", intent)

    @hookimpl
    def postprocess_model_output(self, model_output: str, state: State) -> str:
        if state.get("kind") == "command":
            return model_output

        try:
            model_output = json.loads(model_output)
        except Exception:
            return model_output

        if state.get("intent") == "query_inventory":
            model_output = self.llm_postprocess.postprocess(model_output, state)
        elif state.get("intent") in ("clarify_intent", "clarify_target"):
            model_output = self.llm_postprocess.clarify(model_output, state)
        elif isinstance(model_output, dict):
            model_output = json.dumps(model_output, ensure_ascii=False)

        return model_output
