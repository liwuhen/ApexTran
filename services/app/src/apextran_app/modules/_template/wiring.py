"""What this module contributes to the service. Discovery collects ``MODULE``."""

from __future__ import annotations

from ...shared.discovery import ModuleSpec
from .ingest import register_jobs
from .router import router

# Rename ``_template`` → your module name when you copy this. The leading ``_``
# is what keeps the template itself from ever mounting.
MODULE = ModuleSpec(name="_template", router=router, register_jobs=register_jobs)
