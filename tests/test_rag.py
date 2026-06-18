"""Tests for the NL→SQL safety validator and the LLM fallback."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.nl2sql import _heuristic_sql, _validate


def test_validator_rejects_dml():
    with pytest.raises(ValueError):
        _validate("DROP TABLE foo")


def test_validator_rejects_multi_statement():
    with pytest.raises(ValueError):
        _validate("SELECT 1; SELECT 2")


def test_validator_accepts_select_on_allowed_table():
    _validate("SELECT 1 FROM v_national_pressure LIMIT 1")


def test_validator_rejects_unknown_table():
    with pytest.raises(ValueError):
        _validate("SELECT * FROM secret_table LIMIT 1")


def test_heuristic_intents():
    assert "median_wait_days" in _heuristic_sql("Why are waiting times rising?")
    assert "ae_attendances" in _heuristic_sql("A&E surge last week?")
    assert "vacancy_rate" in _heuristic_sql("Staff vacancies in London")
    assert "bed_occupancy" in _heuristic_sql("bed occupancy trend")
    assert "risk_score" in _heuristic_sql("Which trusts are at risk of overload?")
