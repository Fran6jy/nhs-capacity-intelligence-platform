"""Date utilities — season mapping, lag creation helpers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

import pandas as pd


def to_date(x) -> pd.Timestamp:
    return pd.Timestamp(x).normalize()


def season_of(d: pd.Timestamp | datetime | date) -> str:
    """Northern-meteorological season (UK default)."""
    m = pd.Timestamp(d).month
    if m in (12, 1, 2):
        return "Winter"
    if m in (3, 4, 5):
        return "Spring"
    if m in (6, 7, 8):
        return "Summer"
    return "Autumn"


def is_flu_season(d: pd.Timestamp | datetime | date) -> bool:
    m = pd.Timestamp(d).month
    # UK flu season: Oct–Mar
    return m in (10, 11, 12, 1, 2, 3)


def build_dim_date(start: str | date, end: str | date) -> pd.DataFrame:
    """Return a complete dim_date frame between start and end (inclusive)."""
    dates = pd.date_range(start=start, end=end, freq="D")
    df = pd.DataFrame({"date_key": dates})
    df["year"] = df.date_key.dt.year
    df["quarter"] = df.date_key.dt.quarter
    df["month"] = df.date_key.dt.month
    df["month_name"] = df.date_key.dt.strftime("%B")
    df["week"] = df.date_key.dt.isocalendar().week.astype(int)
    df["day_of_week"] = df.date_key.dt.dayofweek + 1
    df["day_name"] = df.date_key.dt.strftime("%A")
    df["is_weekend"] = df.day_of_week.isin([6, 7])
    df["season"] = df.date_key.apply(season_of)
    df["flu_season_flag"] = df.date_key.apply(is_flu_season)
    return df


def safe_lag(df: pd.DataFrame, col: str, n: int) -> pd.Series:
    return df[col].shift(n)
