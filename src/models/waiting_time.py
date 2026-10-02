"""Specialty-level waiting-time forecaster using LightGBM.

Direct multi-horizon: one model per horizon, each predicting the value
``horizon`` days ahead from features known today.

On the rolling features: they *include* the current day. That is correct here
and deliberately different from the bed-occupancy residual model. This model's
label is a future value, so today's figure is legitimately known at prediction
time and belongs in the features. The residual model's label is a function of
*today's* value, so for it the same window would be leakage.

Prediction intervals are split-conformal per horizon: the last fifth of the
dates is held out, residuals on it give the interval offsets, then the model is
refitted on everything. The previous fixed ``±8%`` band had no basis.
"""
from __future__ import annotations

import lightgbm as lgb
import pandas as pd

from src.models._common import bias_and_offsets
from src.utils.logging import get_logger

log = get_logger("models.waiting_time")

GROUP = ["hospital_id", "specialty_id"]


class WaitingTimeForecaster:
    def __init__(self, horizons: tuple[int, ...] = (30, 60, 90), interval_level: float = 0.8) -> None:
        self.horizons = horizons
        self.interval_level = interval_level
        self._models: dict[int, lgb.LGBMRegressor] = {}
        self._offsets: dict[int, tuple[float, float]] = {}
        self._bias: dict[int, float] = {}
        self._feat_cols: list[str] = []

    def _features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        df = df.sort_values("date_key").copy()
        df["date_key"] = pd.to_datetime(df["date_key"])
        for col in ("median_wait_days", "referrals", "vacancy_rate"):
            if col not in df.columns:
                continue
            g = df.groupby(GROUP)[col]
            for lag in (1, 7, 14, 30):
                df[f"{col}_lag{lag}"] = g.shift(lag)
            for w in (7, 14, 30):
                df[f"{col}_roll{w}"] = g.transform(lambda s, w=w: s.rolling(w, min_periods=1).mean())
        df["month"] = df["date_key"].dt.month
        df["dow"] = df["date_key"].dt.dayofweek
        df["flu_season"] = df["month"].isin([10, 11, 12, 1, 2, 3]).astype(int)
        feat_cols = [
            c for c in df.columns
            if any(p in c for p in ("_lag", "_roll", "month", "dow", "flu_season",
                                    "flu_index", "covid_index", "avg_temp_c"))
        ]
        return df, feat_cols

    @staticmethod
    def _new_model() -> lgb.LGBMRegressor:
        return lgb.LGBMRegressor(
            n_estimators=400, learning_rate=0.05, num_leaves=31,
            subsample=0.9, colsample_bytree=0.8, random_state=42, n_jobs=4, verbose=-1,
        )

    def fit(self, df: pd.DataFrame, target: str = "median_wait_days") -> None:
        df, feat_cols = self._features(df)
        self._feat_cols = feat_cols
        dates = df["date_key"].drop_duplicates().sort_values()
        cal_from = dates.iloc[int(len(dates) * 0.8)] if len(dates) >= 10 else None

        for horizon in self.horizons:
            d = df.copy()
            d["target"] = d.groupby(GROUP)[target].shift(-horizon)
            d = d.dropna(subset=["target"])
            X, y = d[feat_cols].ffill().fillna(0), d["target"]

            if cal_from is not None:
                fit_mask = d["date_key"] < cal_from
                if fit_mask.sum() >= 50 and (~fit_mask).sum() >= 5:
                    cal_model = self._new_model().fit(X[fit_mask], y[fit_mask])
                    resid = y[~fit_mask] - cal_model.predict(X[~fit_mask])
                    bias, lo, hi = bias_and_offsets(resid, self.interval_level)
                    self._bias[horizon], self._offsets[horizon] = bias, (lo, hi)

            self._models[horizon] = self._new_model().fit(X, y)
            log.info("waiting_time.fit", horizon=horizon, rows=len(X),
                     offsets=self._offsets.get(horizon))

    def predict(self, df: pd.DataFrame, horizon: int) -> pd.DataFrame:
        if horizon not in self._models:
            raise KeyError(f"Model for horizon={horizon} not fit.")
        df, _ = self._features(df)
        X = df[self._feat_cols].ffill().fillna(0)
        col = f"pred_{horizon}d"
        df[col] = self._models[horizon].predict(X) + self._bias.get(horizon, 0.0)
        lo, hi = self._offsets.get(horizon, (float("nan"), float("nan")))
        df[f"{col}_lower"] = df[col] + lo
        df[f"{col}_upper"] = df[col] + hi
        return df[["date_key", "hospital_id", "specialty_id", col, f"{col}_lower", f"{col}_upper"]]
