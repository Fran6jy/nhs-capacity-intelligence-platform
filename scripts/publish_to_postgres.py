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

import re
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
OPTIONAL_TABLES = [
    "ae_stream_agg", "ae_dept_state",   # present after the streaming sim runs
    "model_metrics", "model_forecast_actual",  # present after validation runs
    "nhs_rtt_monthly", "nhs_ae_monthly",  # real NHS England open statistics
]

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

#: Read-only role the API may connect as. Created out-of-band (it needs a
#: password); the grants and policies below are re-applied here so they survive
#: a reload. Absent in local/dev databases, which is fine — it is skipped.
READER_ROLE = "nhs_reader"

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def harden() -> None:
    """Re-apply row-level security and grants after a load.

    Publishing drops and recreates the optional tables, and a dropped table
    takes its RLS setting and every policy with it. Left to a one-off manual
    script, the database therefore drifts back towards being readable through
    the anon key a little more with each refresh — silently, because nothing
    fails.

    So the posture is declared here and re-asserted on every publish:

    * the PostgREST roles (`anon`, `authenticated`) hold no grants — nothing in
      this project uses the Supabase client libraries;
    * RLS is on everywhere, so a future grant cannot quietly open a table;
    * `nhs_reader`, if it exists, keeps a SELECT grant and a read policy. It is
      not the table owner, so without a policy it would read zero rows.

    Idempotent, and safe on a database where the reader role was never created.
    """
    from sqlalchemy import text

    with db.get_engine().begin() as conn:
        conn.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated"))
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "REVOKE ALL ON TABLES FROM anon, authenticated"
            )
        )

        has_reader = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": READER_ROLE}
        ).first()

        tables = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
        ]

        for table in tables:
            if not _IDENT.match(table):  # defensive: identifiers are interpolated below
                log.warning("publish.skip_odd_identifier", table=table)
                continue

            conn.execute(text(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY"))
            if has_reader:
                conn.execute(text(f"GRANT SELECT ON public.{table} TO {READER_ROLE}"))
                conn.execute(
                    text(f"DROP POLICY IF EXISTS {READER_ROLE}_read ON public.{table}")
                )
                conn.execute(
                    text(
                        f"CREATE POLICY {READER_ROLE}_read ON public.{table} "
                        f"FOR SELECT TO {READER_ROLE} USING (true)"
                    )
                )

        if has_reader:
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {READER_ROLE}"))

    log.info("publish.hardened", tables=len(tables), reader_role=bool(has_reader))


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

    # 5) re-apply the security posture, which the load above partly destroys
    harden()

    log.info("publish.complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
