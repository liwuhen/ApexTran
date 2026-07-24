"""The wire shapes this module exposes. Replace with your real domain."""

from __future__ import annotations

from pydantic import BaseModel


class Widget(BaseModel):
    id: str
    label: str
