"""Tests for the tiered NL→SQL router: validator, intent matching, refusal."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm import nl2sql
from src.llm.nl2sql import (
    MAX_ROWS,
    UnanswerableQuestion,
    answer_question,
    match_intent,
    validate_sql,
)


# --------------------------------------------------------------------------- #
# Validator
# --------------------------------------------------------------------------- #
def test_validator_rejects_dml():
    with pytest.raises(ValueError):
        validate_sql("DROP TABLE foo")


def test_validator_rejects_multi_statement():
    with pytest.raises(ValueError):
        validate_sql("SELECT 1 FROM risk_score; SELECT 2 FROM risk_score")


def test_validator_accepts_select_on_allowed_table():
    assert "v_national_pressure" in validate_sql("SELECT 1 FROM v_national_pressure LIMIT 1")


def test_validator_rejects_unknown_table():
    with pytest.raises(ValueError):
        validate_sql("SELECT * FROM secret_table LIMIT 1")


def test_validator_rejects_join_to_unlisted_table():
    """The allow-list is containment, not intersection.

    The previous validator passed this: it only required that *some*
    allow-listed name appear anywhere in the statement.
    """
    with pytest.raises(ValueError, match="not allow-listed"):
        validate_sql(
            "SELECT * FROM v_national_pressure v JOIN auth_users u ON true LIMIT 1"
        )


def test_validator_rejects_cross_schema_reference():
    with pytest.raises(ValueError, match="Cross-schema"):
        validate_sql("SELECT * FROM auth.users LIMIT 1")


def test_validator_rejects_comments():
    with pytest.raises(ValueError, match="Comments"):
        validate_sql("SELECT 1 FROM risk_score -- DROP TABLE risk_score")


def test_validator_allows_cte():
    sql = validate_sql(
        "WITH latest AS (SELECT MAX(date_key) AS d FROM risk_score) "
        "SELECT * FROM latest LIMIT 5"
    )
    assert "latest" in sql


def test_validator_tolerates_keyword_inside_string_literal():
    """`WHERE region_name = 'Created'` is legitimate and must not be rejected."""
    validate_sql("SELECT * FROM dim_region WHERE region_name = 'Created' LIMIT 1")


def test_row_cap_is_appended_when_missing():
    assert validate_sql("SELECT * FROM risk_score").endswith(f"LIMIT {MAX_ROWS}")


def test_row_cap_overrides_an_oversized_limit():
    out = validate_sql("SELECT * FROM risk_score LIMIT 100000")
    assert f"LIMIT {MAX_ROWS}" in out and "100000" not in out


# --------------------------------------------------------------------------- #
# Intent matching
# --------------------------------------------------------------------------- #
def test_intents_route_to_expected_queries():
    assert match_intent("Why are waiting times rising?").name == "waiting_times"
    assert match_intent("A&E surge last week?").name == "ae_demand"
    assert match_intent("Staff vacancies in London").name == "workforce"
    assert match_intent("bed occupancy trend").name == "capacity"
    assert match_intent("Which trusts are at risk of overload?").name == "risk"


def test_paediatric_does_not_route_to_ae():
    """Regression: the old matcher used `"ae" in question`, and "paediatric"
    contains the substring "ae"."""
    matched = match_intent("how many paediatric admissions last month")
    assert matched is None or matched.name != "ae_demand"


def test_unrelated_question_matches_no_intent():
    assert match_intent("what is the capital of France") is None


# --------------------------------------------------------------------------- #
# Routing and refusal
# --------------------------------------------------------------------------- #
def test_curated_tier_executes_reviewed_sql(monkeypatch):
    captured = {}

    def fake_read(sql, *_args, **_kwargs):
        captured["sql"] = sql
        return pd.DataFrame([{"specialty_name": "Cardiology", "median_wait_days": 91.0}])

    monkeypatch.setattr(nl2sql.db, "read_sql_readonly", fake_read)

    result = answer_question("why are waiting times so long?")
    assert result.source == "curated"
    assert result.intent == "waiting_times"
    assert "median_wait_days" in captured["sql"]


def test_refuses_instead_of_guessing_when_no_tier_applies(monkeypatch):
    """The old code returned the risk query for *any* unmatched question."""
    monkeypatch.setattr(nl2sql, "has_real_llm", lambda: False)

    with pytest.raises(UnanswerableQuestion) as exc:
        answer_question("what is the capital of France")
    assert "risk" not in str(exc.value).lower() or "I can't answer" in str(exc.value)


def test_generated_tier_validates_model_output(monkeypatch):
    """A model that emits an unlisted table must not reach the database."""
    monkeypatch.setattr(nl2sql, "has_real_llm", lambda: True)
    monkeypatch.setattr(
        nl2sql, "generate_sql", lambda q: ("SELECT * FROM pg_shadow", "leak")
    )

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("invalid generated SQL reached the database")

    monkeypatch.setattr(nl2sql.db, "read_sql_readonly", must_not_run)

    with pytest.raises(UnanswerableQuestion):
        answer_question("dump the credentials table")


def test_generated_tier_returns_model_sql(monkeypatch):
    monkeypatch.setattr(nl2sql, "has_real_llm", lambda: True)
    monkeypatch.setattr(
        nl2sql,
        "generate_sql",
        lambda q: ("SELECT region_name FROM dim_region LIMIT 5", "regions"),
    )
    monkeypatch.setattr(
        nl2sql.db, "read_sql_readonly", lambda *a, **k: pd.DataFrame([{"region_name": "London"}])
    )

    result = answer_question("list the distinct geographies covered")
    assert result.source == "generated"
    assert result.sql.startswith("SELECT region_name")
