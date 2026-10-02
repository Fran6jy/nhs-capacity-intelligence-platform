"""Tests for the national monthly forecaster on real-shaped series."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import monthly
from src.models.monthly import MonthlySeries, backtest, forecast, run_all, series_from_tables


def _seasonal_series(months: int = 60, seed: int = 3) -> pd.DataFrame:
    """Trend + strong annual cycle + noise: the shape of A&E attendances."""
    rng = np.random.default_rng(seed)
    periods = pd.period_range("2021-01", periods=months, freq="M").strftime("%Y-%m")
    t = np.arange(months)
    value = 2_000_000 + 4_000 * t + 150_000 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 20_000, months)
    return pd.DataFrame({"period": periods, "value": value})


def test_seasonal_naive_repeats_last_year():
    h = pd.Series(np.arange(24.0))
    out = monthly._seasonal_naive(h, 3)
    assert list(out) == [12.0, 13.0, 14.0]


@pytest.mark.filterwarnings("ignore")
def test_backtest_beats_seasonal_naive_on_a_clean_annual_cycle():
    pytest.importorskip("prophet")
    s = MonthlySeries("A&E attendances", _seasonal_series(), "attendances")
    metrics, resid = backtest(s)
    assert metrics["folds"] == monthly.N_FOLDS
    assert metrics["baseline"] == "seasonal_naive_12m"
    assert metrics["n_eval"] == monthly.N_FOLDS * monthly.HOLDOUT_MONTHS
    assert len(resid) == metrics["n_eval"]
    # Trend + seasonality is exactly what Prophet should capture better than
    # "same month last year", which misses the trend entirely.
    assert metrics["skill"] > 0, metrics
    assert metrics["mase"] < 1.0, metrics


@pytest.mark.filterwarnings("ignore")
def test_forecast_is_twelve_months_with_ordered_conformal_band():
    pytest.importorskip("prophet")
    s = MonthlySeries("RTT waiting list", _seasonal_series(48), "pathways")
    _, resid = backtest(s)
    fc = forecast(s, resid)
    assert len(fc) == monthly.HORIZON_MONTHS
    assert fc["period"].iat[0] == "2025-01"  # month after the 48-month history
    assert (fc["yhat_lower"] <= fc["yhat"]).all() and (fc["yhat"] <= fc["yhat_upper"]).all()
    assert (fc["yhat_upper"] - fc["yhat_lower"]).gt(0).all()


def test_too_short_a_series_is_skipped_not_forecast():
    short = MonthlySeries("x", _seasonal_series(18), "")
    metrics, _ = backtest(short)
    assert metrics["folds"] == 0
    with pytest.raises(ValueError, match="need"):
        forecast(short, pd.Series(dtype=float))


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
    assert fh["value"].iat[0] == 75.0  # (300-75)/300


@pytest.mark.filterwarnings("ignore")
def test_run_all_returns_forecasts_and_metrics_for_each_series():
    pytest.importorskip("prophet")
    series = [MonthlySeries("A", _seasonal_series(48, 1), "u"), MonthlySeries("B", _seasonal_series(18, 2), "u")]
    fcs, mets = run_all(series)
    assert set(fcs["target"]) == {"A"}  # B is too short and is skipped
    assert set(mets["target"]) == {"A", "B"}
    assert "evaluated_at" in mets.columns
