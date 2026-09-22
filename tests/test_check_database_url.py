"""Tests for the DATABASE_URL preflight.

Regression cover for the misconfiguration that left the warehouse 72 days
stale: a session-pooler URI with a bare `postgres` username is rejected by
Supabase as a *password* failure, which points every diagnosis at the wrong
thing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_database_url import _check_pooler_username, _safe_target

POOLER = "aws-0-eu-west-1.pooler.supabase.com"


def test_bare_username_on_pooler_is_rejected():
    msg = _check_pooler_username("postgres", POOLER)
    assert msg is not None
    assert "project ref" in msg


def test_qualified_username_on_pooler_is_accepted():
    assert _check_pooler_username("postgres.dtxavwlqmefuhyphjikk", POOLER) is None


def test_direct_host_allows_bare_username():
    """Direct connections legitimately use plain `postgres`."""
    assert _check_pooler_username("postgres", "db.dtxavwlqmefuhyphjikk.supabase.co") is None


def test_safe_target_reports_username_but_never_the_password():
    target = _safe_target(
        f"postgresql+psycopg2://postgres.ref:sup3rs3cret@{POOLER}:5432/postgres"
    )
    assert "postgres.ref" in target
    assert "sup3rs3cret" not in target
