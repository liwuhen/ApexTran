"""What the market module contributes to the service (router + jobs)."""

from __future__ import annotations

from ...shared.discovery import ModuleSpec
from .ingest import register_jobs
from .router import router

MODULE = ModuleSpec(name="market", router=router, register_jobs=register_jobs)
