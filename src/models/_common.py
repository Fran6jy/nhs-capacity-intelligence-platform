"""Shared modelling utilities.

Everything here exists to stop a specific class of quiet modelling error:

* :func:`yearly_seasonality_for` — Prophet will happily fit an annual Fourier
  series to six months of data and extrapolate the result. Only enable it once
  the series has actually seen two full cycles.
* :func:`expanding_time_folds` — rolling-origin folds for out-of-fold residuals
  and back-tests. A single train/test split gives one number with unknown
  variance; several origins give a distribution.
* :func:`conformal_offsets` — split-conformal prediction intervals from held-out
  residuals. Replaces the hand-picked ``yhat * 0.92`` style multipliers that
  used to pass for uncertainty.
* :func:`daily_features` — lag and rolling features for a one-row-per-day
  series, with the rolling windows shifted so they never include the row being
  predicted. Building these on a multi-row-per-day frame (hospital × specialty)
  silently produces "lags" that are just the previous row.
* :func:`seasonal_naive` / :func:`last_value` — the baselines every forecast
  must beat before its accuracy means anything.
"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd

#: Two full annual cycles before Prophet is allowed to model one.
MIN_DAYS_FOR_YEARLY = 730

LAGS = (1, 7, 14, 30)
WINDOWS = (7, 14, 30)
FEATURE_COLUMNS = [f"lag{lag}" for lag in LAGS] + [f"roll{w}" for w in WINDOWS] + [
    "dow", "month", "dayofyear",
]


def yearly_seasonality_for(dates: pd.Series) -> bool:
    """True only when the series spans at least two years."""
    d = pd.to_datetime(dates)
    if d.empty:
        return False
    return bool((d.max() - d.min()).days >= MIN_DAYS_FOR_YEARLY)


def expanding_time_folds(
    n: int, n_folds: int = 3, min_train: int = 60, fold_len: int | None = None
) -> Iterator[tuple[slice, slice]]:
    """Yield ``(train, validation)`` slices with an expanding training window.

    Folds are taken from the tail of the series, oldest first, so every fold
    trains strictly on data that precedes it. The number of folds is reduced
    rather than the minimum training size violated.
    """
    if n < min_train + 14:
        return
    fold_len = fold_len or max(14, n // (n_folds * 2))
    k = min(n_folds, max(1, (n - min_train) // fold_len))
    for i in range(k, 0, -1):
        val_end = n - (i - 1) * fold_len
        val_start = val_end - fold_len
        yield slice(0, val_start), slice(val_start, val_end)


def conformal_offsets(residuals, level: float = 0.8) -> tuple[float, float]:
    """Interval offsets ``(lower, upper)`` from held-out residuals.

    ``residuals`` are ``actual - predicted`` on data the model did not train on.
    Add the offsets to a point forecast for a ``level`` interval. Returns NaNs
    when there are too few residuals to say anything.
    """
    r = np.asarray(residuals, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 5:
        return float("nan"), float("nan")
    alpha = (1.0 - level) / 2.0
    return float(np.quantile(r, alpha)), float(np.quantile(r, 1.0 - alpha))


def bias_and_offsets(residuals, level: float = 0.8) -> tuple[float, float, float]:
    """``(bias, lower, upper)``: a median bias correction plus centred offsets.

    If held-out residuals are systematically one-signed, raw conformal
    quantiles can both land on the same side of zero and the point forecast
    ends up outside its own interval. Correcting the point by the median
    residual and taking quantiles of the *centred* residuals fixes both: the
    forecast is less biased, and ``lower <= 0 <= upper`` always holds.
    """
    r = np.asarray(residuals, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 5:
        return 0.0, float("nan"), float("nan")
    bias = float(np.median(r))
    lo, hi = conformal_offsets(r - bias, level)
    return bias, min(lo, 0.0), max(hi, 0.0)


def daily_features(daily: pd.DataFrame, value_col: str = "y") -> pd.DataFrame:
    """Lag, rolling and calendar features for a one-row-per-day frame.

    ``daily`` must have a ``ds`` column and one row per date, sorted ascending.
    Rolling means use ``shift(1)`` first so that ``roll7`` on day *t* is the
    mean of days *t-7 … t-1*; without the shift it would contain *y_t* itself,
    which is target leakage when the model's label is a function of *y_t*.
    """
    y = daily[value_col].astype(float)
    out = pd.DataFrame({"ds": pd.to_datetime(daily["ds"]).values})
    for lag in LAGS:
        out[f"lag{lag}"] = y.shift(lag).values
    prior = y.shift(1)
    for w in WINDOWS:
        out[f"roll{w}"] = prior.rolling(w, min_periods=1).mean().values
    ds = pd.to_datetime(out["ds"])
    out["dow"] = ds.dt.dayofweek
    out["month"] = ds.dt.month
    out["dayofyear"] = ds.dt.dayofyear
    return out


def features_for_date(history: pd.Series, when: pd.Timestamp) -> dict[str, float]:
    """The same features as :func:`daily_features`, for one future date.

    ``history`` is a date-indexed series of known *and already-forecast* values
    up to the day before ``when``; recursive multi-step forecasting appends each
    prediction before computing the next day's features, so ``lag1`` for day
    *t+2* is the forecast for *t+1*, not the last observed value repeated.
    """
    hist = history.sort_index()
    row: dict[str, float] = {}
    for lag in LAGS:
        key = when - pd.Timedelta(days=lag)
        row[f"lag{lag}"] = float(hist.get(key, np.nan))
    for w in WINDOWS:
        window = hist.loc[when - pd.Timedelta(days=w): when - pd.Timedelta(days=1)]
        row[f"roll{w}"] = float(window.mean()) if not window.empty else float(hist.iloc[-1])
    row["dow"] = when.dayofweek
    row["month"] = when.month
    row["dayofyear"] = when.dayofyear
    return row


def seasonal_naive(history: pd.Series, horizon: int, period: int = 7) -> np.ndarray:
    """Forecast each future day as the value ``period`` days earlier.

    With a weekly period this is the strongest trivial baseline for daily
    operational series, and the one a model must beat to claim any skill.
    """
    h = np.asarray(history, dtype=float)
    if h.size < period:
        return np.full(horizon, h[-1] if h.size else np.nan)
    out = []
    buf = list(h)
    for _ in range(horizon):
        out.append(buf[-period])
        buf.append(out[-1])
    return np.asarray(out)


def last_value(history: pd.Series, horizon: int) -> np.ndarray:
    """Forecast every future day as the last observed value."""
    h = np.asarray(history, dtype=float)
    return np.full(horizon, h[-1] if h.size else np.nan)


def mase(actual, predicted, insample, period: int = 7) -> float:
    """Mean absolute scaled error: MAE relative to the in-sample seasonal-naive MAE.

    Below 1.0 means the model beats the naive baseline; above 1.0 it is worse
    than predicting last week. Unlike MAPE it is defined at zero and does not
    reward under-forecasting.
    """
    a, p = np.asarray(actual, float), np.asarray(predicted, float)
    ins = np.asarray(insample, float)
    if ins.size <= period:
        return float("nan")
    scale = np.mean(np.abs(ins[period:] - ins[:-period]))
    if not np.isfinite(scale) or scale == 0:
        return float("nan")
    return float(np.mean(np.abs(a - p)) / scale)
