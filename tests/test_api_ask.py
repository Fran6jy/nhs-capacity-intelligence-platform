"""HTTP-layer tests for /api/ask — the contract the React frontend depends on.

The database and the LLM are both stubbed, so these run in CI with no
DATABASE_URL and no API key.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.main import app
from src.llm import nl2sql


class _StubLLM:
    def invoke(self, messages):  # noqa: D102
        return type("R", (), {"content": "Waits are rising in Cardiology."})()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        nl2sql.db,
        "read_sql_readonly",
        lambda *a, **k: pd.DataFrame(
            [{"specialty_name": "Cardiology", "median_wait_days": 91.0}]
        ),
    )
    monkeypatch.setattr("src.llm.rag.get_llm", lambda: _StubLLM())
    return TestClient(app)


def test_ask_returns_curated_answer_with_auditable_sql(client):
    resp = client.post("/api/ask", json={"question": "why are waiting times rising?"})
    assert resp.status_code == 200

    body = resp.json()
    assert body["source"] == "curated"
    assert body["intent"] == "waiting_times"
    assert "median_wait_days" in body["sql"]  # the SQL is exposed for audit
    assert body["rows"][0]["specialty_name"] == "Cardiology"
    assert body["explanation"]


def test_ask_declines_rather_than_answering_a_different_question(client, monkeypatch):
    monkeypatch.setattr(nl2sql, "has_real_llm", lambda: False)

    resp = client.post("/api/ask", json={"question": "what is the capital of France"})
    assert resp.status_code == 200

    body = resp.json()
    assert body["source"] == "unanswerable"
    assert body["rows"] == []
    assert body["sql"] == ""
    assert "can answer questions about" in body["answer"]


def test_ask_rejects_an_empty_question(client, monkeypatch):
    monkeypatch.setattr(nl2sql, "has_real_llm", lambda: False)

    resp = client.post("/api/ask", json={"question": "   "})
    assert resp.json()["source"] == "unanswerable"


def test_health_reports_503_when_database_is_down(monkeypatch):
    def fail(*_a, **_k):
        raise RuntimeError("no database")

    monkeypatch.setattr("src.api.main.db.read_sql", fail)
    resp = TestClient(app, raise_server_exceptions=False).get("/api/health")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "database unavailable"


def test_api_key_guard_blocks_unauthenticated_calls(monkeypatch):
    """When API_KEY is set, /api/* requires the header but health stays open."""
    monkeypatch.setattr("src.api.main.settings.api_key", "s3cret")
    c = TestClient(app, raise_server_exceptions=False)

    assert c.post("/api/ask", json={"question": "beds"}).status_code == 401
    assert c.get("/api/health").status_code in (200, 503)  # exempt either way
