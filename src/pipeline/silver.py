"""🥈 Silver layer — cleaning, deduplication, type coercion.

For each bronze source we:
* coerce dtypes
* drop duplicates (partition key + business key)
* standardise trust / region codes
* handle missing values
* tag the run timestamp

We do **not** perform business joins here — that is Gold's job.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.config import settings
from src.utils.io import list_parquet_files, read_parquet, write_parquet
from src.utils.logging import get_logger

log = get_logger("silver")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_TRUST_CODE_RE = re.compile(r"^[A-Z0-9]{3,5}$")


def _normalise_trust_code(s: pd.Series) -> pd.Series:
    cleaned = (
        s.astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
    )
    # Keep only codes that look like valid NHS trust codes (3-5 alphanumerics).
    return cleaned.where(cleaned.str.match(_TRUST_CODE_RE), other=pd.NA)


def _clip_outliers(s: pd.Series, lo: float | None = None, hi: float | None = None) -> pd.Series:
    s = s.astype(float)
    if lo is None:
        lo = s.quantile(0.001)
    if hi is None:
        hi = s.quantile(0.999)
    return s.clip(lower=lo, upper=hi)


def _impute_median(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col not in df.columns:
        return df
    if df[col].isna().any():
        median = df[col].median()
        df[col] = df[col].fillna(median)
    return df


# --------------------------------------------------------------------------- #
# Source-specific transforms
# --------------------------------------------------------------------------- #

def clean_waiting_list(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    rename = {
        "trust_code": "trust_code",
        "specialty": "specialty",
        "period": "period",
        "waiting_list_size": "waiting_list_size",
        "median_wait_days": "median_wait_days",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["trust_code"] = _normalise_trust_code(df["trust_code"])
    df = df.dropna(subset=["trust_code"])
    df = df.drop_duplicates(subset=["trust_code", "specialty", "period"])
    df["waiting_list_size"] = _clip_outliers(df["waiting_list_size"], 0, 200_000)
    df["median_wait_days"] = _clip_outliers(df["median_wait_days"], 0, 365)
    df = _impute_median(df, "median_wait_days")
    return df.reset_index(drop=True)


def clean_hes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    df["trust_code"] = _normalise_trust_code(df["trust_code"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "trust_code"])
    df = df.drop_duplicates(subset=["trust_code", "specialty", "date"])
    for col in ("admissions", "discharges", "bed_occupancy_count", "ae_attendances", "referrals"):
        if col in df.columns:
            df[col] = _clip_outliers(df[col], 0)
            # round then cast to nullable Int64 (avoids pandas 3.x "safe" cast issue)
            df[col] = df[col].fillna(0).round().astype("Int64")
    return df.reset_index(drop=True)


def clean_workforce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    df["trust_code"] = _normalise_trust_code(df["trust_code"])
    df = df.drop_duplicates(subset=["trust_code", "role"])
    df["vacancy_rate"] = df["vacancy_rate"].clip(0, 50)
    return df.reset_index(drop=True)


def clean_illness(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.drop_duplicates(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["flu_index"] = df["flu_index"].clip(0, 50)
    df["covid_index"] = df["covid_index"].clip(0, 50)
    return df


def clean_weather(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "region_id"])
    df = df.drop_duplicates(subset=["date", "region_id"])
    df["avg_temp_c"] = df["avg_temp_c"].clip(-15, 40)
    return df.reset_index(drop=True)


def clean_demographics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.drop_duplicates(subset=["region_id"])
    return df.reset_index(drop=True)


def clean_dim_date(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date_key"] = pd.to_datetime(df["date_key"]).dt.date
    return df.drop_duplicates(subset=["date_key"]).sort_values("date_key").reset_index(drop=True)


def clean_dim_hospital(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hospital_id"] = df["hospital_id"].astype(str).str.strip()
    return df.drop_duplicates(subset=["hospital_id"]).reset_index(drop=True)


def clean_dim_specialty(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    return df.drop_duplicates(subset=["specialty_id"]).reset_index(drop=True)


def clean_dim_region(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    return df.drop_duplicates(subset=["region_id"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #

_CLEANERS = {
    "nhs_waiting_list": clean_waiting_list,
    "hes":              clean_hes,
    "workforce":        clean_workforce,
    "illness_trends":   clean_illness,
    "weather":          clean_weather,
    "demographics":     clean_demographics,
    "dim_date":         clean_dim_date,
    "dim_hospital":     clean_dim_hospital,
    "dim_specialty":    clean_dim_specialty,
    "dim_region":       clean_dim_region,
}


def run() -> None:
    log.info("silver.start")
    files: list[Path] = list_parquet_files(settings.bronze_path)
    for f in files:
        name = f.stem
        cleaner = _CLEANERS.get(name)
        if cleaner is None:
            log.warning("silver.no_cleaner", file=str(f))
            continue
        df = read_parquet(f)
        cleaned = cleaner(df)
        out = settings.silver_path / f"{name}.parquet"
        write_parquet(cleaned, out)
        log.info("silver.cleaned", source=name, rows=len(cleaned))
    log.info("silver.complete")


if __name__ == "__main__":
    run()
