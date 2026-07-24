"""Request/response shapes for the analysis module."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    context: dict[str, Any] | None = None
