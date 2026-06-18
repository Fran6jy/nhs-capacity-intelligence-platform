"""🥇 Gold layer — build the star schema in DuckDB and load it.

Idempotent: drops and re-creates tables on each run.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from src.config import settings
from src.pipeline.features import add_all, regional_zscore
from src.utils.io import execute_sql_script, read_parquet
from src.utils.logging import get_logger

log = get_logger("gold")

# Canonical column order of the hospital_activity_fact star-schema table
# (must match sql/01_warehouse.sql). Kept as a module constant so both the
# fact builder and the loader project to exactly these 19 columns.
FACT_COLUMNS = [
    "activity_id", "date_key", "hospital_id", "specialty_id", "region_id",
    "admissions", "discharges", "bed_occupancy_pct", "bed_occupancy_count",
    "waiting_list_size", "median_wait_days", "staff_count", "vacancies",
    "vacancy_rate", "ae_attendances", "referrals",
    "flu_index", "covid_index", "avg_temp_c",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _read(name: str) -> pd.DataFrame:
    return read_parquet(settings.silver_path / f"{name}.parquet")


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

def _build_fact() -> pd.DataFrame:
    hes = _read("hes")
    wl = _read("nhs_waiting_list")
    wf = _read("workforce")
    illness = _read("illness_trends")
    weather = _read("weather")
    dim_h = _read("dim_hospital")
    dim_s = _read("dim_specialty")
    dim_r = _read("dim_region")

    # Trust → region mapping (via hospital)
    trust_region = (
        dim_h[["trust_code", "region_id"]].drop_duplicates()
    )

    hes = hes.merge(trust_region, on="trust_code", how="left")

    # Trust → specialty workforce aggregation (we attach per trust, not per spec).
    wf_agg = (
        wf.groupby("trust_code", as_index=False)
        .agg(staff_count=("staff_count", "sum"),
             vacancies=("vacancies", "sum"))
    )
    wf_agg["vacancy_rate"] = (
        wf_agg["vacancies"] / wf_agg["staff_count"].replace(0, pd.NA) * 100
    ).round(2)
    hes = hes.merge(wf_agg, on="trust_code", how="left")

    # Joining specialty — HES carries specialty *name* (e.g. SP_CARD), the
    # dim carries the same id, so rename column to match.
    hes = hes.rename(columns={"specialty": "specialty_id"})

    hes["date_key"] = pd.to_datetime(hes["date"]).dt.date

    # The waiting list is a *monthly* snapshot while HES is daily, so we join
    # on year-month and broadcast the monthly value across every day in that
    # month (a join on the exact date would only ever hit the 1st of the month).
    if not wl.empty and "period" in wl.columns:
        wl = wl.rename(columns={"specialty": "specialty_id"})
        wl["ym"] = wl["period"].str.slice(0, 7)  # "YYYY-MM"
        wl_agg = (
            wl.groupby(["trust_code", "specialty_id", "ym"], as_index=False)
            .agg({"waiting_list_size": "sum", "median_wait_days": "mean"})
        )
        hes["ym"] = pd.to_datetime(hes["date_key"]).dt.strftime("%Y-%m")
        hes = hes.merge(wl_agg, on=["trust_code", "specialty_id", "ym"], how="left")
        hes = hes.drop(columns=["ym"])
    else:
        hes["waiting_list_size"] = pd.NA
        hes["median_wait_days"] = pd.NA

    # Illness + weather joins
    hes["date_key_dt"] = pd.to_datetime(hes["date_key"])
    illness["date_key_dt"] = pd.to_datetime(illness["date"])
    weather["date_key_dt"] = pd.to_datetime(weather["date"])
    weather = weather.dropna(subset=["region_id"])

    fact = hes.merge(illness[["date_key_dt", "flu_index", "covid_index"]],
                     on="date_key_dt", how="left")
    fact = fact.merge(weather[["date_key_dt", "region_id", "avg_temp_c"]],
                      on=["date_key_dt", "region_id"], how="left")
    fact = fact.drop(columns=["date_key_dt"])

    # Compute bed_occupancy_pct where capacity available.
    trust_caps = (
        dim_h.groupby("trust_code", as_index=False)["bed_capacity"].sum()
    )
    fact = fact.merge(trust_caps, on="trust_code", how="left")
    fact["bed_occupancy_pct"] = (
        fact["bed_occupancy_count"] / fact["bed_capacity"].replace(0, pd.NA) * 100
    ).round(2)

    # hospital_id — assign one (we have 1:1 trust→hospital in dim_h)
    trust_hospital = dim_h[["trust_code", "hospital_id"]].drop_duplicates()
    fact = fact.merge(trust_hospital, on="trust_code", how="left")

    # Add activity_id surrogate key
    fact = fact.reset_index(drop=True)
    fact["activity_id"] = (fact.index + 1) * 1000 + 1

    # Required columns
    for c in FACT_COLUMNS:
        if c not in fact.columns:
            fact[c] = pd.NA
    return fact[FACT_COLUMNS]


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def run(warehouse_path: Path | None = None) -> Path:
    warehouse_path = warehouse_path or settings.warehouse_path
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    if warehouse_path.exists():
        warehouse_path.unlink()
    con = duckdb.connect(str(warehouse_path))

    # Schema
    schema_sql = (Path(__file__).resolve().parents[2] / "sql" / "01_warehouse.sql").read_text(encoding="utf-8")
    n = execute_sql_script(con, schema_sql)
    log.info("gold.schema_applied", statements=n)

    # Load dim tables — truncate first so the gold layer is idempotent on
    # rerun (we keep ml_forecast / risk_score / recommendation intact).
    for dim in ("dim_date", "dim_hospital", "dim_specialty", "dim_region"):
        df = _read(dim)
        con.execute(f"DELETE FROM {dim}")
        con.register("df_dim", df)
        con.execute(f"INSERT INTO {dim} SELECT * FROM df_dim")
        log.info("gold.loaded_dim", table=dim, rows=len(df))

    # Build and load fact
    fact = _build_fact()
    # Add engineered features
    fact = add_all(fact, target="bed_occupancy_pct")
    fact = add_all(fact, target="waiting_list_size")
    fact = regional_zscore(fact, "bed_occupancy_pct")
    fact = regional_zscore(fact, "median_wait_days")

    con.execute("DELETE FROM hospital_activity_fact")
    con.register("df_fact", fact[FACT_COLUMNS])
    con.execute("INSERT INTO hospital_activity_fact SELECT * FROM df_fact")
    log.info("gold.loaded_fact", rows=len(fact))

    # View creation
    views_sql = (Path(__file__).resolve().parents[2] / "sql" / "02_analytics_views.sql").read_text(encoding="utf-8")
    n = execute_sql_script(con, views_sql)
    log.info("gold.views_applied", statements=n)

    con.close()
    log.info("gold.complete", warehouse=str(warehouse_path))
    return warehouse_path


if __name__ == "__main__":
    run()
