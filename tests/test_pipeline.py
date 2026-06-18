"""End-to-end pipeline test using synthetic data."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings
from src.pipeline.bronze import run as bronze_run
from src.pipeline.silver import run as silver_run
from src.pipeline.gold import run as gold_run


@pytest.fixture(scope="module")
def warehouse_path(tmp_path_factory) -> Path:
    """Run the pipeline once for the test session and return the warehouse path."""
    work = tmp_path_factory.mktemp("nhs")
    start = date(2025, 1, 1)
    end = start + timedelta(days=120)
    settings.bronze_path = work / "raw"
    settings.silver_path = work / "processed"
    settings.gold_path = work / "gold"
    settings.warehouse_path = work / "gold" / "warehouse.duckdb"
    settings.bronze_path.mkdir(parents=True, exist_ok=True)

    bronze_run(start, end)
    silver_run()
    gold_run()
    return settings.warehouse_path


def test_warehouse_has_fact_rows(warehouse_path):
    con = duckdb.connect(str(warehouse_path), read_only=True)
    n = con.execute("SELECT COUNT(*) FROM hospital_activity_fact").fetchone()[0]
    con.close()
    assert n > 0


def test_dim_date_complete(warehouse_path):
    con = duckdb.connect(str(warehouse_path), read_only=True)
    rows = con.execute("SELECT MIN(date_key), MAX(date_key), COUNT(*) FROM dim_date").fetchone()
    con.close()
    start, end, n = rows
    assert (end - start).days + 1 == n  # every day present


def test_views_exist(warehouse_path):
    con = duckdb.connect(str(warehouse_path), read_only=True)
    for view in ("v_national_pressure", "v_top_risk_trusts", "v_forecast_long"):
        # DuckDB stores views in duckdb_views
        present = con.execute(
            "SELECT COUNT(*) FROM duckdb_views WHERE view_name = ?", [view]
        ).fetchone()[0]
        assert present == 1, f"View {view} missing"
    con.close()
