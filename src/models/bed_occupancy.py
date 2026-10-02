"""Bed-occupancy (capacity pressure) forecaster.

Hybrid: Prophet for the national trend and seasonality, with an XGBoost model
on Prophet's *out-of-fold* residuals using lag, rolling and calendar features.

What changed from the first version, and why
--------------------------------------------
* Features are built on the **national daily series** (one row per day). The
  earlier code built them on the raw fact table, which has ~160 rows per day
  (hospital × specialty), so ``shift(1)`` returned the previous *row* — another
  hospital on the same day — and every "lag" was meaningless.
* Rolling windows are **shifted by one** so they exclude the day being
  predicted. Unshifted, ``roll7`` on day *t* contained *y_t*, and the residual
  model could read its own target out of a feature. In-sample fit looked
  excellent; the forecast path, which has no *y_t*, saw a different feature
  distribution entirely.
* XGBoost trains on **out-of-fold** Prophet residuals from rolling-origin
  folds, not on in-sample ones, which are optimistically small.
* Multi-step forecasting is **recursive**: each day's prediction is appended to
  the history before the next day's lags are computed.
* Yearly seasonality is only enabled with two or more years of data.
* Prediction intervals are **split-conformal**: quantiles of hybrid residuals on
  a held-out calibration fold. The previous ``yhat_lower + residual * 0.6`` had
  no basis.
* No exogenous drivers. Flu, COVID and temperature need *future* values to be
  useful at forecast time, and the earlier code invented them with hard-coded
  sinusoids. Add them back when a forecast feed exists.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from prophet import Prophet

from src.models._common import (
    FEATURE_COLUMNS,
    bias_and_offsets,
    daily_features,
    expanding_time_folds,
    features_for_date,
    yearly_seasonality_for,
)
from src.utils.logging import get_logger

log = get_logger("models.bed_occupancy")

MIN_TRAINING_DAYS = 60


class BedOccupancyForecaster:
    def __init__(self, horizon_days: int = 90, interval_level: float = 0.8, n_folds: int = 3) -> None:
        self.horizon_days = horizon_days
        self.interval_level = interval_level
        self.n_folds = n_folds
        self._prophet: Prophet | None = None
        self._xgb: xgb.XGBRegressor | None = None
        self._daily: pd.DataFrame | None = None
        self._offsets: tuple[float, float] = (float("nan"), float("nan"))
        self._bias: float = 0.0
        self.yearly_seasonality: bool = False

    # ------------------------------------------------------------------ fit
    def _new_prophet(self) -> Prophet:
        m = Prophet(
            weekly_seasonality=True,
            yearly_seasonality=self.yearly_seasonality,
            seasonality_mode="multiplicative",
            changepoint_prior_scale=0.05,
        )
        m.add_country_holidays(country_name="UK")
        return m

    @staticmethod
    def _new_xgb() -> xgb.XGBRegressor:
        # Shallow on purpose: it corrects residuals on a few hundred rows at most.
        return xgb.XGBRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.9, random_state=42, n_jobs=2,
        )

    @staticmethod
    def national_daily(df: pd.DataFrame, target: str) -> pd.DataFrame:
        """Collapse the fact table to one national mean per day."""
        d = df[["date_key", target]].copy()
        d["date_key"] = pd.to_datetime(d["date_key"])
        daily = (
            d.groupby("date_key", as_index=False)[target].mean()
            .rename(columns={"date_key": "ds", target: "y"})
            .dropna()
            .sort_values("ds")
            .reset_index(drop=True)
        )
        return daily

    def fit(self, df: pd.DataFrame, target: str = "bed_occupancy_pct") -> None:
        daily = self.national_daily(df, target)
        if len(daily) < MIN_TRAINING_DAYS:
            raise ValueError(f"need at least {MIN_TRAINING_DAYS} days, got {len(daily)}")
        self.yearly_seasonality = yearly_seasonality_for(daily["ds"])
        log.info("bed_occupancy.fit", days=len(daily), yearly=self.yearly_seasonality)

        # Out-of-fold Prophet residuals: each fold is predicted by a model that
        # never saw it, so the residual corrector learns realistic errors.
        parts: list[pd.DataFrame] = []
        for train, val in expanding_time_folds(len(daily), self.n_folds, MIN_TRAINING_DAYS):
            p = self._new_prophet().fit(daily.iloc[train])
            pred = p.predict(daily.iloc[val][["ds"]])[["ds", "yhat"]]
            part = daily.iloc[val].merge(pred, on="ds")
            part["residual"] = part["y"] - part["yhat"]
            parts.append(part)

        feats = daily_features(daily)
        self._daily = daily
        self._prophet = self._new_prophet().fit(daily)

        if not parts:
            log.warning("bed_occupancy.no_folds", days=len(daily))
            self._xgb = None
            return

        oof = pd.concat(parts, ignore_index=True).merge(feats, on="ds").dropna(subset=FEATURE_COLUMNS)

        # Split conformal: calibrate intervals on the most recent fold using a
        # corrector that never saw it, then refit the corrector on everything.
        cal_start = parts[-1]["ds"].min()
        fit_part, cal_part = oof[oof["ds"] < cal_start], oof[oof["ds"] >= cal_start]
        if len(fit_part) >= 20 and len(cal_part) >= 5:
            cal_model = self._new_xgb().fit(fit_part[FEATURE_COLUMNS], fit_part["residual"])
            hybrid = cal_part["yhat"] + cal_model.predict(cal_part[FEATURE_COLUMNS])
            self._bias, lo, hi = bias_and_offsets(cal_part["y"] - hybrid, self.interval_level)
            self._offsets = (lo, hi)

        self._xgb = self._new_xgb().fit(oof[FEATURE_COLUMNS], oof["residual"])
        log.info("bed_occupancy.residual_model", oof_rows=len(oof), offsets=self._offsets)

    # -------------------------------------------------------------- forecast
    def forecast(self) -> pd.DataFrame:
        if self._prophet is None or self._daily is None:
            raise RuntimeError("Model has not been fit()")

        last = self._daily["ds"].max()
        future_dates = pd.date_range(last + pd.Timedelta(days=1), periods=self.horizon_days, freq="D")
        base = self._prophet.predict(pd.DataFrame({"ds": future_dates}))
        base = base.set_index("ds")[["yhat", "yhat_lower", "yhat_upper"]]

        history = self._daily.set_index("ds")["y"].astype(float)
        preds: list[float] = []
        for when in future_dates:
            yhat = float(base.at[when, "yhat"])
            if self._xgb is not None:
                row = pd.DataFrame([features_for_date(history, when)])[FEATURE_COLUMNS]
                yhat += float(self._xgb.predict(row)[0])
            yhat += self._bias  # median held-out residual: cheapest accuracy gain available
            preds.append(yhat)
            history.loc[when] = yhat  # recursive: tomorrow's lag1 is today's forecast

        out = pd.DataFrame({"date_key": future_dates, "yhat": preds})
        lo, hi = self._offsets
        if np.isfinite(lo) and np.isfinite(hi):
            out["yhat_lower"] = out["yhat"] + lo
            out["yhat_upper"] = out["yhat"] + hi
        else:  # too little data to calibrate — fall back to Prophet's own band
            out["yhat_lower"] = base["yhat_lower"].values
            out["yhat_upper"] = base["yhat_upper"].values
        return out[["date_key", "yhat", "yhat_lower", "yhat_upper"]]
