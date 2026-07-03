import json

import requests

from backend.agent.settings import FeishuSettings


def get_feishu_tenant_access_token(settings: FeishuSettings) -> str:
    """Fetch tenant_access_token via app_id/app_secret (no Bearer header on this endpoint)."""
    if not settings.app_id or not settings.app_secret:
        raise ValueError("ApexTran_FEISHU_APP_ID and ApexTran_FEISHU_APP_SECRET must be configured in .env")
    base = settings.base_url.rstrip("/")
    response = requests.post(
        f"{base}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": settings.app_id, "app_secret": settings.app_secret},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if int(data.get("code", -1)) != 0:
        raise RuntimeError(f"Failed to get Feishu tenant access token: {data.get('msg', data)}")
    token = str(data.get("tenant_access_token", ""))
    if not token:
        raise RuntimeError("Feishu tenant access token is empty")
    return token


def send_feishu_message(
    *,
    base: str,
    auth_headers: dict[str, str],
    chat_id: str,
    msg_type: str,
    content: dict,
) -> dict:
    response = requests.post(
        f"{base}/open-apis/im/v1/messages",
        headers={**auth_headers, "Content-Type": "application/json"},
        params={"receive_id_type": "chat_id"},
        json={
            "receive_id": chat_id,
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        },
        timeout=30,
    )
    response.raise_for_status()
    data: dict = response.json()
    if int(data.get("code", -1)) != 0:
        raise RuntimeError(f"Feishu send message failed: {data.get('msg', data)}")
    return data


def resolve_feishu_chat_id(settings: FeishuSettings, session_id: str) -> str:
    if ":" in session_id:
        channel, chat_id = session_id.split(":", 1)
        if channel == "feishu" and chat_id:
            return chat_id
    allow = settings.allow_chats or ""
    chat_ids = [cid.strip() for cid in allow.split(",") if cid.strip()]
    if chat_ids:
        return chat_ids[0]
    raise ValueError("cannot resolve Feishu chat_id from session_id or ApexTran_FEISHU_ALLOW_CHATS")
