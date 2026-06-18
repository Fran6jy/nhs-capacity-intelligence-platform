"""Bed-occupancy forecaster.

Hybrid approach:
* Prophet for the univariate national trend + seasonality.
* XGBoost residual model that uses lag features, flu, covid, and weather.

This is the canonical pattern: a strong baseline (Prophet) with a
gradient-boosted residual model on top.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd
import xgboost as xgb
from prophet import Prophet
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error

from src.utils.logging import get_logger

log = get_logger("models.bed_occupancy")


@dataclass
class HybridForecast:
    df: pd.DataFrame   # date, yhat, yhat_lower, yhat_upper


class BedOccupancyForecaster:
    def __init__(self, horizon_days: int = 90) -> None:
        self.horizon_days = horizon_days
        self._prophet: Prophet | None = None
        self._xgb: xgb.XGBRegressor | None = None
        self._last_train: pd.DataFrame | None = None

    # ------------------------------------------------------------------ fit
    def fit(self, df: pd.DataFrame, target: str = "bed_occupancy_pct") -> None:
        log.info("bed_occupancy.fit", rows=len(df), target=target)
        df = df.sort_values("date_key").copy()
        df["date_key"] = pd.to_datetime(df["date_key"])

        # 1) national daily series for Prophet
        daily = (
            df.groupby("date_key", as_index=False)[target].mean()
            .rename(columns={"date_key": "ds", target: "y"})
        )
        daily = daily.dropna()

        m = Prophet(
            weekly_seasonality=True,
            yearly_seasonality=True,
            seasonality_mode="multiplicative",
            changepoint_prior_scale=0.05,
        )
        m.add_country_holidays(country_name="UK")
        m.fit(daily)
        self._prophet = m

        # 2) XGBoost residual on lag features
        df = df[["date_key", target, "flu_index", "covid_index", "avg_temp_c"]].copy()
        for lag in (1, 7, 14, 30):
            df[f"{target}_lag{lag}"] = df[target].shift(lag)
        for w in (7, 14, 30):
            df[f"{target}_roll{w}"] = df[target].rolling(w, min_periods=1).mean()
        df["month"] = df["date_key"].dt.month
        df["dow"] = df["date_key"].dt.dayofweek

        # Get Prophet fitted (in-sample) predictions to compute residual
        fitted = m.predict(daily[["ds"]])[["ds", "yhat"]]
        fitted["date_key"] = pd.to_datetime(fitted["ds"])
        df = df.merge(fitted[["date_key", "yhat"]], on="date_key", how="left")
        df["residual"] = df[target] - df["yhat"]
        df = df.dropna()

        features = [
            target + "_lag1", target + "_lag7", target + "_lag14", target + "_lag30",
            target + "_roll7", target + "_roll14", target + "_roll30",
            "flu_index", "covid_index", "avg_temp_c", "month", "dow",
        ]
        X = df[features].ffill()
        y = df["residual"]
        model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.9,
            random_state=42,
            n_jobs=4,
        )
        model.fit(X, y)
        self._xgb = model
        self._features = features
        self._last_train = df[["date_key"] + [target]].copy()

    # -------------------------------------------------------------- forecast
    def forecast(self) -> pd.DataFrame:
        if self._prophet is None or self._xgb is None:
            raise RuntimeError("Model has not been fit()")
        future = self._prophet.make_future_dataframe(periods=self.horizon_days)
        prophet_pred = self._prophet.predict(future)
        prophet_pred["date_key"] = pd.to_datetime(prophet_pred["ds"])

        # Build lag features for the *future* using last known values + prophet
        history = self._last_train.set_index("date_key")[self._last_train.columns[1]]
        future_dates = pd.date_range(history.index.max() + pd.Timedelta(days=1),
                                     periods=self.horizon_days, freq="D")
        rows = []
        for d in future_dates:
            row = {
                "date_key": d,
                "flu_index": self._seasonal_index(d, peak_month=1, amplitude=5, base=2),
                "covid_index": self._seasonal_index(d, peak_month=12, amplitude=1.5, base=2),
                "avg_temp_c": self._seasonal_temp(d),
            }
            for lag in (1, 7, 14, 30):
                key = history.index.max() - pd.Timedelta(days=lag) if (d - pd.Timedelta(days=lag)) in history.index else d - pd.Timedelta(days=lag)
                row[f"{history.name}_lag{lag}"] = history.get(key, history.iloc[-1])
            for w in (7, 14, 30):
                recent = history.sort_index().loc[d - pd.Timedelta(days=w):d - pd.Timedelta(days=1)]
                row[f"{history.name}_roll{w}"] = recent.mean() if not recent.empty else history.iloc[-1]
            row["month"] = d.month
            row["dow"] = d.dayofweek
            rows.append(row)
        future_df = pd.DataFrame(rows)
        X_future = future_df[self._features].apply(pd.to_numeric, errors="coerce").astype(float)
        residuals = self._xgb.predict(X_future)

        # Combine Prophet + residual. Align to exactly the forecast dates the
        # residuals were built for — the XGB history can be shorter than
        # Prophet's (e.g. real weather lags a few days, trimming lag rows), so a
        # ">" filter on the Prophet frame would over-select.
        out = prophet_pred[prophet_pred.date_key.isin(future_dates)].copy()
        out["residual"] = residuals
        out["yhat"] = out["yhat"] + out["residual"]
        out["yhat_lower"] = out["yhat_lower"] + out["residual"] * 0.6
        out["yhat_upper"] = out["yhat_upper"] + out["residual"] * 0.6
        return out[["date_key", "yhat", "yhat_lower", "yhat_upper"]]

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _seasonal_index(d: pd.Timestamp, peak_month: int, amplitude: float, base: float) -> float:
        diff = min(abs(d.month - peak_month), 12 - abs(d.month - peak_month))
        return float(base + amplitude * max(0, 1 - diff / 6))

    @staticmethod
    def _seasonal_temp(d: pd.Timestamp) -> float:
        return float(10 + 10 * (1 - abs(d.month - 7) / 6))

    @staticmethod
    def evaluate(y_true: Iterable[float], y_pred: Iterable[float]) -> dict[str, float]:
        return {
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": float(mean_absolute_percentage_error(y_true, y_pred)),
        }
