"""Specialty-level waiting-time forecaster using LightGBM."""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from src.utils.logging import get_logger

log = get_logger("models.waiting_time")


class WaitingTimeForecaster:
    def __init__(self, horizons: tuple[int, ...] = (30, 60, 90)) -> None:
        self.horizons = horizons
        self._models: dict[int, lgb.LGBMRegressor] = {}

    def _features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        df = df.sort_values("date_key").copy()
        # Per-group lag features (specialty × hospital)
        for col in ("median_wait_days", "referrals", "vacancy_rate"):
            if col in df.columns:
                for lag in (1, 7, 14, 30):
                    df[f"{col}_lag{lag}"] = (
                        df.groupby(["hospital_id", "specialty_id"])[col].shift(lag)
                    )
                for w in (7, 14, 30):
                    df[f"{col}_roll{w}"] = (
                        df.groupby(["hospital_id", "specialty_id"])[col]
                        .transform(lambda s: s.rolling(w, min_periods=1).mean())
                    )
        df["month"] = pd.to_datetime(df["date_key"]).dt.month
        df["dow"] = pd.to_datetime(df["date_key"]).dt.dayofweek
        df["flu_season"] = df["month"].isin([10, 11, 12, 1, 2, 3]).astype(int)

        feat_cols = [c for c in df.columns
                     if any(p in c for p in ("_lag", "_roll", "month", "dow", "flu_season",
                                              "flu_index", "covid_index", "avg_temp_c"))]
        return df, feat_cols

    def fit(self, df: pd.DataFrame, target: str = "median_wait_days") -> None:
        df, feat_cols = self._features(df)
        for horizon in self.horizons:
            df_h = df.copy()
            df_h["target"] = (
                df_h.groupby(["hospital_id", "specialty_id"])[target].shift(-horizon)
            )
            df_h = df_h.dropna(subset=["target"])
            X = df_h[feat_cols].ffill().fillna(0)
            y = df_h["target"]
            model = lgb.LGBMRegressor(
                n_estimators=400,
                learning_rate=0.05,
                num_leaves=31,
                subsample=0.9,
                colsample_bytree=0.8,
                random_state=42,
                n_jobs=4,
            )
            model.fit(X, y, categorical_feature=None)
            self._models[horizon] = model
            log.info("waiting_time.fit", horizon=horizon, rows=len(X))

    def predict(self, df: pd.DataFrame, horizon: int) -> pd.DataFrame:
        if horizon not in self._models:
            raise KeyError(f"Model for horizon={horizon} not fit.")
        df, feat_cols = self._features(df)
        X = df[feat_cols].ffill().fillna(0)
        df[f"pred_{horizon}d"] = self._models[horizon].predict(X)
        return df[["date_key", "hospital_id", "specialty_id", f"pred_{horizon}d"]]
