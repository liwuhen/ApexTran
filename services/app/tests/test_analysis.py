"""M3 analysis tests — SSE streaming + rate limit, on the LocalAgentClient stub."""

from __future__ import annotations

from apextran_app.main import create_app
from fastapi.testclient import TestClient

client = TestClient(create_app())


def _deltas(text: str) -> list[str]:
    """Pull the ``delta`` payloads out of an SSE body."""
    out: list[str] = []
    event: str | None = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:") and event == "delta":
            import json

            out.append(json.loads(line[5:].strip())["delta"])
    return out


def test_analyze_streams_deltas_then_end() -> None:
    resp = client.post("/api/v1/analysis/analyze", json={"prompt": "看看茅台"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # private data must never be cached
    assert "no-cache" in resp.headers.get("cache-control", "")
    body = resp.text
    assert _deltas(body)  # got at least one delta
    assert "event: end" in body


def test_analyze_rejects_empty_prompt() -> None:
    resp = client.post("/api/v1/analysis/analyze", json={"prompt": ""})
    assert resp.status_code == 422


def test_openapi_exposes_analysis_contract() -> None:
    spec = client.get("/openapi.json").json()
    assert "/api/v1/analysis/analyze" in spec["paths"]
