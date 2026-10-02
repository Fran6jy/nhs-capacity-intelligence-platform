"""Tests for the rolling-origin back-test.

The point of these is not that the models are good; it is that the numbers
reported about them are honest — several folds, a real baseline, and a skill
figure that goes negative when the model deserves it.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import validation
from src.models.validation import _best_baseline, _fold_row, backtest


def _fact(n_days: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(date(2025, 1, 1), periods=n_days, freq="D")
    rows = []
    for i, d in enumerate(dates):
        weekly = 4 * np.sin(2 * np.pi * i / 7)
        for h in range(3):
            for s in range(2):
                rows.append({
                    "date_key": d, "hospital_id": f"H{h}", "specialty_id": f"S{s}",
                    "bed_occupancy_pct": 85 + weekly + 0.01 * i + rng.normal(0, 1),
                    "median_wait_days": 20 + weekly / 2 + 0.02 * i + rng.normal(0, 0.5),
                    "ae_attendances": int(200 + 20 * weekly + rng.normal(0, 5)),
                    "referrals": int(rng.integers(0, 60)),
                    "vacancy_rate": 8 + 0.005 * i + rng.normal(0, 0.3),
                    "flu_index": 5.0, "covid_index": 3.0, "avg_temp_c": 10.0,
                })
    return pd.DataFrame(rows)


def test_best_baseline_picks_the_stronger_trivial_forecast():
    # Strong weekly pattern: seasonal naive should win over last value.
    hist = pd.Series(np.tile([10, 12, 14, 16, 14, 12, 10], 8).astype(float))
    actual = np.tile([10, 12, 14, 16, 14, 12, 10], 2).astype(float)
    name, pred, mae = _best_baseline(hist, actual, 14)
    assert name == "seasonal_naive"
    assert mae == pytest.approx(0.0)
    assert len(pred) == 14


def test_skill_is_negative_when_the_model_is_worse_than_the_baseline():
    actual = np.array([10.0, 10.0, 10.0, 10.0])
    worse = np.array([13.0, 13.0, 13.0, 13.0])
    row = _fold_row("x", "m", 0, actual, worse, np.arange(20.0), "last_value", baseline_mae=1.0)
    assert row["skill"] < 0
    assert row["mae"] == pytest.approx(3.0)


@pytest.mark.filterwarnings("ignore")
def test_backtest_reports_folds_baselines_and_skill():
    pytest.importorskip("prophet")
    pytest.importorskip("lightgbm")

    metrics, series = backtest(_fact())

    assert set(metrics["target"]) == {"Capacity pressure", "A&E demand", "Vacancy rate", "Waiting time"}
    assert set(validation.METRIC_COLUMNS) <= set(metrics.columns)

    national = metrics[metrics["target"] != "Waiting time"]
    assert (national["folds"] == validation.N_FOLDS).all()
    assert national["baseline"].isin(["seasonal_naive", "last_value"]).all()
    assert national["skill"].notna().all() and national["mase"].notna().all()

    panel = metrics[metrics["target"] == "Waiting time"].iloc[0]
    assert panel["baseline"] == "persistence"
    assert panel["folds"] >= 1

    # The point of the back-test is honest reporting, not a guaranteed win:
    # every skill must be a real, bounded comparison against a non-trivial
    # baseline error. (Whether a given model *deserves* a positive skill on
    # this series is exactly what the number is for — asserting it would
    # defeat the test.) Prophet on a clean weekly A&E signal should win, though.
    assert national["skill"].between(-1.0, 1.0).all()
    assert (national["baseline_mae"] > 0).all()
    ae = national[national["target"] == "A&E demand"].iloc[0]
    assert ae["skill"] > 0 and ae["mase"] < 1.0, ae.to_dict()

    assert {"target", "date", "actual", "predicted", "baseline"} <= set(series.columns)
    assert series["target"].nunique() == 3
    assert (series.groupby("target").size() == validation.HOLDOUT_DAYS).all()


def test_metrics_do_not_contain_the_old_accuracy_grade():
    """'accuracy = 100 - MAPE' is gone: it read like a grade and meant nothing."""
    assert "accuracy" not in validation.METRIC_COLUMNS
