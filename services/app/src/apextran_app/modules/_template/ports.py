"""The port(s) the service depends on — swap adapters without touching logic."""

from __future__ import annotations

from typing import Protocol

from .domain.models import Widget


class WidgetSource(Protocol):
    async def fetch_widgets(self) -> list[Widget]: ...
