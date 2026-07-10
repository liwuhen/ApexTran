"""HTTP surface — thin; delegates to the service. Rename the prefix per module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from .domain.models import Widget
from .provider import get_service
from .service import WidgetService

router = APIRouter(prefix="/api/v1/_template", tags=["_template"])

ServiceDep = Annotated[WidgetService, Depends(get_service)]


@router.get("/widgets")
async def list_widgets(service: ServiceDep) -> list[Widget]:
    return await service.list_widgets()
