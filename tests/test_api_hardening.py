"""HTTP-layer tests for the production hardening: request IDs, latency
headers, and the rate limit on the one endpoint that spends money."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import main
from src.api.main import _TokenBucket, app
from src.llm import nl2sql


class _StubLLM:
    def invoke(self, messages):  # noqa: D102
        return type("R", (), {"content": "ok"})()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        nl2sql.db, "read_sql_readonly",
        lambda *a, **k: pd.DataFrame([{"specialty_name": "Cardiology", "median_wait_days": 1.0}]),
    )
    monkeypatch.setattr("src.llm.rag.get_llm", lambda: _StubLLM())
    monkeypatch.setattr(main, "ask_limiter", _TokenBucket(per_minute=3))
    return TestClient(app, raise_server_exceptions=False)


def test_every_response_carries_a_request_id_and_timing(client):
    resp = client.get("/api/validation/sources")
    assert resp.status_code == 200
    assert len(resp.headers["X-Request-ID"]) >= 8
    assert resp.headers["Server-Timing"].startswith("app;dur=")


def test_client_supplied_request_id_is_echoed(client):
    resp = client.get("/api/validation/sources", headers={"X-Request-ID": "trace-abc123"})
    assert resp.headers["X-Request-ID"] == "trace-abc123"


def test_ask_is_rate_limited_per_client(client):
    body = {"question": "why are waiting times rising?"}
    for _ in range(3):
        assert client.post("/api/ask", json=body).status_code == 200
    blocked = client.post("/api/ask", json=body)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert "per minute" in blocked.json()["detail"]


def test_rate_limit_does_not_touch_read_endpoints(client):
    for _ in range(6):
        assert client.get("/api/validation/sources").status_code == 200


def test_token_bucket_window_slides():
    bucket = _TokenBucket(per_minute=2)
    assert bucket.allow("c", now=0.0) and bucket.allow("c", now=1.0)
    assert not bucket.allow("c", now=2.0)
    assert bucket.allow("c", now=61.0)  # first hit has aged out
