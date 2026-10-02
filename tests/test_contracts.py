"""Tests for the silver → gold data contracts.

Each test feeds a frame that used to flow through silently and asserts it is
now refused by name.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline import contracts
from src.pipeline.contracts import ContractViolation, validate, validate_fact_integrity


def _fact_row(**overrides) -> dict:
    row = {
        "activity_id": 1, "date_key": date(2026, 1, 1), "hospital_id": "H1",
        "specialty_id": "S1", "region_id": "R1", "admissions": 10, "discharges": 9,
        "bed_occupancy_pct": 88.0, "bed_occupancy_count": 440, "waiting_list_size": 1200,
        "median_wait_days": 21.0, "staff_count": 900, "vacancies": 80, "vacancy_rate": 8.9,
        "ae_attendances": 300, "referrals": 40, "flu_index": 4.0, "covid_index": 2.0,
        "avg_temp_c": 9.5,
    }
    row.update(overrides)
    return row


def test_valid_fact_passes():
    df = pd.DataFrame([_fact_row(), _fact_row(activity_id=2, hospital_id="H2")])
    out = validate(df, contracts.GOLD_FACT)
    assert len(out) == 2


def test_impossible_occupancy_is_refused():
    df = pd.DataFrame([_fact_row(bed_occupancy_pct=240.0)])
    with pytest.raises(ContractViolation, match="bed_occupancy_pct"):
        validate(df, contracts.GOLD_FACT)


def test_negative_wait_is_refused():
    df = pd.DataFrame([_fact_row(median_wait_days=-3.0)])
    with pytest.raises(ContractViolation, match="median_wait_days"):
        validate(df, contracts.GOLD_FACT)


def test_duplicate_grain_is_refused():
    """Two rows for the same date × hospital × specialty would double-count."""
    df = pd.DataFrame([_fact_row(), _fact_row(activity_id=2)])
    with pytest.raises(ContractViolation):
        validate(df, contracts.GOLD_FACT)


def test_missing_key_is_refused():
    df = pd.DataFrame([_fact_row(hospital_id=None)])
    with pytest.raises(ContractViolation, match="hospital_id"):
        validate(df, contracts.GOLD_FACT)


def test_all_failures_are_reported_together():
    """lazy=True: one run names every problem, not just the first."""
    df = pd.DataFrame([_fact_row(bed_occupancy_pct=240.0, median_wait_days=-3.0)])
    with pytest.raises(ContractViolation) as exc:
        validate(df, contracts.GOLD_FACT)
    assert "bed_occupancy_pct" in str(exc.value) and "median_wait_days" in str(exc.value)


def test_fact_must_join_to_its_dimensions():
    fact = pd.DataFrame([_fact_row(), _fact_row(activity_id=2, hospital_id="GHOST")])
    dim_h = pd.DataFrame({"hospital_id": ["H1"]})
    dim_s = pd.DataFrame({"specialty_id": ["S1"]})
    dim_r = pd.DataFrame({"region_id": ["R1"]})
    with pytest.raises(ContractViolation, match="GHOST"):
        validate_fact_integrity(fact, dim_h, dim_s, dim_r)


def test_silver_hes_rejects_bad_trust_code():
    df = pd.DataFrame({
        "trust_code": ["bad code!"], "specialty": ["S1"],
        "date": pd.to_datetime(["2026-01-01"]), "admissions": [1], "discharges": [1],
        "bed_occupancy_count": [1], "ae_attendances": [1], "referrals": [1],
    })
    with pytest.raises(ContractViolation, match="trust_code"):
        validate(df, contracts.SILVER_HES)


def test_silver_workforce_rejects_vacancy_rate_over_fifty():
    df = pd.DataFrame({
        "trust_code": ["RJE"], "role": ["Nursing"], "staff_count": [100.0],
        "vacancies": [60.0], "vacancy_rate": [60.0],
    })
    with pytest.raises(ContractViolation, match="vacancy_rate"):
        validate(df, contracts.SILVER_WORKFORCE)
