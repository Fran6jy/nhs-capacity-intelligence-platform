"""Model validation: rolling-origin back-tests against trivial baselines.

The earlier version held out the final 30 days once and reported
"accuracy = 100 − MAPE". That is one number with unknown variance, in a metric
that reads like a grade, with nothing to compare it to. On a series hovering
around 89%, "predict last week" scores well too, and without that comparison
an 85% figure says nothing about whether the model has learned anything.

This version:

* evaluates on **several rolling origins**, so every metric comes with a
  spread, not a point;
* scores every forecast against the **best trivial baseline** available
  (seasonal naive or last value for national series, persistence for the
  waiting-time panel) and reports **skill** — the fraction of baseline error
  the model removes. Skill ≤ 0 means the model is no better than guessing;
* reports **MASE**, which is scale-free, defined at zero, and reads directly
  as "error relative to last week" (1.0 = no better than the naive);
* still writes a predicted-vs-actual series for the Evidence page, now with
  the baseline alongside so the chart shows what the model is beating.

MAPE is kept because people expect it, not because it is good.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd

from src.models._common import expanding_time_folds, last_value, mase, seasonal_naive
from src.models.ae_demand import AEDemandForecaster
from src.models.bed_occupancy import BedOccupancyForecaster
from src.models.waiting_time import WaitingTimeForecaster
from src.models.workforce_demand import VacancyRateForecaster
from src.utils.logging import get_logger

log = get_logger("models.validation")

HOLDOUT_DAYS = 30
N_FOLDS = 3
MIN_TRAIN_DAYS = 60
SEASONAL_PERIOD = 7

METRIC_COLUMNS = [
    "target", "model", "folds", "horizon_days", "mae", "mae_std", "mape", "mase",
    "baseline", "baseline_mae", "skill", "n_eval", "evaluated_at",
]

class NationalForecaster(Protocol):
    """What a national-series forecaster must offer the back-test."""

    yearly_seasonality: bool

    def __init__(self, horizon_days: int) -> None: ...
    @staticmethod
    def national_daily(df: pd.DataFrame, target: str) -> pd.DataFrame: ...
    def fit(self, df: pd.DataFrame, target: str) -> None: ...
    def forecast(self) -> pd.DataFrame: ...


#: National targets: (label, model class, fact column, model name)
NATIONAL: list[tuple[str, type[NationalForecaster], str, str]] = [
    ("Capacity pressure", BedOccupancyForecaster, "bed_occupancy_pct", "prophet+xgboost"),
    ("A&E demand", AEDemandForecaster, "ae_attendances", "prophet"),
    ("Vacancy rate", VacancyRateForecaster, "vacancy_rate", "prophet"),
]


def _errors(actual, predicted) -> tuple[float, float]:
    a, p = np.asarray(actual, float), np.asarray(predicted, float)
    ok = ~np.isnan(a) & ~np.isnan(p)
    if ok.sum() == 0:
        return float("nan"), float("nan")
    mae = float(np.mean(np.abs(a[ok] - p[ok])))
    nz = ok & (a != 0)
    mape = float(np.mean(np.abs((a[nz] - p[nz]) / a[nz])) * 100) if nz.any() else float("nan")
    return mae, mape


def _best_baseline(history: pd.Series, actual, horizon: int) -> tuple[str, np.ndarray, float]:
    """The strongest trivial forecast for this fold, and its MAE.

    Reporting skill against the *weaker* baseline would flatter the model, so
    both are tried and the better one is the bar.
    """
    candidates = {
        "seasonal_naive": seasonal_naive(history, horizon, SEASONAL_PERIOD),
        "last_value": last_value(history, horizon),
    }
    scored = {name: _errors(actual, pred)[0] for name, pred in candidates.items()}
    name = min(scored, key=lambda k: (np.isnan(scored[k]), scored[k]))
    return name, candidates[name], scored[name]


def _fold_row(target: str, model: str, fold: int, actual, predicted, insample,
              baseline: str, baseline_mae: float) -> dict:
    mae, mape = _errors(actual, predicted)
    skill = (1 - mae / baseline_mae) if baseline_mae and np.isfinite(baseline_mae) else float("nan")
    return {
        "target": target, "model": model, "fold": fold,
        "mae": mae, "mape": mape, "mase": mase(actual, predicted, insample, SEASONAL_PERIOD),
        "baseline": baseline, "baseline_mae": baseline_mae, "skill": skill,
        "n_eval": int(np.sum(~np.isnan(np.asarray(actual, float)))),
    }


def _national_backtest(
    fact: pd.DataFrame, label: str, model_cls: type[NationalForecaster], column: str, model_name: str,
) -> tuple[list[dict], pd.DataFrame | None]:
    daily = model_cls.national_daily(fact, column)
    folds = list(expanding_time_folds(len(daily), N_FOLDS, MIN_TRAIN_DAYS, HOLDOUT_DAYS))
    rows: list[dict] = []
    series: pd.DataFrame | None = None

    for i, (train_idx, hold_idx) in enumerate(folds):
        train, hold = daily.iloc[train_idx], daily.iloc[hold_idx]
        try:
            m = model_cls(horizon_days=len(hold))
            m.fit(fact[pd.to_datetime(fact["date_key"]) <= train["ds"].max()], target=column)
            fc = m.forecast().set_index("date_key")["yhat"].reindex(hold["ds"]).values
        except Exception as exc:  # noqa: BLE001
            log.warning("validation.fold_failed", target=label, fold=i, error=str(exc))
            continue

        name, base_pred, base_mae = _best_baseline(train["y"], hold["y"].values, len(hold))
        rows.append(_fold_row(label, model_name, i, hold["y"].values, fc, train["y"].values, name, base_mae))

        if i == len(folds) - 1:
            series = pd.DataFrame({
                "target": label, "date": hold["ds"].values,
                "actual": hold["y"].values, "predicted": fc, "baseline": base_pred,
            })
    return rows, series


def _waiting_time_backtest(fact: pd.DataFrame) -> list[dict]:
    """Panel back-test: predict each trust × specialty 30 days ahead.

    Baseline is persistence — today's wait as the forecast of the wait in 30
    days — which is what a planner does without a model.
    """
    f = fact.copy()
    f["date_key"] = pd.to_datetime(f["date_key"])
    dates = f["date_key"].drop_duplicates().sort_values().reset_index(drop=True)
    folds = list(expanding_time_folds(len(dates), N_FOLDS, MIN_TRAIN_DAYS, HOLDOUT_DAYS))
    rows: list[dict] = []
    keys = ["hospital_id", "specialty_id"]

    for i, (train_idx, _hold_idx) in enumerate(folds):
        cutoff = dates.iloc[train_idx.stop - 1]
        train = f[f["date_key"] <= cutoff]
        try:
            wt = WaitingTimeForecaster(horizons=(HOLDOUT_DAYS,))
            wt.fit(train, target="median_wait_days")
            pred = wt.predict(train, horizon=HOLDOUT_DAYS)
        except Exception as exc:  # noqa: BLE001
            log.warning("validation.fold_failed", target="Waiting time", fold=i, error=str(exc))
            continue

        pred = pred.rename(columns={f"pred_{HOLDOUT_DAYS}d": "predicted"})
        pred["target_date"] = pred["date_key"] + pd.Timedelta(days=HOLDOUT_DAYS)
        pred = pred[pred["target_date"] > cutoff]  # only genuinely future targets
        current = train[["date_key", *keys, "median_wait_days"]].rename(
            columns={"median_wait_days": "persistence"})
        pred = pred.merge(current, on=["date_key", *keys], how="left")
        actual = f[["date_key", *keys, "median_wait_days"]].rename(
            columns={"date_key": "target_date", "median_wait_days": "actual"})
        merged = pred.merge(actual, on=["target_date", *keys], how="inner").dropna(subset=["actual"])
        if merged.empty:
            continue

        base_mae, _ = _errors(merged["actual"], merged["persistence"])
        rows.append(_fold_row(
            "Waiting time", "lightgbm", i, merged["actual"].values, merged["predicted"].values,
            train.groupby("date_key")["median_wait_days"].mean().values, "persistence", base_mae,
        ))
    return rows


def _aggregate(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=METRIC_COLUMNS)
    df = pd.DataFrame(rows)
    agg = (
        df.groupby(["target", "model"], as_index=False)
        .agg(
            folds=("fold", "nunique"), mae=("mae", "mean"), mae_std=("mae", "std"),
            mape=("mape", "mean"), mase=("mase", "mean"), baseline_mae=("baseline_mae", "mean"),
            skill=("skill", "mean"), n_eval=("n_eval", "sum"),
            baseline=("baseline", lambda s: s.mode().iat[0]),
        )
    )
    agg["horizon_days"] = HOLDOUT_DAYS
    agg["evaluated_at"] = pd.Timestamp.utcnow().tz_localize(None)
    for c in ("mae", "mae_std", "mape", "mase", "baseline_mae"):
        agg[c] = agg[c].astype(float).round(3)
    agg["skill"] = agg["skill"].astype(float).round(3)
    return agg[METRIC_COLUMNS]


def backtest(fact: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rolling-origin back-test of every forecaster against its best baseline."""
    rows: list[dict] = []
    series: list[pd.DataFrame] = []

    for label, cls, column, model_name in NATIONAL:
        fold_rows, s = _national_backtest(fact, label, cls, column, model_name)
        rows.extend(fold_rows)
        if s is not None:
            series.append(s)

    rows.extend(_waiting_time_backtest(fact))

    metrics = _aggregate(rows)
    fa = (pd.concat(series, ignore_index=True) if series
          else pd.DataFrame(columns=["target", "date", "actual", "predicted", "baseline"]))
    for _, r in metrics.iterrows():
        log.info("validation.result", target=r["target"], skill=r["skill"], mase=r["mase"],
                 baseline=r["baseline"], folds=int(r["folds"]))
    return metrics, fa


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
