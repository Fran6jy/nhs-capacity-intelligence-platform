"""Unit tests for the composite risk engine."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.risk.risk_engine import _classify, compute_risk


def test_classify_thresholds():
    assert _classify(-0.5) == "Green"
    assert _classify(0.0) == "Amber"
    assert _classify(0.5) == "Amber"
    assert _classify(0.99) == "Amber"
    assert _classify(1.0) == "Red"
    assert _classify(3.0) == "Red"


def test_compute_risk_basic():
    df = pd.DataFrame({
        "hospital_id": ["H1", "H2", "H3", "H4"],
        "date_key": pd.to_datetime(["2025-06-01"] * 4),
        "bed_occupancy_pct": [95, 70, 80, 88],
        "waiting_list_size": [1000, 800, 1100, 1300],
        "vacancy_rate": [12, 4, 8, 14],
        "ae_attendances": [400, 100, 200, 350],
    })
    out = compute_risk(df)
    assert set(out["classification"].unique()) <= {"Green", "Amber", "Red"}
    # H4 has the worst combination → should be the highest-scored
    assert out.sort_values("score", ascending=False).iloc[0]["hospital_id"] == "H4"


def test_compute_risk_handles_missing_columns():
    df = pd.DataFrame({
        "hospital_id": ["H1", "H2"],
        "date_key": pd.to_datetime(["2025-06-01"] * 2),
        "bed_occupancy_pct": [80, 80],
        "waiting_list_size": [1000, 1000],
        "vacancy_rate": [5, 5],
        "ae_attendances": [100, 100],
    })
    out = compute_risk(df)
    assert len(out) == 2
