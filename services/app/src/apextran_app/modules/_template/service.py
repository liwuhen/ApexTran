"""Application logic — orchestrates ports; no framework imports here."""

from __future__ import annotations

from .domain.models import Widget
from .ports import WidgetSource


class WidgetService:
    def __init__(self, source: WidgetSource) -> None:
        self._source = source

    async def list_widgets(self) -> list[Widget]:
        return await self._source.fetch_widgets()

    async def refresh(self) -> None:
        # Example worker job: warm a cache, precompute, sync upstream, ...
        await self._source.fetch_widgets()
