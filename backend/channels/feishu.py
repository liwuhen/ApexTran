from __future__ import annotations

import asyncio
import contextlib
import json
from time import monotonic
from typing import Any, ClassVar

from aiohttp import ClientSession
from loguru import logger

from backend.agent.settings import FeishuSettings
from backend.channels.base import Channel
from backend.channels.message import ChannelMessage, MediaItem, MediaType
from backend.utils.types import MessageHandler

_MSG_TYPE_TO_MEDIA_TYPE: dict[str, MediaType] = {
    "image": "image",
    "post": "image",
}


class FeishuChannel(Channel):
    name = "feishu"
    _TOKEN_EXPIRE_SKEW_SECONDS: ClassVar[int] = 30

    def __init__(self, on_receive: MessageHandler) -> None:
        self._on_receive = on_receive
        self._settings = FeishuSettings()
        self._allow_users = {uid.strip() for uid in (self._settings.allow_users or "").split(",") if uid.strip()}
        self._allow_chats = {cid.strip() for cid in (self._settings.allow_chats or "").split(",") if cid.strip()}
        self._ws_task: asyncio.Task[None] | None = None
        self._ws_client: Any | None = None
        self._ws_ping_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._token_lock = asyncio.Lock()
        self._tenant_access_token: str | None = None
        self._tenant_access_token_expire_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._settings.app_id and self._settings.app_secret)

    @property
    def needs_debounce(self) -> bool:
        return True

    async def start(self, stop_event: asyncio.Event) -> None:
        # 在多协程环境中，get_running_loop() 返回的是同一个事件循环，因为所有协程都运行在同一个线程的同一个事件循环中
        self._loop = asyncio.get_running_loop()  # 记录当前异步事件循环对象
        self._ws_task = asyncio.create_task(self._run_websocket(stop_event))
        logger.info("feishu.start websocket mode enabled")

    async def stop(self) -> None:
        if self._ws_task is not None:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
        if self._ws_ping_task is not None:
            self._ws_ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_ping_task
            self._ws_ping_task = None
        if self._ws_client is not None:
            with contextlib.suppress(Exception):
                await self._ws_client._disconnect()
            self._ws_client = None
        logger.info("feishu.stopped")

    def _on_message(self, event: Any, lark: Any) -> None:
        loop = self._loop
        if loop is None:
            return
        payload_raw = lark.JSON.marshal(event)
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            logger.warning("feishu.websocket invalid event payload")
            return
        if not isinstance(payload, dict):
            return
        event_payload = payload.get("event")
        if not isinstance(event_payload, dict):
            return
        loop.call_soon_threadsafe(asyncio.create_task, self._build_message(event_payload))

    async def _run_websocket(self, stop_event: asyncio.Event) -> None:
        try:
            import lark_oapi as lark
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Feishu websocket mode requires dependency 'lark-oapi'. Install it with: uv add lark-oapi"
            ) from exc

        # 创建事件分发器（飞书 SDK 的事件路由器），注册消息接收事件处理器，收到飞书消息时，转调你自己的 _on_ws_message 方法处理。同时把 lark 传进去用于序列化 event
        event_handler = (
            lark.EventDispatcherHandler
            .builder("", "")  # 创建事件分发器（飞书 SDK 的事件路由器）
            .register_p2_im_message_receive_v1(lambda event: self._on_message(event, lark))  # 注册消息接收事件处理器
            .build()
        )  # 收到飞书消息时，转调你自己的 _on_ws_message 方法处理。同时把 lark 传进去用于序列化 event

        # 创建飞书长连接客户端。传入 app_id 和 app_secret 用于鉴权。把上面注册好的事件处理器挂上去。设置日志级别。
        self._ws_client = lark.ws.Client(
            self._settings.app_id,
            self._settings.app_secret,  # 创建飞书长连接客户端。传入 app_id 和 app_secret 用于鉴权。
            event_handler=event_handler,  # 把上面注册好的事件处理器挂上去。
            log_level=lark.LogLevel.INFO,  # 设置日志级别。
        )
        await self._ws_client._connect()  # 真正建立到飞书的 WS 连接（握手完成才继续）。
        self._ws_ping_task = asyncio.create_task(
            self._ws_client._ping_loop()
        )  # 启动心跳定时器，定期发送心跳包保持连接活跃。
        try:
            await stop_event.wait()  # 主协程在这里“挂起等待停机信号”，连接持续工作。
        finally:  # 无论正常退出、异常、取消，都会执行清理：
            if self._ws_ping_task is not None:  # 取消心跳定时器。
                self._ws_ping_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):  # 等待心跳定时器完成。
                    await self._ws_ping_task
                self._ws_ping_task = None
            if self._ws_client is not None:  # 断开 WS 连接。
                with contextlib.suppress(Exception):  # 等待 WS 连接断开。
                    await self._ws_client._disconnect()  # 断开 WS 连接。
                self._ws_client = None  # 清空客户端引用。

    async def send(self, message: ChannelMessage) -> None:
        text = self._extract_reply_text(message.content)
        if not text.strip():
            return
        await self._send_text(chat_id=message.chat_id, text=text)

    @staticmethod
    def _extract_reply_text(content: str) -> str:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(payload, dict):
            raw = payload.get("message", "")
            return str(raw) if raw is not None else ""
        return content

    @staticmethod
    def _extract_inbound_text(message_type: str, content: str) -> str:
        if not content:
            return ""
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(payload, dict) and message_type == "text":
            raw = payload.get("text", "")
            return str(raw) if raw is not None else ""
        elif isinstance(payload, dict) and message_type != "text":
            raw = payload.get("content", "")
            if raw:
                raw = raw[0][0]["text"]
            return str(raw) if raw is not None else ""
        return content

    @staticmethod
    def _json_dict(raw: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(payload, dict):
            return payload
        return {}

    @staticmethod
    def _extract_image_keys(message_type: str, content: str) -> list[str]:
        payload = FeishuChannel._json_dict(content)
        if message_type == "image":
            key = str(payload.get("image_key", "")).strip()
            return [key] if key else []
        if message_type != "post":
            return []
        keys: list[str] = []
        # post content format: {"content":[[{"tag":"img","image_key":"..."}], ...]}
        blocks = payload.get("content")
        if isinstance(blocks, list):
            for line in blocks:
                if not isinstance(line, list):
                    continue
                for item in line:
                    if not isinstance(item, dict):
                        continue
                    if item.get("tag") != "img":
                        continue
                    key = str(item.get("image_key", "")).strip()
                    if key:
                        keys.append(key)
        return keys

    def _extract_media_items(self, message_type: str, content: str, message_id: str) -> list[MediaItem]:
        media_type = _MSG_TYPE_TO_MEDIA_TYPE.get(message_type)
        if not media_type or not message_id:
            return []
        image_keys = self._extract_image_keys(message_type, content)
        if not image_keys:
            return []
        return [
            MediaItem(
                type=media_type,
                mime_type="image/jpeg",
                filename=image_key,
                data_fetcher=lambda key=image_key: self._download_message_resource(message_id, key, "image"),  # type: ignore[misc]
            )
            for image_key in image_keys
        ]

    async def _build_message(self, event: dict[str, Any]) -> None:
        message = event.get("message")
        if not isinstance(message, dict):
            return
        chat_id = str(message.get("chat_id", ""))  # chat_id 是飞书事件消息体里带过来的
        if not chat_id:
            return
        if self._allow_chats and chat_id not in self._allow_chats:
            return

        sender = event.get("sender")
        sender = sender if isinstance(sender, dict) else {}
        sender_id = sender.get("sender_id")
        sender_id = sender_id if isinstance(sender_id, dict) else {}
        sender_open_id = str(sender_id.get("open_id", ""))
        if self._allow_users and sender_open_id not in self._allow_users:
            return

        message_type = str(message.get("message_type", "text"))
        message_id = str(message.get("message_id", ""))
        content_raw = str(message.get("content", ""))
        text = ""
        media_items: list[MediaItem] = []
        if message_type == "text":  # 单文本消息
            text = self._extract_inbound_text(message_type, content_raw).strip()
            if not text:
                return
        elif message_type in {"image", "post"}:
            text = self._extract_inbound_text(message_type, content_raw).strip()
            media_items = self._extract_media_items(message_type, content_raw, message_id)
            if not media_items:
                return
        else:
            text = self._extract_inbound_text(message_type, content_raw).strip()

        # 飞书消息message: {'message_id': '', 'create_time': '', 'update_time': '', 'chat_id': '', 'chat_type': '', 'message_type': '', 'content': '{"text":"hello"}'}
        session_id = f"{self.name}:{chat_id}"  # session_id = channel:chat_id， eg: Feishu 消息：feishu:123456789
        if text.startswith("/"):
            inbound_content = text  # 逗号命令直接原样传给框架。
        else:
            inbound_content = json.dumps(  # 普通文本消息，包装成 JSON 格式。
                {
                    "message": text,
                    "message_id": str(message.get("message_id", "")),
                    "type": message_type,
                    "chat_id": chat_id,
                    "sender_id": sender_open_id,
                },
                ensure_ascii=False,
            )
        inbound = ChannelMessage(
            session_id=session_id,
            channel=self.name,
            chat_id=chat_id,
            content=inbound_content,
            is_active=True,
            media=media_items,
            output_channel=self.name,
        )
        await self._on_receive(inbound)

    async def _send_text(self, chat_id: str, text: str) -> None:
        token = await self._get_tenant_access_token()
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        response = await self._request_json(
            "POST",
            "/open-apis/im/v1/messages?receive_id_type=chat_id",
            headers={"Authorization": f"Bearer {token}"},
            payload=payload,
        )
        if int(response.get("code", -1)) != 0:
            msg = response.get("msg", "unknown error")
            raise RuntimeError(f"Failed to send Feishu message: {msg}")

    async def _get_tenant_access_token(self) -> str:
        now = monotonic()
        cached = self._tenant_access_token
        if cached and now < self._tenant_access_token_expire_at - self._TOKEN_EXPIRE_SKEW_SECONDS:
            return cached
        async with self._token_lock:
            now = monotonic()
            cached = self._tenant_access_token
            if cached and now < self._tenant_access_token_expire_at - self._TOKEN_EXPIRE_SKEW_SECONDS:
                return cached
            response = await self._request_json(
                "POST",
                "/open-apis/auth/v3/tenant_access_token/internal",
                payload={"app_id": self._settings.app_id, "app_secret": self._settings.app_secret},
            )
            if int(response.get("code", -1)) != 0:
                msg = response.get("msg", "unknown error")
                raise RuntimeError(f"Failed to get Feishu tenant access token: {msg}")
            token = str(response.get("tenant_access_token", ""))
            if not token:
                raise RuntimeError("Feishu tenant access token is empty.")
            expire = int(response.get("expire", 7200))
            self._tenant_access_token = token
            self._tenant_access_token_expire_at = monotonic() + expire
            return token

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._settings.base_url.rstrip('/')}{path}"
        req_headers = {"Content-Type": "application/json; charset=utf-8"}
        if headers:
            req_headers.update(headers)
        async with (
            ClientSession() as session,
            session.request(method, url, json=payload, headers=req_headers) as response,
        ):
            data = await response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected Feishu API response format.")  # noqa: TRY004 - API contract error, not a type error
        return data

    async def _download_message_resource(self, message_id: str, file_key: str, file_type: str) -> bytes:
        token = await self._get_tenant_access_token()
        path = f"/open-apis/im/v1/messages/{message_id}/resources/{file_key}"
        params = {"type": file_type}
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{self._settings.base_url.rstrip('/')}{path}"
        async with ClientSession() as session, session.get(url, params=params, headers=headers) as response:
            if response.status >= 400:
                body = await response.text()
                raise RuntimeError(f"Failed to download Feishu resource: status={response.status}, body={body}")
            return await response.read()
