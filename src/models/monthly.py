"""National monthly forecasts on real NHS England series.

This is the forecasting layer running on data NHS England actually
publishes — the monthly RTT waiting list back to 2007 and 36 months of A&E
activity — rather than on the synthetic daily fact table. Monthly grain is
the grain the data has, so nothing here implies a precision the source
cannot support.

Method
------
Prophet with yearly seasonality (legitimate here: the shortest series has
three annual cycles, the RTT series has nineteen), linear growth, and a
changepoint prior damped for slow-moving operational series. Every forecast
is back-tested on rolling origins against the **seasonal naive** — the same
month last year — which is the baseline that matters for annual-cycle data.
Skill is reported against it; a model that cannot beat "same month last year"
has no business issuing a 12-month outlook.

Prediction intervals are split-conformal from the back-test residuals, so they
are as wide as the model has actually been wrong, not as wide as a multiplier.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from prophet import Prophet

from src.models._common import bias_and_offsets, mase
from src.utils.logging import get_logger

log = get_logger("models.monthly")

SEASONAL_PERIOD = 12
HORIZON_MONTHS = 12
HOLDOUT_MONTHS = 6
N_FOLDS = 3
MIN_TRAIN_MONTHS = 24


@dataclass(frozen=True)
class MonthlySeries:
    """One national series to forecast: a label and a monthly frame."""

    target: str
    frame: pd.DataFrame  # columns: period (YYYY-MM), value
    unit: str = ""


def _to_prophet(frame: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "ds": pd.to_datetime(frame["period"] + "-01"),
        "y": pd.to_numeric(frame["value"], errors="coerce"),
    }).dropna().sort_values("ds").reset_index(drop=True)
    return df


def _fit(daily: pd.DataFrame) -> Prophet:
    m = Prophet(
        growth="linear",
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,
        seasonality_mode="additive",
    )
    m.fit(daily)
    return m


def _predict(model: Prophet, last: pd.Timestamp, months: int) -> pd.DataFrame:
    future = pd.DataFrame({"ds": pd.date_range(last + pd.offsets.MonthBegin(1), periods=months, freq="MS")})
    return model.predict(future)[["ds", "yhat", "yhat_lower", "yhat_upper"]]


def _seasonal_naive(history: pd.Series, horizon: int) -> np.ndarray:
    h = list(np.asarray(history, dtype=float))
    out = []
    for _ in range(horizon):
        out.append(h[-SEASONAL_PERIOD] if len(h) >= SEASONAL_PERIOD else h[-1])
        h.append(out[-1])
    return np.asarray(out)


def backtest(series: MonthlySeries) -> tuple[dict, pd.Series]:
    """Rolling-origin back-test; returns the metrics row and the pooled residuals."""
    df = _to_prophet(series.frame)
    rows, residuals = [], []
    n = len(df)
    for i in range(N_FOLDS, 0, -1):
        cut = n - i * HOLDOUT_MONTHS
        if cut < MIN_TRAIN_MONTHS:
            continue
        train, hold = df.iloc[:cut], df.iloc[cut:cut + HOLDOUT_MONTHS]
        if hold.empty:
            continue
        try:
            fc = _predict(_fit(train), train["ds"].iat[-1], len(hold))
        except Exception as exc:  # noqa: BLE001
            log.warning("monthly.fold_failed", target=series.target, error=str(exc))
            continue
        pred = fc["yhat"].values
        actual = hold["y"].values
        naive = _seasonal_naive(train["y"], len(hold))
        mae = float(np.mean(np.abs(actual - pred)))
        naive_mae = float(np.mean(np.abs(actual - naive)))
        rows.append({
            "mae": mae, "naive_mae": naive_mae,
            "mape": float(np.mean(np.abs((actual - pred) / np.where(actual == 0, np.nan, actual))) * 100),
            "mase": mase(actual, pred, train["y"].values, SEASONAL_PERIOD),
            "skill": 1 - mae / naive_mae if naive_mae else float("nan"),
            "n": len(hold),
        })
        residuals.extend((actual - pred).tolist())

    if not rows:
        return {"target": series.target, "model": "prophet", "folds": 0}, pd.Series(dtype=float)
    r = pd.DataFrame(rows)
    metrics = {
        "target": series.target, "model": "prophet", "folds": len(r),
        "horizon_months": HOLDOUT_MONTHS, "unit": series.unit,
        "mae": round(float(r["mae"].mean()), 3),
        "mae_std": round(float(r["mae"].std()), 3) if len(r) > 1 else None,
        "mape": round(float(r["mape"].mean()), 3),
        "mase": round(float(r["mase"].mean()), 3),
        "baseline": "seasonal_naive_12m",
        "baseline_mae": round(float(r["naive_mae"].mean()), 3),
        "skill": round(float(r["skill"].mean()), 3),
        "n_eval": int(r["n"].sum()),
    }
    return metrics, pd.Series(residuals, dtype=float)


def forecast(series: MonthlySeries, residuals: pd.Series) -> pd.DataFrame:
    """Twelve-month forecast with conformal intervals from the back-test residuals."""
    df = _to_prophet(series.frame)
    if len(df) < MIN_TRAIN_MONTHS:
        raise ValueError(f"{series.target}: need {MIN_TRAIN_MONTHS} months, have {len(df)}")
    fc = _predict(_fit(df), df["ds"].iat[-1], HORIZON_MONTHS)
    bias, lo, hi = bias_and_offsets(residuals.values, level=0.8)
    fc["yhat"] = fc["yhat"] + bias
    if np.isfinite(lo) and np.isfinite(hi):
        fc["yhat_lower"], fc["yhat_upper"] = fc["yhat"] + lo, fc["yhat"] + hi
    out = pd.DataFrame({
        "target": series.target,
        "period": fc["ds"].dt.strftime("%Y-%m"),
        "yhat": fc["yhat"].round(2),
        "yhat_lower": fc["yhat_lower"].round(2),
        "yhat_upper": fc["yhat_upper"].round(2),
        "model": "prophet",
        "unit": series.unit,
    })
    return out


def run_all(series_list: list[MonthlySeries]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Back-test and forecast every series; returns (forecasts, metrics)."""
    fcs, mets = [], []
    for s in series_list:
        metrics, resid = backtest(s)
        mets.append(metrics)
        if metrics.get("folds", 0) == 0:
            log.warning("monthly.skipped", target=s.target, months=len(s.frame))
            continue
        try:
            fcs.append(forecast(s, resid))
        except Exception as exc:  # noqa: BLE001
            log.warning("monthly.forecast_failed", target=s.target, error=str(exc))
        log.info("monthly.result", target=s.target, skill=metrics["skill"],
                 mase=metrics["mase"], folds=metrics["folds"])
    forecasts = pd.concat(fcs, ignore_index=True) if fcs else pd.DataFrame(
        columns=["target", "period", "yhat", "yhat_lower", "yhat_upper", "model", "unit"])
    metrics_df = pd.DataFrame(mets)
    metrics_df["evaluated_at"] = pd.Timestamp.utcnow().tz_localize(None)
    return forecasts, metrics_df


