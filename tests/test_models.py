"""Smoke tests for the ML models (no real training — just shape checks)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_fact(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range(date(2025, 1, 1), periods=n, freq="D")
    return pd.DataFrame({
        "date_key": dates.repeat(2),
        "hospital_id": ["H1", "H2"] * n,
        "specialty_id": ["SP_GEN"] * (n * 2),
        "bed_occupancy_pct": np.clip(rng.normal(85, 7, n * 2), 50, 100),
        "median_wait_days": np.clip(rng.normal(20, 5, n * 2), 5, 60),
        "ae_attendances": rng.integers(80, 400, n * 2),
        "referrals": rng.integers(0, 60, n * 2),
        "vacancy_rate": np.clip(rng.normal(7, 3, n * 2), 0, 25),
        "flu_index": rng.normal(5, 2, n * 2),
        "covid_index": rng.normal(3, 1, n * 2),
        "avg_temp_c": rng.normal(10, 5, n * 2),
    })


def test_bed_occupancy_forecast_smoke():
    pytest.importorskip("prophet")
    from src.models.bed_occupancy import BedOccupancyForecaster
    df = _make_fact()
    m = BedOccupancyForecaster(horizon_days=30)
    m.fit(df)
    fc = m.forecast()
    assert (fc["date_key"].dt.date > df["date_key"].max().date()).sum() >= 28
    assert {"yhat", "yhat_lower", "yhat_upper"} <= set(fc.columns)


def test_waiting_time_forecast_smoke():
    pytest.importorskip("lightgbm")
    from src.models.waiting_time import WaitingTimeForecaster
    df = _make_fact(150)
    m = WaitingTimeForecaster(horizons=(7, 14))
    m.fit(df)
    out = m.predict(df, horizon=7)
    assert "pred_7d" in out.columns
    assert len(out) > 0


def test_ae_demand_forecast_smoke():
    pytest.importorskip("prophet")
    from src.models.ae_demand import AEDemandForecaster
    df = _make_fact(150)
    m = AEDemandForecaster(horizon_days=30)
    m.fit(df)
    fc = m.forecast()
    assert (fc["date_key"].dt.date > df["date_key"].max().date()).sum() >= 28
