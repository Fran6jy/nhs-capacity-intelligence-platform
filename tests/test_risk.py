"""Unit tests for the composite risk engine."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.risk.risk_engine import _absolute_class, _classify, compute_risk


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


def test_absolute_class_thresholds():
    """The absolute overlay fires on hard safety limits, ignoring peers."""
    red = pd.Series({"bed_occupancy": 96.0, "vacancy_rate": 5.0, "ae_surge_index": 0.0})
    assert _absolute_class(red) == "Red"
    amber = pd.Series({"bed_occupancy": 93.0, "vacancy_rate": 5.0, "ae_surge_index": 0.0})
    assert _absolute_class(amber) == "Amber"
    green = pd.Series({"bed_occupancy": 85.0, "vacancy_rate": 5.0, "ae_surge_index": 0.0})
    assert _absolute_class(green) == "Green"
    # Vacancy alone can escalate, even with healthy occupancy.
    assert _absolute_class(
        pd.Series({"bed_occupancy": 80.0, "vacancy_rate": 16.0, "ae_surge_index": 0.0})
    ) == "Red"


def test_overlay_escalates_when_zscore_is_low():
    """A trust at 96% occupancy is Red via the absolute overlay even though its
    peer-relative score alone only reaches Amber."""
    df = pd.DataFrame({
        "hospital_id": ["H1", "H2", "H3", "H4"],
        "date_key": pd.to_datetime(["2025-06-01"] * 4),
        # H1 breaches the 95% ceiling; the rest sit just below it, so the
        # spread is small and H1's occupancy z-score is modest, not extreme.
        "bed_occupancy_pct": [96, 88, 89, 90],
        "waiting_list_size": [1000, 1000, 1000, 1000],
        "vacancy_rate": [5, 5, 5, 5],
        "ae_attendances": [200, 200, 200, 200],
    })
    out = compute_risk(df).set_index("hospital_id")
    # Peer-relative path alone would NOT call H1 Red …
    assert out.loc["H1", "classification_relative"] != "Red"
    # … but the absolute overlay does, and the final verdict takes the worse.
    assert out.loc["H1", "classification_absolute"] == "Red"
    assert out.loc["H1", "classification"] == "Red"


def test_final_class_is_worse_of_relative_and_absolute():
    """Final classification is never softer than either input verdict."""
    severity = {"Green": 0, "Amber": 1, "Red": 2}
    df = pd.DataFrame({
        "hospital_id": ["H1", "H2", "H3", "H4"],
        "date_key": pd.to_datetime(["2025-06-01"] * 4),
        "bed_occupancy_pct": [96, 70, 82, 91],
        "waiting_list_size": [1400, 800, 1000, 1200],
        "vacancy_rate": [16, 3, 7, 11],
        "ae_attendances": [420, 90, 180, 300],
    })
    out = compute_risk(df)
    for _, r in out.iterrows():
        assert severity[r["classification"]] >= severity[r["classification_relative"]]
        assert severity[r["classification"]] >= severity[r["classification_absolute"]]
