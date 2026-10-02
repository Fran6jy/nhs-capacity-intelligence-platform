"""National monthly forecasts on real NHS England series, chosen by back-test.

The first version of this module fitted Prophet to every series and reported
negative skill on all six against "same month last year" — on the RTT waiting
list, skill −5.5, because a linear trend fitted across the 2020 regime break
extrapolates it. A single model for every series was the mistake.

Each series is now forecast by whichever candidate has the lowest error on
identical rolling-origin folds. The candidates span the methods that actually
win on operational series — seasonal naive, drift, seasonal drift, damped
Holt-Winters, Theta, and Prophet on the recent regime only — and the chosen
model is named in the metrics and on the page. If nothing beats the seasonal
naive, the seasonal naive *is* the forecast and the skill reads zero. That is
the honest outcome, and it is far better than a confident curve from a model
that lost the back-test.

Prediction intervals are split-conformal from the winner's pooled fold
residuals, so they are as wide as that model has actually been wrong.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.models._common import bias_and_offsets, mase
from src.utils.logging import get_logger

log = get_logger("models.monthly")

SEASONAL_PERIOD = 12
HORIZON_MONTHS = 12
HOLDOUT_MONTHS = 6
N_FOLDS = 3
MIN_TRAIN_MONTHS = 24
PROPHET_WINDOW = 60  # months: the recent regime, not the 2007 history

Forecaster = Callable[[np.ndarray, int], np.ndarray]


@dataclass(frozen=True)
class MonthlySeries:
    """One national series to forecast: a label and a monthly frame."""

    target: str
    frame: pd.DataFrame  # columns: period (YYYY-MM), value
    unit: str = ""


# --------------------------------------------------------------------------- #
# Candidates — each maps (history, horizon) -> point forecast
# --------------------------------------------------------------------------- #
def seasonal_naive(y: np.ndarray, h: int) -> np.ndarray:
    """Same month last year. The baseline every other candidate must beat."""
    out, buf = [], list(y)
    for _ in range(h):
        out.append(buf[-SEASONAL_PERIOD] if len(buf) >= SEASONAL_PERIOD else buf[-1])
        buf.append(out[-1])
    return np.asarray(out, dtype=float)


def drift(y: np.ndarray, h: int) -> np.ndarray:
    """Last value plus the series' average monthly change."""
    slope = (y[-1] - y[0]) / max(len(y) - 1, 1)
    return y[-1] + slope * np.arange(1, h + 1)


def seasonal_drift(y: np.ndarray, h: int) -> np.ndarray:
    """Same month last year, shifted by the mean year-on-year change of the last year."""
    if len(y) < 2 * SEASONAL_PERIOD:
        return seasonal_naive(y, h)
    yoy = float(np.mean(y[-SEASONAL_PERIOD:] - y[-2 * SEASONAL_PERIOD:-SEASONAL_PERIOD]))
    return seasonal_naive(y, h) + yoy


def holt_winters_damped(y: np.ndarray, h: int) -> np.ndarray:
    """Additive damped trend + additive annual seasonality."""
    if len(y) < 2 * SEASONAL_PERIOD + 2:
        return drift(y, h)
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(
            y, trend="add", damped_trend=True, seasonal="add",
            seasonal_periods=SEASONAL_PERIOD, initialization_method="estimated",
        ).fit(optimized=True)
    return np.asarray(model.forecast(h), dtype=float)


def theta(y: np.ndarray, h: int) -> np.ndarray:
    if len(y) < 2 * SEASONAL_PERIOD + 2:
        return drift(y, h)
    from statsmodels.tsa.forecasting.theta import ThetaModel

    idx = pd.period_range("2000-01", periods=len(y), freq="M")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ThetaModel(pd.Series(y, index=idx), period=SEASONAL_PERIOD).fit()
    return np.asarray(model.forecast(h).values, dtype=float)


def prophet_recent(y: np.ndarray, h: int) -> np.ndarray:
    """Prophet on the last PROPHET_WINDOW months only.

    Fitted across the whole history it learns the 2020 break as trend and
    extrapolates it; on the recent regime it is competitive.
    """
    from prophet import Prophet

    yy = y[-PROPHET_WINDOW:] if len(y) > PROPHET_WINDOW else y
    ds = pd.date_range("2000-01-01", periods=len(yy), freq="MS")
    m = Prophet(
        yearly_seasonality=len(yy) >= 2 * SEASONAL_PERIOD,
        weekly_seasonality=False, daily_seasonality=False, changepoint_prior_scale=0.05,
    )
    m.fit(pd.DataFrame({"ds": ds, "y": yy}))
    future = pd.DataFrame({"ds": pd.date_range(ds[-1] + pd.offsets.MonthBegin(1), periods=h, freq="MS")})
    return np.asarray(m.predict(future)["yhat"].values, dtype=float)


CANDIDATES: dict[str, Forecaster] = {
    "seasonal_naive": seasonal_naive,
    "drift": drift,
    "seasonal_drift": seasonal_drift,
    "holt_winters_damped": holt_winters_damped,
    "theta": theta,
    "prophet_recent_60m": prophet_recent,
}
BASELINE = "seasonal_naive"


# --------------------------------------------------------------------------- #
# Back-test and selection
# --------------------------------------------------------------------------- #
def _values(series: MonthlySeries) -> tuple[np.ndarray, list[str]]:
    f = series.frame.dropna(subset=["value"]).sort_values("period")
    return pd.to_numeric(f["value"], errors="coerce").to_numpy(dtype=float), list(f["period"])


