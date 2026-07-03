"""Phase B: Codex OAuth wiring into the LangChain client.

Offline only — a fake JWT carrying ``chatgpt_account_id`` stands in for a real
Codex OAuth token. The live OAuth handshake (republic) is not exercised here.
"""

from __future__ import annotations

import base64
import json

from backend.agent.codex_oauth import (
    build_codex_headers,
    extract_codex_account_id,
    is_codex_token,
    resolve_codex_api_base,
)
from backend.agent.settings import AgentSettings
from backend.llm.client import build_chat_model


def _make_codex_jwt(account_id: str = "acct_123") -> str:
    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    header = b64({"alg": "none"})
    payload = b64({"https://api.openai.com/auth": {"chatgpt_account_id": account_id}})
    return f"{header}.{payload}.sig"


def test_codex_token_detection_and_headers() -> None:
    token = _make_codex_jwt("acct_xyz")
    assert is_codex_token(token)
    assert not is_codex_token("sk-a-normal-openai-key")
    assert not is_codex_token(None)
    assert extract_codex_account_id(token) == "acct_xyz"

    headers = build_codex_headers(token)
    assert headers["chatgpt-account-id"] == "acct_xyz"
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["originator"] == "codex_cli_rs"


def test_resolve_codex_api_base() -> None:
    assert resolve_codex_api_base() == "https://chatgpt.com/backend-api/codex"
    assert resolve_codex_api_base("https://x/backend-api/codex/responses") == "https://x/backend-api/codex"
    assert resolve_codex_api_base("https://x/backend-api") == "https://x/backend-api/codex"


def test_build_chat_model_uses_codex_backend() -> None:
    token = _make_codex_jwt("acct_1")
    settings = AgentSettings(model="openai:gpt-5-codex", api_key=token)

    model = build_chat_model(settings)

    assert model.use_responses_api is True
    assert str(model.openai_api_base).endswith("/codex")
    assert model.default_headers["chatgpt-account-id"] == "acct_1"
    assert model.openai_api_key.get_secret_value() == token


def test_build_chat_model_normal_openai_is_not_codex() -> None:
    settings = AgentSettings(model="openai:gpt-4o", api_key="sk-a-normal-openai-key")

    model = build_chat_model(settings)

    assert not getattr(model, "use_responses_api", None)
    assert "/codex" not in str(model.openai_api_base or "")
