"""Web channel — HTTP/SSE gateway that speaks the LangGraph Platform protocol.

This lets the ported deer-flow frontend (which talks to the backend via
``@langchain/langgraph-sdk``) drive ApexTran's pluggy turn pipeline.

Design (see ``docs/web-gateway-design.md``):
- The channel runs an aiohttp server and registers itself like any other
  channel via ``provide_channels``.
- An HTTP ``POST /threads/{id}/runs/stream`` turns into a ``ChannelMessage``
  handed to the framework (``on_receive``). The turn runs asynchronously in the
  ChannelManager loop; its streaming events are routed back here through
  ``stream_events`` (the manager's ``wrap_stream`` dispatches by channel name).
- We correlate the HTTP request and the turn's stream via a ``run_id`` carried
  in the message ``context`` and a per-run :class:`asyncio.Queue`.

Wire format matches what the LangGraph SDK / ``useStream`` hook expects:
``event: <type>\\ndata: <json>\\n\\n``, with ``Content-Location`` on the run
stream response.

Scope: milestone M1 (minimal chat). Resource endpoints (models/skills/...) and
richer history come in later milestones.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any, ClassVar

from aiohttp import web
from loguru import logger

from backend.channels.base import Channel
from backend.channels.message import ChannelMessage
from backend.core.events import StreamEvent
from backend.utils.types import MessageHandler

# Sentinel pushed onto a run queue to signal the stream is finished.
_END = object()


def _sse(event: str, data: Any, *, event_id: str | None = None) -> bytes:
    """Format one SSE frame the way the LangGraph SDK decoder expects."""
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts).encode("utf-8")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


class WebChannel(Channel):
    """aiohttp-based LangGraph-compatible gateway channel."""

    name: ClassVar[str] = "web"

    #: assistant/graph id the frontend pins (``useStream({ assistantId })``).
    ASSISTANT_ID = "lead_agent"

    def __init__(self, on_receive: MessageHandler, host: str | None = None, port: int | None = None) -> None:
        self._on_receive = on_receive
        self._host = host or os.getenv("ApexTran_WEB_HOST", "127.0.0.1")
        self._port = port or int(os.getenv("ApexTran_WEB_PORT", "8000"))
        self._runner: web.AppRunner | None = None
        # run_id -> queue of ("delta", str) | (_END, None)
        self._streams: dict[str, asyncio.Queue] = {}
        # thread_id -> list of LangGraph-shaped messages ({type, content, id})
        # 进程内的会话历史索引。它会被持久化到磁盘(见 _store_path),
        # 这样后端重启后历史不会丢失。
        self._threads: dict[str, list[dict[str, Any]]] = {}
        # 历史落盘路径:与 tapes 同级,放在 ApexTran_HOME 下。
        home = Path(os.path.expanduser(os.getenv("ApexTran_HOME", "~/.ApexTran")))
        self._store_path = home / "web_threads.json"
        self._load_threads()

    # ------------------------------------------------------------------ #
    # Persistence: thread history survives backend restarts.
    # ------------------------------------------------------------------ #
    def _load_threads(self) -> None:
        """启动时从磁盘恢复会话历史(文件不存在/损坏则视为空)。"""
        try:
            raw = self._store_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._threads = {str(tid): msgs for tid, msgs in data.items() if isinstance(msgs, list)}
                logger.info(f"web.channel restored {len(self._threads)} thread(s) from {self._store_path}")
        except FileNotFoundError:
            pass
        except Exception as exc:  # 损坏的历史文件不应阻止后端启动
            logger.warning(f"web.channel failed to load thread history: {exc}")

    def _save_threads(self) -> None:
        """把会话历史原子写入磁盘(临时文件 + rename,避免半截写入)。"""
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._threads, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            tmp.replace(self._store_path)
        except Exception as exc:
            logger.warning(f"web.channel failed to persist thread history: {exc}")

    # ------------------------------------------------------------------ #
    # Channel lifecycle
    # ------------------------------------------------------------------ #
    @property
    def enabled(self) -> bool:
        return True

    async def start(self, stop_event: asyncio.Event) -> None:
        app = web.Application()
        app.add_routes([
            web.get("/health", self._health),
            # --- LangGraph Platform native API (served at root; the
            #     frontend's /api/langgraph/* rewrite strips the prefix) ---
            web.post("/threads", self._create_thread),
            web.post("/threads/search", self._search_threads),
            web.get("/threads/{thread_id}", self._get_thread),
            web.get("/threads/{thread_id}/state", self._thread_state),
            web.post("/threads/{thread_id}/history", self._thread_history),
            web.post("/threads/{thread_id}/runs/stream", self._runs_stream),
            web.post("/assistants/search", self._assistants_search),
            web.get("/assistants/{assistant_id}", self._get_assistant),
            # --- Gateway resource API (served under /api/*; the frontend's
            #     /api/* rewrite forwards these keeping the prefix) ---
            web.get("/api/models", self._list_models),
            web.get("/api/skills", self._list_skills),
        ])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info(f"web.channel listening on http://{self._host}:{self._port}")

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        logger.info("web.channel stopped")

    # ------------------------------------------------------------------ #
    # Stream routing: the turn's events come back here via the manager's
    # wrap_stream -> channel.stream_events(message, stream).
    # ------------------------------------------------------------------ #
    def stream_events(self, message: ChannelMessage, stream: AsyncIterable[StreamEvent]) -> AsyncIterable[StreamEvent]:
        run_id = message.context.get("run_id") if isinstance(message.context, dict) else None
        queue = self._streams.get(run_id) if run_id else None

        async def _wrap() -> AsyncIterable[StreamEvent]:
            try:
                async for event in stream:
                    if queue is not None and event.kind == "text":
                        delta = str(event.data.get("delta", ""))
                        if delta:
                            await queue.put(("delta", delta))
                    yield event
            finally:
                if queue is not None:
                    await queue.put((_END, None))

        return _wrap()

    # ------------------------------------------------------------------ #
    # HTTP handlers — LangGraph Platform compatible
    # ------------------------------------------------------------------ #
    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "channel": self.name})

    async def _create_thread(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        thread_id = body.get("thread_id") or str(uuid.uuid4())
        self._threads.setdefault(thread_id, [])
        self._save_threads()
        return web.json_response(self._thread_obj(thread_id))

    async def _get_thread(self, request: web.Request) -> web.Response:
        thread_id = request.match_info["thread_id"]
        return web.json_response(self._thread_obj(thread_id))

    async def _search_threads(self, request: web.Request) -> web.Response:
        return web.json_response([self._thread_obj(tid) for tid in self._threads])

    async def _thread_state(self, request: web.Request) -> web.Response:
        thread_id = request.match_info["thread_id"]
        return web.json_response(self._state_obj(thread_id))

    async def _thread_history(self, request: web.Request) -> web.Response:
        thread_id = request.match_info["thread_id"]
        messages = self._threads.get(thread_id, [])
        if not messages:
            return web.json_response([])
        return web.json_response([self._state_obj(thread_id)])

    async def _list_models(self, request: web.Request) -> web.Response:
        """Surface ApexTran's configured model in the frontend's expected shape."""
        raw = os.getenv("ApexTran_MODEL", "deepseek:deepseek-chat").strip()
        _, _, model_id = raw.partition(":")
        model_id = model_id or raw
        return web.json_response({
            "models": [
                {
                    "id": raw,
                    "name": raw,
                    "model": model_id,
                    "display_name": raw,
                    "supports_thinking": False,
                }
            ]
        })

    async def _list_skills(self, request: web.Request) -> web.Response:
        """List ApexTran's on-disk skills (``backend/skills/<name>/SKILL.md``)."""
        skills = []
        skills_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
        try:
            for name in sorted(os.listdir(skills_dir)):
                skill_md = os.path.join(skills_dir, name, "SKILL.md")
                if not os.path.isfile(skill_md):
                    continue
                description = ""
                try:
                    with open(skill_md, encoding="utf-8") as fh:
                        head = fh.read(2000)
                    # crude frontmatter/first-paragraph description probe
                    for line in head.splitlines():
                        line = line.strip()
                        if line.lower().startswith("description:"):
                            description = line.split(":", 1)[1].strip()
                            break
                except OSError:
                    pass
                skills.append({
                    "name": name,
                    "description": description,
                    "license": None,
                    "category": "public",
                    "enabled": True,
                })
        except OSError:
            pass
        return web.json_response({"skills": skills})

    async def _assistants_search(self, request: web.Request) -> web.Response:
        return web.json_response([self._assistant_obj()])

    async def _get_assistant(self, request: web.Request) -> web.Response:
        return web.json_response(self._assistant_obj())

    async def _runs_stream(self, request: web.Request) -> web.StreamResponse:
        """创建一次 run 并以 SSE 流式返回其事件(M1 阶段的核心端点)。

        流程:解析入站请求 -> 注册 per-run 队列 -> 打开 SSE 响应 -> 把 turn 交给
        框架 -> 消费队列(由 ``stream_events`` 填充)逐帧发出 ``values`` ->
        turn 结束后发出最终的 ``values`` + ``end``。
        """
        # --- 1. 解析请求:属于哪个 thread、用户输入了什么、生成新的 run_id ---
        thread_id = request.match_info["thread_id"]
        body = await _json_body(request)
        user_text = _extract_input_text(body)
        run_id = str(uuid.uuid4())

        # --- 2. 把这次人类发言追加到该 thread 的历史里,并提前分配 AI 消息 id,
        #        让后续每一帧流式输出都复用它(SDK 按 id 对"生成中"的 AI 消息
        #        做更新去重,而不是不断追加新消息)。 ---
        messages = self._threads.setdefault(thread_id, [])
        user_msg = {"type": "human", "content": user_text, "id": str(uuid.uuid4())}
        messages.append(user_msg)
        # 提问一追加就落盘,即使本次 run 中途失败,问题也不会丢。
        self._save_threads()
        ai_id = str(uuid.uuid4())

        # --- 3. 创建 per-run 队列并以 run_id 注册,这样(由 manager 循环调用的)
        #        stream_events() 才能找到它,把模型的文本增量回灌过来。 ---
        queue: asyncio.Queue = asyncio.Queue()
        self._streams[run_id] = queue

        # --- 4. 打开分块 SSE 响应。Content-Location 携带 run 路径;
        #        X-Accel-Buffering 关闭代理缓冲,让增量能立即刷出。 ---
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Content-Location": f"/threads/{thread_id}/runs/{run_id}",
            },
        )
        await response.prepare(request)

        # --- 5. 首个 SSE 帧:metadata(run id)——SDK 也会从 Content-Location
        #        读取,但显式发一帧更稳妥。 ---
        await response.write(_sse("metadata", {"run_id": run_id, "thread_id": thread_id}))

        # --- 6. 把 turn 交给框架。manager 循环会异步处理它,其流式事件经
        #        stream_events 回灌,靠塞进 context 的 run_id 做关联。此调用
        #        不会阻塞等待模型,立即返回。 ---
        await self._on_receive(
            ChannelMessage(
                session_id=thread_id,
                channel=self.name,
                content=user_text,
                chat_id="web",
                context={"run_id": run_id},
            )
        )

        # --- 7. 消费队列:每个 "delta" 追加到累积文本上,然后把完整状态快照
        #        (历史 + 正在增长的 AI 消息)作为 "values" 帧发出。_END(由
        #        stream_events 的 finally 推入)用于跳出循环。 ---
        assistant_content = ""
        try:
            while True:
                kind, value = await queue.get()
                if kind is _END:
                    break
                # kind == "delta"
                assistant_content += value
                snapshot = {
                    "messages": [
                        *messages,
                        {"type": "ai", "content": assistant_content, "id": ai_id},
                    ]
                }
                await response.write(_sse("values", snapshot, event_id=run_id))
        finally:
            # 无论如何都注销队列,避免崩溃/取消的 run 造成泄漏。
            self._streams.pop(run_id, None)

        # --- 8. 把完成的 AI 消息持久化进 thread 历史,再发出最终的 "values"
        #        帧和 "end" 帧来关闭这次 run。 ---
        messages.append({"type": "ai", "content": assistant_content, "id": ai_id})
        # AI 回复完成,持久化整段对话,后端重启后历史可恢复。
        self._save_threads()
        await response.write(_sse("values", {"messages": messages}, event_id=run_id))
        await response.write(_sse("end", None))
        await response.write_eof()
        return response

    # ------------------------------------------------------------------ #
    # Object shapes
    # ------------------------------------------------------------------ #
    def _thread_obj(self, thread_id: str) -> dict[str, Any]:
        messages = self._threads.get(thread_id, [])
        return {
            "thread_id": thread_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "metadata": {"graph_id": self.ASSISTANT_ID},
            "status": "idle",
            "values": {"messages": messages} if messages else None,
        }

    def _state_obj(self, thread_id: str) -> dict[str, Any]:
        messages = self._threads.get(thread_id, [])
        return {
            "values": {"messages": messages},
            "next": [],
            "checkpoint": {"thread_id": thread_id, "checkpoint_id": str(uuid.uuid4())},
            "metadata": {},
            "created_at": _now_iso(),
            "parent_checkpoint": None,
            "tasks": [],
        }

    def _assistant_obj(self) -> dict[str, Any]:
        return {
            "assistant_id": self.ASSISTANT_ID,
            "graph_id": self.ASSISTANT_ID,
            "name": "ApexTran",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "metadata": {},
            "version": 1,
            "config": {},
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _extract_input_text(body: dict[str, Any]) -> str:
    """Pull the user's text out of a LangGraph runs payload.

    The frontend posts ``{input: {messages: [{type:"human", content:"..."}]}}``
    (shapes vary slightly across SDK versions), so we probe defensively.
    """
    inp = body.get("input")
    if isinstance(inp, dict):
        msgs = inp.get("messages")
        if isinstance(msgs, list) and msgs:
            last = msgs[-1]
            if isinstance(last, dict):
                content = last.get("content", "")
                if isinstance(content, list):  # content blocks
                    return "".join(b.get("text", "") for b in content if isinstance(b, dict))
                return str(content)
    if isinstance(inp, str):
        return inp
    return ""
