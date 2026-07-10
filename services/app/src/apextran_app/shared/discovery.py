"""Module auto-discovery.

Each module exposes a ``wiring.py`` with a module-level ``MODULE: ModuleSpec``.
``main`` (serve role) collects the routers; ``worker`` collects the jobs. Adding
a module needs no change here — just a new ``modules/<name>/wiring.py``.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter
from loguru import logger

from .scheduler import Scheduler


@dataclass(frozen=True)
class ModuleSpec:
    """What a module contributes to the service."""

    name: str
    router: APIRouter | None = None
    register_jobs: Callable[[Scheduler], None] | None = None


def discover_modules() -> list[ModuleSpec]:
    """Import every ``apextran_app.modules.<name>.wiring`` and collect its MODULE.

    Names starting with ``_`` (e.g. ``_template``) are skipped. Modules named in
    ``APP_DISABLED_MODULES`` are the gray switch — discovered but not loaded.
    """
    from apextran_app import modules as modules_pkg

    from ..config import get_settings

    disabled = get_settings().disabled_module_set
    specs: list[ModuleSpec] = []
    for info in pkgutil.iter_modules(modules_pkg.__path__):
        if info.name.startswith("_"):
            continue
        wiring = importlib.import_module(f"apextran_app.modules.{info.name}.wiring")
        spec = getattr(wiring, "MODULE", None)
        if not isinstance(spec, ModuleSpec):
            logger.warning("modules.{} has no MODULE: ModuleSpec — skipped", info.name)
            continue
        if spec.name in disabled:
            logger.info("module {} disabled via APP_DISABLED_MODULES — skipped", spec.name)
            continue
        specs.append(spec)
        logger.debug("discovered module: {}", spec.name)
    return specs
