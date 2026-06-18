"""Feature engineering — rolling means, lag variables, regional z-scores."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils.logging import get_logger

log = get_logger("features")


def add_rolling_means(df: pd.DataFrame, col: str, windows=(7, 14, 30)) -> pd.DataFrame:
    df = df.copy()
    for w in windows:
        df[f"{col}_roll{w}"] = (
            df.groupby(["hospital_id", "specialty_id"])[col]
            .transform(lambda s: s.rolling(w, min_periods=1).mean())
        )
    return df


def add_lag_features(df: pd.DataFrame, col: str, lags=(1, 7, 14, 30)) -> pd.DataFrame:
    df = df.copy()
    for lag in lags:
        df[f"{col}_lag{lag}"] = (
            df.groupby(["hospital_id", "specialty_id"])[col].shift(lag)
        )
    return df


def add_growth_rate(df: pd.DataFrame, col: str, periods=(7, 30)) -> pd.DataFrame:
    df = df.copy()
    for p in periods:
        prev = df.groupby(["hospital_id", "specialty_id"])[col].shift(p)
        df[f"{col}_growth{p}d"] = (df[col] - prev) / prev.replace(0, np.nan)
    return df


def add_seasonal(df: pd.DataFrame, date_col: str = "date_key") -> pd.DataFrame:
    df = df.copy()
    d = pd.to_datetime(df[date_col])
    df["month"] = d.dt.month
    df["day_of_week"] = d.dt.dayofweek
    df["is_weekend"] = d.dt.dayofweek.isin([5, 6])
    df["weekofyear"] = d.dt.isocalendar().week.astype(int)
    return df


def regional_zscore(df: pd.DataFrame, col: str, by: str = "region_id") -> pd.DataFrame:
    """Z-score a metric relative to its region (national normalisation)."""
    df = df.copy()
    grp = df.groupby(by)[col]
    df[f"{col}_regional_z"] = (df[col] - grp.transform("mean")) / grp.transform("std")
    return df


def add_all(df: pd.DataFrame, target: str) -> pd.DataFrame:
    log.info("features.add_all", target=target, rows=len(df))
    df = add_seasonal(df)
    df = add_rolling_means(df, target)
    df = add_lag_features(df, target)
    df = add_growth_rate(df, target)
    return df
