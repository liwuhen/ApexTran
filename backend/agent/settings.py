from __future__ import annotations

import os
import pathlib
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

DEFAULT_MODEL = "openrouter:qwen/qwen3-coder-next"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_HOME = pathlib.Path.home() / ".ApexTran"
DEFAULT_CONFIG_FILE = DEFAULT_HOME / "config.yml"


def provider_specific(setting_name: str) -> Callable[[], dict[str, str] | None]:
    def default_factory() -> dict[str, str] | None:
        setting_regex = re.compile(rf"^ApexTran_(.+)_{setting_name.upper()}$")
        loaded_env = os.environ
        result: dict[str, str] = {}
        for key, value in loaded_env.items():
            if value is None:
                continue
            if match := setting_regex.match(key):
                provider = match.group(1).lower()
                result[provider] = value
        return result or None

    return default_factory


class SQLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ApexTran_SQL_", extra="ignore", env_file=".env")
    host: str = Field(default="", description="host.")
    port: str = Field(default="", description="port.")
    user: str = Field(default="", description="user.")
    password: str = Field(default="", description="password.")
    dbname: str = Field(default="", description="dbname.")
    connect_timeout: int = Field(default=10, description="TCP connect timeout in seconds.")


class AgentSettings(BaseSettings):
    """Configuration settings for the Agent."""

    model_config = SettingsConfigDict(env_prefix="ApexTran_", env_parse_none_str="null", extra="ignore")
    home: pathlib.Path = Field(default=DEFAULT_HOME)
    model: str = DEFAULT_MODEL
    fallback_models: list[str] | None = None
    api_key: str | dict[str, str] | None = Field(default_factory=provider_specific("api_key"))
    api_base: str | dict[str, str] | None = Field(default_factory=provider_specific("api_base"))
    api_format: Literal["completion", "responses", "messages"] = "completion"
    max_steps: int = 50
    max_tokens: int = DEFAULT_MAX_TOKENS
    model_timeout_seconds: int | None = None
    client_args: dict[str, Any] | None = None
    verbose: int = Field(default=0, description="Verbosity level for logging. Higher means more verbose.", ge=0, le=2)

    @field_validator("home")
    @classmethod
    def _expand_home(cls, value: pathlib.Path) -> pathlib.Path:
        # Expand "~" (and env vars) so home-derived paths (tapes, logs, plugins,
        # history, config.yml) all resolve to the real directory.
        return pathlib.Path(os.path.expanduser(os.path.expandvars(str(value))))

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        home = os.path.expanduser(os.getenv("ApexTran_HOME", str(DEFAULT_HOME)))
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=pathlib.Path(home) / "config.yml"),
            file_secret_settings,
        )


class FeishuSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ApexTran_FEISHU_", extra="ignore", env_file=".env")

    app_id: str = Field(default="", description="Feishu app id.")
    app_secret: str = Field(default="", description="Feishu app secret.")
    base_url: str = Field(default="https://open.feishu.cn", description="Feishu OpenAPI base URL.")
    allow_users: str | None = Field(default=None, description="Comma-separated list of allowed Feishu sender open_ids.")
    allow_chats: str | None = Field(default=None, description="Comma-separated list of allowed Feishu chat_ids.")


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ApexTran_TELEGRAM_", extra="ignore", env_file=".env")

    token: str = Field(default="", description="Telegram bot token.")
    allow_users: str | None = Field(
        default=None, description="Comma-separated list of allowed Telegram user IDs, or empty for no restriction."
    )
    allow_chats: str | None = Field(
        default=None, description="Comma-separated list of allowed Telegram chat IDs, or empty for no restriction."
    )
    proxy: str | None = Field(
        default=None,
        description="Optional proxy URL for connecting to Telegram API, e.g. 'http://user:pass@host:port' or 'socks5://host:port'.",
    )


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ApexTran_Embedding_", extra="ignore", env_file=".env")
    model_name: str = Field(default="", description="model name.")
    api_key: str = Field(default="", description="api key.")


class ChannelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ApexTran_", extra="ignore", env_file=".env")

    enabled_channels: str = Field(
        default="all", description="Comma-separated list of enabled channels, or 'all' for all channels."
    )
    debounce_seconds: float = Field(
        default=1.0,
        description="Minimum seconds between processing two messages from the same channel to prevent overload.",
    )
    max_wait_seconds: float = Field(
        default=10.0,
        description="Maximum seconds to wait for processing before new messages reach the channel.",
    )
    active_time_window: float = Field(
        default=60.0,
        description="Time window in seconds to consider a channel active for processing messages.",
    )
    stream_output: bool = Field(default=False, description="Whether to stream model output to channels in real-time.")


@lru_cache(maxsize=1)
def load_settings() -> AgentSettings:
    return AgentSettings()
