"""Composition — build the singleton service from config (single seam)."""

from __future__ import annotations

from functools import lru_cache

from .adapters import MockWidgetSource
from .service import WidgetService


@lru_cache
def get_service() -> WidgetService:
    return WidgetService(source=MockWidgetSource())
