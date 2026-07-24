"""M3 observability — /metrics exposes request counts + latency in Prom text."""

from __future__ import annotations

from apextran_app.main import create_app
from fastapi.testclient import TestClient

client = TestClient(create_app())


def test_metrics_counts_requests() -> None:
    client.get("/healthz")
    body = client.get("/metrics").text
    assert "app_requests_total" in body
    assert 'route="/healthz"' in body
    assert "app_request_duration_seconds_bucket" in body
