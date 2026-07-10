"""HTTP surface for analysis — private, streamed, rate-limited.

``POST /api/v1/analysis/analyze`` streams the model output as SSE ``delta``
frames then ``end``, proxying agent-service straight to the browser.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...config import get_settings
from ...shared.ratelimit import TokenBucket
from ...shared.security import get_user_id
from .provider import get_service
from .schemas import AnalyzeRequest
from .service import AnalysisService

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

# Per-user token bucket (process-local; Redis-backed in M4 for cross-replica).
_bucket = TokenBucket(get_settings().rate_limit_per_min)

ServiceDep = Annotated[AnalysisService, Depends(get_service)]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/analyze")
async def analyze(req: AnalyzeRequest, request: Request, service: ServiceDep) -> StreamingResponse:
    user = get_user_id(request)
    if not _bucket.allow(user):
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    async def gen() -> AsyncIterator[str]:
        async for delta in service.analyze_stream(prompt=req.prompt, context=req.context, user_id=user):
            yield _sse("delta", {"delta": delta})
        yield _sse("end", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
