"""Workforce demand / shortage model — XGBoost classifier + regressor.

* `predict_shortage` — probability of a trust × role being short-staffed
  on a given date (binary classifier).
* `predict_demand` — expected FTE demand 30/60/90 days ahead.
"""
from __future__ import annotations

import pandas as pd
import xgboost as xgb

from src.utils.logging import get_logger

log = get_logger("models.workforce")


class WorkforceDemandModel:
    def __init__(self) -> None:
        self._clf: xgb.XGBClassifier | None = None
        self._reg: xgb.XGBRegressor | None = None

    def _build_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        df = df.sort_values("date_key").copy()
        for col in ("vacancy_rate", "staff_count"):
            if col in df.columns:
                for lag in (7, 14, 30):
                    df[f"{col}_lag{lag}"] = (
                        df.groupby(["trust_code", "role"])[col].shift(lag)
                    )
                for w in (14, 30):
                    df[f"{col}_roll{w}"] = (
                        df.groupby(["trust_code", "role"])[col]
                        .transform(lambda s, w=w: s.rolling(w, min_periods=1).mean())
                    )
        df["month"] = pd.to_datetime(df["date_key"]).dt.month
        df["dow"] = pd.to_datetime(df["date_key"]).dt.dayofweek
        # role as numeric
        df["role_code"] = df["role"].astype("category").cat.codes
        feats = [c for c in df.columns
                 if any(p in c for p in ("_lag", "_roll", "month", "dow", "role_code"))]
        return df, feats

    def fit(self, df: pd.DataFrame) -> None:
        df, feats = self._build_features(df)

        # Classifier
        clf_df = df.copy()
        clf_df["shortage_label"] = (clf_df["vacancy_rate"] > 9.0).astype(int)
        Xc = clf_df[feats].ffill().fillna(0)
        yc = clf_df["shortage_label"]
        clf = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            random_state=42,
            n_jobs=4,
        )
        clf.fit(Xc, yc)
        self._clf = clf

        # Regressor for FTE demand
        reg_df = df.dropna(subset=["staff_count"]).copy()
        Xr = reg_df[feats].ffill().fillna(0)
        yr = reg_df["staff_count"]
        reg = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            random_state=42,
            n_jobs=4,
        )
        reg.fit(Xr, yr)
        self._reg = reg
        self._feats = feats
        log.info("workforce.fit", rows=len(df))

    def predict_shortage(self, df: pd.DataFrame) -> pd.DataFrame:
        if self._clf is None:
            raise RuntimeError("Model has not been fit()")
        df, _ = self._build_features(df)
        X = df[self._feats].ffill().fillna(0)
        df["shortage_proba"] = self._clf.predict_proba(X)[:, 1]
        return df[["date_key", "trust_code", "role", "shortage_proba"]]

    def predict_demand(self, df: pd.DataFrame) -> pd.DataFrame:
        if self._reg is None:
            raise RuntimeError("Model has not been fit()")
        df, _ = self._build_features(df)
        X = df[self._feats].ffill().fillna(0)
        df["demand_fte"] = self._reg.predict(X)
        return df[["date_key", "trust_code", "role", "demand_fte"]]
