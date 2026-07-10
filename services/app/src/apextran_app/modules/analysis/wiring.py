"""What the analysis module contributes (router only; no scheduled jobs)."""

from __future__ import annotations

from ...shared.discovery import ModuleSpec
from .router import router

MODULE = ModuleSpec(name="analysis", router=router)
