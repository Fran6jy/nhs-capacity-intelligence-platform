"""End-to-end pipeline.

* `bronze`  — ingest NHS / HES / WFS / ONS / flu / weather.
* `silver`  — clean, dedupe, type-coerce.
* `gold`    — build the star schema in DuckDB.
* `train`   — fit Prophet / XGBoost / LightGBM and write forecasts.
* `risk`    — compute the operational risk score.
* `recommend` — generate actionable recommendations.

Schedule: daily. If you flip to streaming, swap the bronze + silver
operators for a Kafka consumer without changing downstream tasks.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

# Make src importable when run by Airflow
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.config import settings
from src.pipeline.bronze import run as bronze_run
from src.pipeline.silver import run as silver_run
from src.pipeline.gold import run as gold_run
from src.models.training import train_all
from src.risk.risk_engine import run as risk_run
from src.llm.recommender import run as recommender_run
from src.utils.logging import get_logger

log = get_logger("airflow.dag")

default_args = {
    "owner": "nhs-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}

with DAG(
    dag_id="nhs_capacity_pipeline",
    default_args=default_args,
    description="End-to-end NHS capacity & demand pipeline (medallion + ML + risk + LLM)",
    schedule_interval="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["nhs", "medallion", "ml", "llm"],
) as dag:
    def _bronze_callable(**_):
        bronze_run()
        log.info("bronze.done")

    def _silver_callable(**_):
        silver_run()
        log.info("silver.done")

    def _gold_callable(**_):
        gold_run()
        log.info("gold.done")

    def _train_callable(**_):
        train_all()
        log.info("train.done")

    def _risk_callable(**_):
        risk_run()
        log.info("risk.done")

    def _reco_callable(**_):
        recommender_run()
        log.info("reco.done")

    t_bronze = PythonOperator(task_id="bronze", python_callable=_bronze_callable)
    t_silver = PythonOperator(task_id="silver", python_callable=_silver_callable)
    t_gold   = PythonOperator(task_id="gold",   python_callable=_gold_callable)
    t_train  = PythonOperator(task_id="train",  python_callable=_train_callable)
    t_risk   = PythonOperator(task_id="risk",   python_callable=_risk_callable)
    t_reco   = PythonOperator(task_id="recommend", python_callable=_reco_callable)

    t_bronze >> t_silver >> t_gold >> t_train >> t_risk >> t_reco
