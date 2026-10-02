"""End-to-end training: fit every forecaster and write `ml_forecast`.

Every interval written here comes from the model that produced the point
forecast — Prophet's posterior band or a split-conformal offset calibrated on
held-out residuals. No fixed multipliers.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from src.config import settings
from src.models.ae_demand import AEDemandForecaster
from src.models.bed_occupancy import BedOccupancyForecaster
from src.models.waiting_time import WaitingTimeForecaster
from src.models.workforce_demand import VacancyRateForecaster
from src.utils.logging import get_logger

log = get_logger("training")

HORIZON = 90
COLUMNS = [
    "forecast_id", "date_key", "hospital_id", "specialty_id",
    "target", "horizon_days", "yhat", "yhat_lower", "yhat_upper", "model",
]


def _load_fact() -> pd.DataFrame:
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    df = con.execute("SELECT * FROM hospital_activity_fact").fetch_df()
    con.close()
    return df


def _national(fc: pd.DataFrame, target: str, model: str) -> pd.DataFrame:
    fc = fc.copy()
    fc["target"], fc["model"], fc["horizon_days"] = target, model, HORIZON
    fc["hospital_id"], fc["specialty_id"] = pd.NA, pd.NA
    return fc


def train_all() -> None:
    log.info("training.start")
    fact = _load_fact()
    log.info("training.data", fact_rows=len(fact))
    forecasts: list[pd.DataFrame] = []

    bed = BedOccupancyForecaster(horizon_days=HORIZON)
    bed.fit(fact, target="bed_occupancy_pct")
    forecasts.append(_national(bed.forecast(), "bed_occupancy", "prophet_xgb"))

    ae = AEDemandForecaster(horizon_days=HORIZON)
    ae.fit(fact, target="ae_attendances")
    forecasts.append(_national(ae.forecast(), "ae_demand", "prophet"))

    vac = VacancyRateForecaster(horizon_days=HORIZON)
    vac.fit(fact, target="vacancy_rate")
    forecasts.append(_national(vac.forecast(), "vacancy_rate", "prophet"))

    wt = WaitingTimeForecaster(horizons=(30, 60, 90))
    wt.fit(fact, target="median_wait_days")
    for h in wt.horizons:
        out = wt.predict(fact, horizon=h).rename(columns={
            f"pred_{h}d": "yhat", f"pred_{h}d_lower": "yhat_lower", f"pred_{h}d_upper": "yhat_upper",
        })
        out["target"], out["model"], out["horizon_days"] = "waiting_time", "lightgbm", h
        forecasts.append(out)

    out = pd.concat(forecasts, ignore_index=True, sort=False)
    out["forecast_id"] = range(1, len(out) + 1)
    out["date_key"] = pd.to_datetime(out["date_key"]).dt.date
    for c in COLUMNS:
        if c not in out.columns:
            out[c] = pd.NA
    out = out[COLUMNS]

    con = duckdb.connect(str(settings.warehouse_path))
    con.execute("DELETE FROM ml_forecast")
    con.register("df_fc", out)
    con.execute("INSERT INTO ml_forecast SELECT * FROM df_fc")
    con.close()
    log.info("training.complete", rows=len(out))


if __name__ == "__main__":
    train_all()
