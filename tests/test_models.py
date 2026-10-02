"""Correctness tests for the forecasting layer.

The previous tests were shape checks only, which is exactly why three bugs
survived: lags computed across rows instead of days, rolling windows that
leaked the target, and yearly seasonality fitted to six months. Each of those
is pinned here.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models._common import (
    conformal_offsets,
    daily_features,
    expanding_time_folds,
    features_for_date,
    mase,
    seasonal_naive,
    yearly_seasonality_for,
)


def _fact(n_days: int = 200, hospitals: int = 3, specialties: int = 2, seed: int = 42) -> pd.DataFrame:
    """Multi-row-per-day fact table with real weekly structure in every series."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(date(2025, 1, 1), periods=n_days, freq="D")
    rows = []
    for i, d in enumerate(dates):
        weekly = 4 * np.sin(2 * np.pi * i / 7)
        for h in range(hospitals):
            for s in range(specialties):
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


# --------------------------------------------------------------------------- #
# Feature construction
# --------------------------------------------------------------------------- #
def test_lags_are_days_not_rows():
    """Regression: on a multi-row-per-day frame, an ungrouped shift returns the
    previous *row*. Features must be built on the daily series instead."""
    daily = pd.DataFrame({"ds": pd.date_range("2025-01-01", periods=40), "y": np.arange(40.0)})
    f = daily_features(daily)
    assert f.loc[10, "lag1"] == 9.0
    assert f.loc[10, "lag7"] == 3.0
    assert np.isnan(f.loc[5, "lag7"])


def test_rolling_window_excludes_the_current_day():
    """Regression: an unshifted rolling mean contains y_t — target leakage for a
    model whose label is a function of y_t."""
    daily = pd.DataFrame({"ds": pd.date_range("2025-01-01", periods=40), "y": np.arange(40.0)})
    f = daily_features(daily)
    assert f.loc[10, "roll7"] == np.mean(np.arange(3, 10))  # days 3..9, never day 10
    assert f.loc[1, "roll7"] == 0.0  # only day 0 is before it


def test_future_features_use_forecasts_recursively():
    history = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2025-01-01", periods=3))
    row = features_for_date(history, pd.Timestamp("2025-01-04"))
    assert row["lag1"] == 3.0
    assert row["roll7"] == 2.0  # mean of all three prior days


def test_yearly_seasonality_requires_two_years():
    assert yearly_seasonality_for(pd.date_range("2025-01-01", periods=180)) is False
    assert yearly_seasonality_for(pd.date_range("2023-01-01", periods=800)) is True


def test_time_folds_train_strictly_before_validation():
    folds = list(expanding_time_folds(200, n_folds=3, min_train=60))
    assert len(folds) == 3
    for train, val in folds:
        assert train.stop == val.start
    assert folds[-1][1].stop == 200


def test_conformal_offsets_bracket_the_level():
    r = np.random.default_rng(0).normal(0, 1, 2000)
    lo, hi = conformal_offsets(r, level=0.8)
    assert -1.4 < lo < -1.15 and 1.15 < hi < 1.4


def test_seasonal_naive_repeats_last_week():
    h = pd.Series(np.arange(14.0))
    assert list(seasonal_naive(h, 3, period=7)) == [7.0, 8.0, 9.0]


def test_mase_is_one_for_the_naive_itself():
    ins = np.arange(50.0) + np.tile([0, 1, 0, 2, 0, 1, 0], 8)[:50]
    actual = ins[7:]
    assert mase(actual, ins[:-7], ins, period=7) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def test_bed_occupancy_learns_weekly_structure():
    """On a series with clear weekly seasonality the hybrid must beat a
    last-value baseline on a held-out month. Shape alone is not evidence."""
    pytest.importorskip("prophet")
    from src.models.bed_occupancy import BedOccupancyForecaster

    df = _fact(220)
    daily = BedOccupancyForecaster.national_daily(df, "bed_occupancy_pct")
    train, hold = daily.iloc[:-30], daily.iloc[-30:]

    m = BedOccupancyForecaster(horizon_days=30)
    m.fit(df[df["date_key"] <= train["ds"].max()])
    fc = m.forecast()
    assert len(fc) == 30
    assert (fc["yhat_lower"] <= fc["yhat"]).all() and (fc["yhat"] <= fc["yhat_upper"]).all()

    model_mae = np.mean(np.abs(fc["yhat"].values - hold["y"].values))
    naive_mae = np.mean(np.abs(train["y"].iloc[-1] - hold["y"].values))
    assert model_mae < naive_mae
    assert m.yearly_seasonality is False  # 190 days of history


def test_waiting_time_predicts_with_calibrated_band():
    pytest.importorskip("lightgbm")
    from src.models.waiting_time import WaitingTimeForecaster

    df = _fact(150)
    m = WaitingTimeForecaster(horizons=(7,))
    m.fit(df)
    out = m.predict(df, horizon=7)
    assert {"pred_7d", "pred_7d_lower", "pred_7d_upper"} <= set(out.columns)
    assert (out["pred_7d_lower"] <= out["pred_7d_upper"]).all()
    assert 7 in m._offsets and np.isfinite(m._offsets[7][0])


def test_ae_demand_forecast_only_covers_the_future():
    pytest.importorskip("prophet")
    from src.models.ae_demand import AEDemandForecaster

    df = _fact(150)
    m = AEDemandForecaster(horizon_days=30)
    m.fit(df)
    fc = m.forecast()
    assert len(fc) == 30
    assert (fc["date_key"] > df["date_key"].max()).all()


def test_vacancy_rate_forecast_is_a_time_series_model():
    """Regression: the old workforce 'forecast' fit and predicted on a single
    snapshot and returned its own input."""
    pytest.importorskip("prophet")
    from src.models.workforce_demand import VacancyRateForecaster

    df = _fact(150)
    m = VacancyRateForecaster(horizon_days=30)
    m.fit(df)
    fc = m.forecast()
    assert len(fc) == 30
    assert (fc["date_key"] > df["date_key"].max()).all()
    assert fc["yhat"].std() > 0 or fc["yhat"].iloc[-1] != fc["yhat"].iloc[0]