def _folds(n: int) -> list[int]:
    return [n - i * HOLDOUT_MONTHS for i in range(N_FOLDS, 0, -1) if n - i * HOLDOUT_MONTHS >= MIN_TRAIN_MONTHS]


@dataclass
class Selection:
    model: str
    mae: float
    mae_std: float | None
    mape: float
    mase: float
    baseline_mae: float
    skill: float
    folds: int
    n_eval: int
    residuals: pd.Series
    candidates: dict[str, float]  # model -> mean MAE


def backtest(series: MonthlySeries) -> Selection | None:
    """Score every candidate on the same folds; return the winner's record."""
    y, _ = _values(series)
    cuts = _folds(len(y))
    if not cuts:
        return None

    results: dict[str, dict] = {}
    for name, fn in CANDIDATES.items():
        maes: list[float] = []
        mapes: list[float] = []
        mases: list[float] = []
        resid: list[float] = []
        for cut in cuts:
            train, hold = y[:cut], y[cut:cut + HOLDOUT_MONTHS]
            try:
                pred = np.asarray(fn(train, len(hold)), dtype=float)
                if pred.shape != hold.shape or not np.all(np.isfinite(pred)):
                    raise ValueError("bad forecast shape or non-finite values")
            except Exception as exc:  # noqa: BLE001
                log.debug("monthly.candidate_failed", target=series.target, model=name, error=str(exc))
                maes = []
                break
            err = hold - pred
            maes.append(float(np.mean(np.abs(err))))
            nz = hold != 0
            mapes.append(float(np.mean(np.abs(err[nz] / hold[nz])) * 100) if nz.any() else float("nan"))
            mases.append(mase(hold, pred, train, SEASONAL_PERIOD))
            resid.extend(err.tolist())
        if maes:
            results[name] = {"mae": float(np.mean(maes)), "mae_std": float(np.std(maes)) if len(maes) > 1 else None,
                             "mape": float(np.nanmean(mapes)), "mase": float(np.nanmean(mases)),
                             "resid": pd.Series(resid, dtype=float)}

    if BASELINE not in results:
        return None
    baseline_mae = results[BASELINE]["mae"]
    winner = min(results, key=lambda k: results[k]["mae"])
    w = results[winner]
    return Selection(
        model=winner, mae=w["mae"], mae_std=w["mae_std"], mape=w["mape"], mase=w["mase"],
        baseline_mae=baseline_mae,
        skill=(1 - w["mae"] / baseline_mae) if baseline_mae else float("nan"),
        folds=len(cuts), n_eval=len(cuts) * HOLDOUT_MONTHS, residuals=w["resid"],
        candidates={k: v["mae"] for k, v in results.items()},
    )


def forecast(series: MonthlySeries, choice: Selection) -> pd.DataFrame:
    """Twelve-month forecast from the selected model, with conformal intervals."""
    y, periods = _values(series)
    if len(y) < MIN_TRAIN_MONTHS:
        raise ValueError(f"{series.target}: need {MIN_TRAIN_MONTHS} months, have {len(y)}")
    yhat = np.asarray(CANDIDATES[choice.model](y, HORIZON_MONTHS), dtype=float)
    bias, lo, hi = bias_and_offsets(choice.residuals.values, level=0.8)
    yhat = yhat + bias
    start = pd.Period(periods[-1], freq="M") + 1
    future = pd.period_range(start, periods=HORIZON_MONTHS, freq="M").strftime("%Y-%m")
    out = pd.DataFrame({
        "target": series.target, "period": future,
        "yhat": np.round(yhat, 2),
        "yhat_lower": np.round(yhat + (lo if np.isfinite(lo) else 0.0), 2),
        "yhat_upper": np.round(yhat + (hi if np.isfinite(hi) else 0.0), 2),
        "model": choice.model, "unit": series.unit,
    })
    return out


def run_all(series_list: list[MonthlySeries]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Back-test, select and forecast every series; returns (forecasts, metrics)."""
    fcs: list[pd.DataFrame] = []
    mets: list[dict[str, object]] = []
    for s in series_list:
        choice = backtest(s)
        if choice is None:
            log.warning("monthly.skipped", target=s.target, months=len(s.frame))
            mets.append({"target": s.target, "model": None, "folds": 0, "unit": s.unit})
            continue
        mets.append({
            "target": s.target, "model": choice.model, "folds": choice.folds,
            "horizon_months": HOLDOUT_MONTHS, "unit": s.unit,
            "mae": round(choice.mae, 3), "mae_std": None if choice.mae_std is None else round(choice.mae_std, 3),
            "mape": round(choice.mape, 3), "mase": round(choice.mase, 3),
            "baseline": BASELINE, "baseline_mae": round(choice.baseline_mae, 3),
            "skill": round(choice.skill, 3), "n_eval": choice.n_eval,
            "candidates_tried": len(choice.candidates),
        })
        try:
            fcs.append(forecast(s, choice))
        except Exception as exc:  # noqa: BLE001
            log.warning("monthly.forecast_failed", target=s.target, error=str(exc))
        log.info("monthly.result", target=s.target, model=choice.model, skill=round(choice.skill, 3),
                 mase=round(choice.mase, 3), folds=choice.folds)
    forecasts = pd.concat(fcs, ignore_index=True) if fcs else pd.DataFrame(
        columns=["target", "period", "yhat", "yhat_lower", "yhat_upper", "model", "unit"])
    metrics = pd.DataFrame(mets)
    metrics["evaluated_at"] = pd.Timestamp.utcnow().tz_localize(None)
    return forecasts, metrics


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
