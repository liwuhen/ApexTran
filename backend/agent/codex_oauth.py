"""OpenAI Codex OAuth — project seam.

The PKCE login flow, token storage and refresh (``~/.codex/auth.json``) live in
``codex_oauth_flow`` (project-owned, authlib + stdlib) and are re-exported here so
call sites depend on this seam module.

The Codex *request* shaping (ChatGPT backend base URL, headers, account-id) is
also project-owned, so :mod:`backend.llm.client` can point a
LangChain ``ChatOpenAI`` at the Codex Responses backend.
"""

from __future__ import annotations

import base64
import json

# Project-owned OAuth flow (login / resolver / token storage), re-exported behind
# this seam; consumed by ``auth.py`` and :func:`codex_access_token`.
from backend.agent.codex_oauth_flow import (
    CodexOAuthLoginError,
    OpenAICodexOAuthTokens,
    load_openai_codex_oauth_tokens,
    login_openai_codex_oauth,
    openai_codex_oauth_resolver,
)

__all__ = [
    "CODEX_BASE_URL",
    "CODEX_ORIGINATOR",
    "CodexOAuthLoginError",
    "OpenAICodexOAuthTokens",
    "build_codex_headers",
    "codex_access_token",
    "extract_codex_account_id",
    "is_codex_token",
    "load_openai_codex_oauth_tokens",
    "login_openai_codex_oauth",
    "resolve_codex_api_base",
]

CODEX_BASE_URL = "https://chatgpt.com/backend-api"
CODEX_ORIGINATOR = "codex_cli_rs"
_CODEX_PROVIDER = "openai"


def extract_codex_account_id(access_token: str) -> str | None:
    """Decode the ``chatgpt_account_id`` claim from a Codex OAuth JWT access token."""
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    segment = parts[1]
    segment += "=" * (-len(segment) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    auth = payload.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        return None
    account_id = auth.get("chatgpt_account_id")
    if not isinstance(account_id, str):
        return None
    return account_id.strip() or None


def is_codex_token(access_token: str | None) -> bool:
    """A Codex OAuth access token is a JWT carrying a ``chatgpt_account_id``."""
    return access_token is not None and extract_codex_account_id(access_token) is not None


def resolve_codex_api_base(api_base: str | None = None) -> str:
    """Normalize the Codex Responses backend base URL (``.../backend-api/codex``)."""
    raw = (api_base or CODEX_BASE_URL).rstrip("/")
    if raw.endswith("/responses"):
        raw = raw[: -len("/responses")]
    return raw if raw.endswith("/codex") else f"{raw}/codex"


def build_codex_headers(access_token: str, *, originator: str = CODEX_ORIGINATOR) -> dict[str, str]:
    """Build the headers the Codex backend requires for an OAuth access token."""
    account_id = extract_codex_account_id(access_token)
    if account_id is None:
        raise ValueError("Codex OAuth token is missing chatgpt_account_id")
    return {
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": originator,
    }


def codex_access_token(codex_home: str | None = None) -> str | None:
    """Return a current Codex access token (auto-refreshing), or ``None`` if not logged in."""
    try:
        resolver = openai_codex_oauth_resolver(codex_home)
        return resolver(_CODEX_PROVIDER)
    except Exception:
        return None
