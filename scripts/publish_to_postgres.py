"""Publish the gold warehouse into PostgreSQL.

The offline batch pipeline builds the medallion gold tables in DuckDB (proven,
fast, laptop-friendly). This step migrates them into PostgreSQL — the
system-of-record the FastAPI backend serves from.

    DATABASE_URL=postgresql+psycopg2://nhs@host:5432/nhs_warehouse \
        python scripts/publish_to_postgres.py

Idempotent: each table is replaced. Schema + analytics views are (re)created
from the same SQL the DuckDB build uses (the DDL is Postgres-compatible).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from src import db
from src.config import settings
from src.utils.logging import get_logger

log = get_logger("publish_pg")

# Gold tables to migrate. Views are rebuilt from SQL, not copied.
TABLES = [
    "dim_date", "dim_hospital", "dim_specialty", "dim_region",
    "hospital_activity_fact", "ml_forecast", "risk_score", "recommendation",
]
OPTIONAL_TABLES = ["ae_stream_agg", "ae_dept_state"]  # present after the streaming sim runs

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _duck() -> duckdb.DuckDBPyConnection:
    if not settings.warehouse_path.exists():
        raise SystemExit(
            f"DuckDB warehouse not found at {settings.warehouse_path}. "
            "Run `python scripts/run_pipeline.py` first."
        )
    return duckdb.connect(str(settings.warehouse_path), read_only=True)


def main() -> int:
    engine = db.get_engine()  # validates DATABASE_URL early
    log.info("publish.start", target=str(engine.url).rsplit("@", 1)[-1])

    # 1) schema — typed tables with PK/FK constraints (idempotent)
    db.execute_script((SQL_DIR / "01_warehouse.sql").read_text(encoding="utf-8"))

    # 2) drop views (they depend on the tables we're about to truncate) and
    #    clear all tables in one CASCADE so we can reload deterministically.
    from sqlalchemy import text
    with db.get_engine().begin() as conn:
        for v in ("v_national_pressure", "v_regional_risk_latest",
                  "v_forecast_long", "v_top_risk_trusts"):
            conn.execute(text(f"DROP VIEW IF EXISTS {v} CASCADE"))
        conn.execute(text(f"TRUNCATE TABLE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))

    # 3) load gold tables in FK-safe order (dims -> fact -> analytics), appending
    #    into the typed schema created in step 1.
    con = _duck()
    duck_tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables"
    ).fetchall()}
    for tbl in TABLES:
        if tbl not in duck_tables:
            log.warning("publish.missing_table", table=tbl)
            continue
        df = con.execute(f"SELECT * FROM {tbl}").fetch_df()
        db.write_table(df, tbl, if_exists="append")
        log.info("publish.loaded", table=tbl, rows=len(df))

    # optional streaming aggregate — no FK, so a plain replace is fine
    for tbl in OPTIONAL_TABLES:
        if tbl in duck_tables:
            df = con.execute(f"SELECT * FROM {tbl}").fetch_df()
            db.write_table(df, tbl, if_exists="replace")
            log.info("publish.loaded", table=tbl, rows=len(df))
    con.close()

    # 4) analytics views (depend on the now-populated tables)
    db.execute_script((SQL_DIR / "02_analytics_views.sql").read_text(encoding="utf-8"))
    log.info("publish.complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
