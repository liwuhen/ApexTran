"""Minimal in-process metrics — Prometheus text format, no extra dependency.

Deliberately tiny: a request counter and a latency histogram, rendered at
``GET /metrics`` for a Prometheus scrape. When we outgrow this (per-route
cardinality, exemplars, traces) the middleware is the single seam to swap in the
OpenTelemetry SDK — nothing else in the app touches timing.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

# Latency histogram buckets (seconds). Cumulative "le" semantics at render time.
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

# Keyed by (method, path_template, status).
_requests: dict[tuple[str, str, int], int] = defaultdict(int)
# Keyed by (method, path_template): [per-bucket counts..., +Inf], sum, count.
_hist_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * (len(_BUCKETS) + 1))
_hist_sum: dict[tuple[str, str], float] = defaultdict(float)


def _route(request: Request) -> str:
    """Template path (``/api/v1/market/{id}``) to keep label cardinality bounded."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def observe(method: str, route: str, status: int, elapsed: float) -> None:
    _requests[(method, route, status)] += 1
    counts = _hist_counts[(method, route)]
    for i, edge in enumerate(_BUCKETS):
        if elapsed <= edge:
            counts[i] += 1
    counts[-1] += 1  # +Inf bucket
    _hist_sum[(method, route)] += elapsed


async def metrics_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    observe(request.method, _route(request), response.status_code, time.perf_counter() - start)
    return response


def render() -> str:
    lines: list[str] = []
    lines.append("# TYPE app_requests_total counter")
    for (method, route, status), n in sorted(_requests.items()):
        lines.append(f'app_requests_total{{method="{method}",route="{route}",status="{status}"}} {n}')

    lines.append("# TYPE app_request_duration_seconds histogram")
    for (method, route), counts in sorted(_hist_counts.items()):
        cumulative = 0
        for i, edge in enumerate(_BUCKETS):
            cumulative += counts[i]
            lines.append(
                f'app_request_duration_seconds_bucket{{method="{method}",route="{route}",le="{edge}"}} {cumulative}'
            )
        total = counts[-1]
        lines.append(f'app_request_duration_seconds_bucket{{method="{method}",route="{route}",le="+Inf"}} {total}')
        lines.append(
            f'app_request_duration_seconds_sum{{method="{method}",route="{route}"}} {_hist_sum[(method, route)]}'
        )
        lines.append(f'app_request_duration_seconds_count{{method="{method}",route="{route}"}} {total}')
    return "\n".join(lines) + "\n"


def metrics_endpoint() -> Response:
    return PlainTextResponse(render(), media_type="text/plain; version=0.0.4")
