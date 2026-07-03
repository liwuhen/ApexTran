"""LangChain chat-model factory — project-owned.

Builds a LangChain chat model from the configured ``provider:model``:

* ``anthropic`` → ``ChatAnthropic``
* everything else (openai, openrouter, deepseek, siliconflow, … all
  OpenAI-compatible) → ``ChatOpenAI`` with an optional ``api_base``

When the OpenAI api key is actually a Codex OAuth token, the client is pointed
at the ChatGPT Codex Responses backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from backend.agent.codex_oauth import (
    build_codex_headers,
    is_codex_token,
    resolve_codex_api_base,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from backend.agent.settings import AgentSettings


def _split_provider_model(value: str) -> tuple[str, str]:
    if ":" in value:
        provider, model = value.split(":", 1)
        return provider.strip().lower(), model.strip()
    return "openai", value.strip()


def _resolve_for_provider(value: str | dict[str, str] | None, provider: str) -> str | None:
    if isinstance(value, dict):
        return value.get(provider)
    return value


def build_chat_model(settings: AgentSettings, model: str | None = None) -> BaseChatModel:
    """Build a LangChain chat model from settings (+ optional ``provider:model`` override)."""
    provider, model_name = _split_provider_model(model or settings.model)
    api_key = _resolve_for_provider(settings.api_key, provider)
    api_base = _resolve_for_provider(settings.api_base, provider)

    common: dict[str, Any] = {"model": model_name, "max_tokens": settings.max_tokens}
    if settings.model_timeout_seconds is not None:
        common["timeout"] = settings.model_timeout_seconds

    if provider == "anthropic":
        anthropic_kwargs: dict[str, Any] = {"api_key": api_key or "none", **common}
        if api_base:
            anthropic_kwargs["base_url"] = api_base
        return ChatAnthropic(**anthropic_kwargs)

    if provider == "openai" and is_codex_token(api_key):
        token = api_key or ""
        return ChatOpenAI(
            api_key=SecretStr(token),
            base_url=resolve_codex_api_base(api_base),
            default_headers=build_codex_headers(token),
            use_responses_api=True,
            **common,
        )

    return ChatOpenAI(
        api_key=SecretStr(api_key or "none"),
        base_url=api_base,
        **common,
    )


__all__ = ["build_chat_model"]