# --------------------------------------------------------------------------- #
# Series builders from the ingested tables
# --------------------------------------------------------------------------- #
def series_from_tables(ae_monthly: pd.DataFrame, rtt_timeseries: pd.DataFrame) -> list[MonthlySeries]:
    """National series from the provider-level A&E table and the RTT time series."""
    out: list[MonthlySeries] = []
    if not ae_monthly.empty:
        nat = ae_monthly.groupby("period", as_index=False).agg(
            attendances=("attendances", "sum"), breaches=("breaches_4hr", "sum"),
            admissions=("emergency_admissions", "sum"))
        nat["four_hour_pct"] = ((1 - nat["breaches"] / nat["attendances"]) * 100).round(2)
        out += [
            MonthlySeries("A&E attendances", nat[["period"]].assign(value=nat["attendances"]), "attendances"),
            MonthlySeries("A&E four-hour performance", nat[["period"]].assign(value=nat["four_hour_pct"]), "%"),
            MonthlySeries("Emergency admissions", nat[["period"]].assign(value=nat["admissions"]), "admissions"),
        ]
    if not rtt_timeseries.empty:
        ts = rtt_timeseries
        out += [
            MonthlySeries("RTT waiting list", ts[["period"]].assign(value=ts["total_waiting"].astype(float)), "pathways"),
            MonthlySeries("RTT within 18 weeks", ts[["period"]].assign(value=ts["within_18_weeks_pct"]), "%"),
            MonthlySeries("RTT waiting 52+ weeks", ts[["period"]].assign(value=ts["over_52_weeks"].astype(float)), "pathways"),
        ]
    return out
