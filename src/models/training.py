"""End-to-end training script: trains all forecasters, writes
results to `ml_forecast` table in the warehouse.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from src.config import settings
from src.models.ae_demand import AEDemandForecaster
from src.models.bed_occupancy import BedOccupancyForecaster
from src.models.waiting_time import WaitingTimeForecaster
from src.models.workforce_demand import WorkforceDemandModel
from src.utils.io import read_parquet
from src.utils.logging import get_logger

log = get_logger("training")


def _load_fact() -> pd.DataFrame:
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    df = con.execute("SELECT * FROM hospital_activity_fact").fetch_df()
    con.close()
    return df


def _load_workforce() -> pd.DataFrame:
    """The workforce table isn't in fact; pull from silver."""
    return read_parquet(settings.silver_path / "workforce.parquet")


def train_all() -> None:
    log.info("training.start")
    fact = _load_fact()
    workforce = _load_workforce()
    log.info("training.data", fact_rows=len(fact), workforce_rows=len(workforce))

    forecasts: list[pd.DataFrame] = []

    # 1) Bed occupancy (national hybrid)
    bed = BedOccupancyForecaster(horizon_days=90)
    bed.fit(fact, target="bed_occupancy_pct")
    bed_fc = bed.forecast()
    bed_fc["target"] = "bed_occupancy"
    bed_fc["model"] = "prophet_xgb"
    bed_fc["horizon_days"] = 90
    bed_fc["hospital_id"] = pd.NA
    bed_fc["specialty_id"] = pd.NA
    forecasts.append(bed_fc)

    # 2) A&E demand
    ae = AEDemandForecaster(horizon_days=90)
    ae.fit(fact, target="ae_attendances")
    ae_fc = ae.forecast()
    ae_fc["target"] = "ae_demand"
    ae_fc["model"] = "prophet"
    ae_fc["horizon_days"] = 90
    ae_fc["hospital_id"] = pd.NA
    ae_fc["specialty_id"] = pd.NA
    forecasts.append(ae_fc)

    # 3) Waiting time
    wt = WaitingTimeForecaster(horizons=(30, 60, 90))
    wt.fit(fact, target="median_wait_days")
    wt_rows = []
    for h in wt.horizons:
        out = wt.predict(fact, horizon=h)
        out = out.rename(columns={f"pred_{h}d": "yhat"})
        out["target"] = "waiting_time"
        out["model"] = "lightgbm"
        out["horizon_days"] = h
        out["yhat_lower"] = out["yhat"] * 0.92
        out["yhat_upper"] = out["yhat"] * 1.08
        wt_rows.append(out)
    wt_df = pd.concat(wt_rows, ignore_index=True)
    forecasts.append(wt_df)

    # 4) Workforce demand — write to its own table in warehouse via gold.load
    wf = WorkforceDemandModel()
    wf.fit(workforce.assign(date_key=date.today()))
    shortage = wf.predict_shortage(workforce.assign(date_key=date.today()))
    demand = wf.predict_demand(workforce.assign(date_key=date.today()))
    workforce_out = demand.rename(columns={"demand_fte": "yhat"})
    workforce_out["target"] = "workforce_demand"
    workforce_out["model"] = "xgboost"
    workforce_out["horizon_days"] = 60
    workforce_out["yhat_lower"] = workforce_out["yhat"] * 0.95
    workforce_out["yhat_upper"] = workforce_out["yhat"] * 1.05
    workforce_out["specialty_id"] = pd.NA
    # map trust → hospital_id (the star-schema fact only carries hospital_id,
    # so the trust→hospital bridge comes from the dim_hospital dimension)
    dim_h = read_parquet(settings.silver_path / "dim_hospital.parquet")
    trust_map = dim_h[["trust_code", "hospital_id"]].drop_duplicates().dropna()
    workforce_out = workforce_out.merge(trust_map, on="trust_code", how="left")
    forecasts.append(workforce_out)

    # ------- write to warehouse -------
    out = pd.concat(forecasts, ignore_index=True, sort=False)
    out = out.assign(
        forecast_id=lambda d: range(1, len(d) + 1),
        date_key=lambda d: pd.to_datetime(d["date_key"]).dt.date,
    )
    # Make sure columns are present
    for c in ("yhat", "yhat_lower", "yhat_upper", "horizon_days", "model",
              "target", "date_key", "forecast_id", "hospital_id", "specialty_id"):
        if c not in out.columns:
            out[c] = pd.NA
    out = out[
        ["forecast_id", "date_key", "hospital_id", "specialty_id",
         "target", "horizon_days", "yhat", "yhat_lower", "yhat_upper", "model"]
    ]

    con = duckdb.connect(str(settings.warehouse_path))
    con.execute("DELETE FROM ml_forecast")
    con.register("df_fc", out)
    con.execute("INSERT INTO ml_forecast SELECT * FROM df_fc")
    con.close()
    log.info("training.complete", rows=len(out))


if __name__ == "__main__":
    train_all()
