"""Tests for the national monthly forecaster: selection by back-test."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import monthly
from src.models.monthly import (
    BASELINE,
    CANDIDATES,
    MonthlySeries,
    backtest,
    forecast,
    run_all,
    seasonal_drift,
    seasonal_naive,
    series_from_tables,
)


def _seasonal_series(months: int = 60, seed: int = 3, trend: float = 4_000) -> pd.DataFrame:
    """Trend + strong annual cycle + noise: the shape of A&E attendances."""
    rng = np.random.default_rng(seed)
    periods = pd.period_range("2021-01", periods=months, freq="M").strftime("%Y-%m")
    t = np.arange(months)
    value = 2_000_000 + trend * t + 150_000 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 20_000, months)
    return pd.DataFrame({"period": periods, "value": value})


def test_seasonal_naive_repeats_last_year():
    assert list(seasonal_naive(np.arange(24.0), 3)) == [12.0, 13.0, 14.0]


def test_seasonal_drift_adds_the_year_on_year_change():
    y = np.concatenate([np.arange(12.0), np.arange(12.0) + 10])  # +10 every month y/y
    assert list(seasonal_drift(y, 2)) == [20.0, 21.0]


@pytest.mark.filterwarnings("ignore")
def test_backtest_scores_every_candidate_on_the_same_folds():
    pytest.importorskip("statsmodels")
    choice = backtest(MonthlySeries("x", _seasonal_series(), "u"))
    assert choice is not None
    assert choice.folds == monthly.N_FOLDS
    assert set(choice.candidates) >= {BASELINE, "drift", "seasonal_drift"}
    assert choice.model == min(choice.candidates, key=choice.candidates.get)
    assert choice.n_eval == monthly.N_FOLDS * monthly.HOLDOUT_MONTHS
    assert len(choice.residuals) == choice.n_eval


@pytest.mark.filterwarnings("ignore")
def test_a_trending_seasonal_series_is_won_by_a_trend_aware_model():
    """Seasonal naive misses the trend, so something that carries it must win."""
    pytest.importorskip("statsmodels")
    choice = backtest(MonthlySeries("x", _seasonal_series(), "u"))
    assert choice is not None
    assert choice.model != BASELINE
    assert choice.skill > 0, choice.candidates
    assert choice.mase < 1.0


@pytest.mark.filterwarnings("ignore")
def test_when_nothing_beats_the_naive_the_naive_is_the_forecast():
    """A pure annual cycle with no trend: the seasonal naive is near-optimal and
    skill must read ~0 rather than a model being forced to look clever."""
    pytest.importorskip("statsmodels")
    choice = backtest(MonthlySeries("x", _seasonal_series(trend=0, seed=11), "u"))
    assert choice is not None
    assert choice.skill < 0.35  # nobody beats the naive by much on a pure cycle
    fc = forecast(MonthlySeries("x", _seasonal_series(trend=0, seed=11), "u"), choice)
    assert fc["model"].iat[0] == choice.model


@pytest.mark.filterwarnings("ignore")
def test_forecast_is_twelve_months_with_ordered_band():
    pytest.importorskip("statsmodels")
    s = MonthlySeries("RTT waiting list", _seasonal_series(48), "pathways")
    choice = backtest(s)
    assert choice is not None
    fc = forecast(s, choice)
    assert len(fc) == monthly.HORIZON_MONTHS
    assert fc["period"].iat[0] == "2025-01"
    assert (fc["yhat_lower"] <= fc["yhat"]).all() and (fc["yhat"] <= fc["yhat_upper"]).all()
    assert fc["model"].iat[0] in CANDIDATES


def test_too_short_a_series_is_skipped_not_forecast():
    assert backtest(MonthlySeries("x", _seasonal_series(18), "")) is None


def test_series_from_tables_builds_six_national_series():
    ae = pd.DataFrame({
        "period": ["2026-07", "2026-07", "2026-08", "2026-08"],
        "org_code": ["A", "B", "A", "B"],
        "attendances": [100, 200, 110, 190],
        "breaches_4hr": [25, 50, 20, 40],
        "emergency_admissions": [30, 60, 33, 57],
    })
    ts = pd.DataFrame({
        "period": ["2026-06", "2026-07"],
        "total_waiting": [7_300_000, 7_328_252],
        "within_18_weeks_pct": [65.1, 65.4],
        "over_52_weeks": [115_000, 111_379],
    })
    series = series_from_tables(ae, ts)
    assert [s.target for s in series] == [
        "A&E attendances", "A&E four-hour performance", "Emergency admissions",
        "RTT waiting list", "RTT within 18 weeks", "RTT waiting 52+ weeks",
    ]
    fh = next(s for s in series if s.target == "A&E four-hour performance").frame
    assert fh["value"].iat[0] == 75.0


@pytest.mark.filterwarnings("ignore")
def test_run_all_names_the_winner_and_skips_short_series():
    pytest.importorskip("statsmodels")
    series = [MonthlySeries("A", _seasonal_series(48, 1), "u"), MonthlySeries("B", _seasonal_series(18, 2), "u")]
    fcs, mets = run_all(series)
    assert set(fcs["target"]) == {"A"}
    a = mets.set_index("target").loc["A"]
    assert a["model"] in CANDIDATES and a["candidates_tried"] >= 5
    assert mets.set_index("target").loc["B", "folds"] == 0
    assert "evaluated_at" in mets.columns
