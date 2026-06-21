"""Model validation — real temporal back-tests (no invented accuracy).

Holds out the last ``HOLDOUT_DAYS`` of the warehouse, fits each forecaster on
the rest, predicts the holdout, and compares to the actuals. Produces:

* ``model_metrics`` — MAE, MAPE and accuracy (100 - MAPE) per model.
* ``model_forecast_actual`` — predicted-vs-actual series for the headline model,
  so the Evidence & Validation page can show it isn't just a pretty UI.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.ae_demand import AEDemandForecaster
from src.models.bed_occupancy import BedOccupancyForecaster
from src.models.waiting_time import WaitingTimeForecaster
from src.utils.logging import get_logger

log = get_logger("models.validation")

HOLDOUT_DAYS = 30


def _scores(actual: pd.Series, pred: pd.Series) -> dict:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    mask = ~np.isnan(a) & ~np.isnan(p) & (a != 0)
    if mask.sum() == 0:
        return {"mae": float("nan"), "mape": float("nan"), "accuracy": float("nan"), "n_eval": 0}
    mae = float(np.mean(np.abs(a[mask] - p[mask])))
    mape = float(np.mean(np.abs((a[mask] - p[mask]) / a[mask])) * 100)
    return {"mae": round(mae, 2), "mape": round(mape, 2),
            "accuracy": round(max(0.0, 100 - mape), 1), "n_eval": int(mask.sum())}


def backtest(fact: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    fact = fact.copy()
    fact["date_key"] = pd.to_datetime(fact["date_key"])
    cutoff = fact["date_key"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    train = fact[fact["date_key"] <= cutoff]
    metrics: list[dict] = []
    fa_rows: list[pd.DataFrame] = []

    # 1) Bed occupancy — Prophet + XGBoost hybrid (national daily mean)
    try:
        m = BedOccupancyForecaster(horizon_days=HOLDOUT_DAYS)
        m.fit(train, target="bed_occupancy_pct")
        fc = m.forecast().set_index("date_key")["yhat"]
        actual = (fact[fact["date_key"] > cutoff]
                  .groupby("date_key")["bed_occupancy_pct"].mean())
        j = pd.concat([actual.rename("actual"), fc.rename("predicted")], axis=1).dropna()
        metrics.append({"target": "Capacity pressure", "model": "prophet+xgboost", **_scores(j["actual"], j["predicted"])})
        fa = j.reset_index().rename(columns={"date_key": "date"})
        fa["target"] = "Capacity pressure"
        fa_rows.append(fa[["target", "date", "actual", "predicted"]])
    except Exception as exc:  # noqa: BLE001
        log.warning("validation.bed_failed", error=str(exc))

    # 2) A&E demand — Prophet (national daily total)
    try:
        m = AEDemandForecaster(horizon_days=HOLDOUT_DAYS)
        m.fit(train, target="ae_attendances")
        fc = m.forecast().set_index("date_key")["yhat"]
        actual = (fact[fact["date_key"] > cutoff]
                  .groupby("date_key")["ae_attendances"].sum())
        j = pd.concat([actual.rename("actual"), fc.rename("predicted")], axis=1).dropna()
        metrics.append({"target": "A&E demand", "model": "prophet", **_scores(j["actual"], j["predicted"])})
    except Exception as exc:  # noqa: BLE001
        log.warning("validation.ae_failed", error=str(exc))

    # 3) Waiting time — LightGBM (per trust × specialty, 30-day horizon)
    try:
        wt = WaitingTimeForecaster(horizons=(HOLDOUT_DAYS,))
        wt.fit(train, target="median_wait_days")
        pred = wt.predict(train, horizon=HOLDOUT_DAYS).rename(columns={f"pred_{HOLDOUT_DAYS}d": "predicted"})
        pred["target_date"] = pd.to_datetime(pred["date_key"]) + pd.Timedelta(days=HOLDOUT_DAYS)
        act = fact[["date_key", "hospital_id", "specialty_id", "median_wait_days"]].rename(
            columns={"date_key": "target_date", "median_wait_days": "actual"})
        merged = pred.merge(act, on=["target_date", "hospital_id", "specialty_id"], how="inner")
        merged = merged[merged["target_date"] > cutoff]
        metrics.append({"target": "Waiting time", "model": "lightgbm", **_scores(merged["actual"], merged["predicted"])})
    except Exception as exc:  # noqa: BLE001
        log.warning("validation.wait_failed", error=str(exc))

    metrics_df = pd.DataFrame(metrics)
    metrics_df["holdout_days"] = HOLDOUT_DAYS
    metrics_df["evaluated_at"] = pd.Timestamp.utcnow().tz_localize(None)
    fa_df = (pd.concat(fa_rows, ignore_index=True) if fa_rows
             else pd.DataFrame(columns=["target", "date", "actual", "predicted"]))
    log.info("validation.done", models=len(metrics_df), fa_rows=len(fa_df))
    return metrics_df, fa_df


def run_and_persist(warehouse_path=None) -> int:
    """Back-test against the warehouse and store results as DuckDB tables."""
    import duckdb

    from src.config import settings
    warehouse_path = warehouse_path or settings.warehouse_path
    con = duckdb.connect(str(warehouse_path))
    fact = con.execute("SELECT * FROM hospital_activity_fact").fetch_df()
    metrics_df, fa_df = backtest(fact)
    con.register("m_df", metrics_df)
    con.register("fa_df", fa_df)
    con.execute("CREATE OR REPLACE TABLE model_metrics AS SELECT * FROM m_df")
    con.execute("CREATE OR REPLACE TABLE model_forecast_actual AS SELECT * FROM fa_df")
    con.close()
    return len(metrics_df)


if __name__ == "__main__":
    print("models validated:", run_and_persist())
