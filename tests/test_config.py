"""Tests for database URL resolution.

Hand percent-encoding a password into a URI is the step that broke the refresh
for 72 days, so the assembled-from-parts path is covered properly.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import resolve_database_url

PARTS = {
    "DB_HOST": "aws-0-eu-west-1.pooler.supabase.com",
    "DB_USER": "postgres.dtxavwlqmefuhyphjikk",
}


def _set(monkeypatch, **env):
    for key in ("DATABASE_URL", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_PORT", "DB_NAME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_explicit_database_url_wins(monkeypatch):
    _set(monkeypatch, DATABASE_URL="postgresql+psycopg2://u:p@h:5432/db", **PARTS)
    assert resolve_database_url() == "postgresql+psycopg2://u:p@h:5432/db"


def test_returns_none_without_enough_parts(monkeypatch):
    _set(monkeypatch, **PARTS)  # no password
    assert resolve_database_url() is None


def test_awkward_password_survives_a_round_trip(monkeypatch):
    """Every character that must be escaped in a URI userinfo field."""
    password = "p/a@ss:w%rd#1?x"
    _set(monkeypatch, DB_PASSWORD=password, **PARTS)

    url = resolve_database_url()
    assert url is not None
    parsed = urlparse(url)

    # The raw characters must not leak into the URI structure...
    assert parsed.hostname == PARTS["DB_HOST"]
    assert parsed.port == 5432
    assert parsed.username == PARTS["DB_USER"]
    # ...and must decode back to exactly what was supplied. `urlparse` returns
    # the raw encoded substring, so unquote it the way SQLAlchemy does.
    assert parsed.password is not None
    assert unquote(parsed.password) == password


def test_defaults_to_the_supabase_pooler_shape(monkeypatch):
    _set(monkeypatch, DB_PASSWORD="simple", **PARTS)
    url = resolve_database_url()
    assert url is not None
    assert url.startswith("postgresql+psycopg2://")
    assert url.endswith("/postgres?sslmode=require")
