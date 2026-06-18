"""PostgreSQL data-access layer (SQLAlchemy).

The platform's system-of-record is PostgreSQL. The connection target is taken
from ``DATABASE_URL`` (e.g. a managed Azure/RDS/Supabase instance):

    postgresql+psycopg2://user:pass@host:5432/nhs_warehouse

A single process-wide engine with a connection pool is created lazily, so the
FastAPI backend, the publisher, and any scripts share pooled connections.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from src.config import settings
from src.utils.logging import get_logger

log = get_logger("db")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = settings.database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at your PostgreSQL instance, e.g. "
            "postgresql+psycopg2://nhs@localhost:5432/nhs_warehouse"
        )
    log.info("db.engine_init", url=url.rsplit("@", 1)[-1])  # log host only, never creds
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame."""
    with get_engine().connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


def execute_script(sql: str) -> int:
    """Execute a multi-statement SQL script in one transaction."""
    from src.utils.io import split_sql_statements

    count = 0
    with get_engine().begin() as conn:
        for stmt in split_sql_statements(sql):
            conn.execute(text(stmt))
            count += 1
    return count


def write_table(df: pd.DataFrame, table: str, if_exists: str = "append") -> int:
    """Bulk-load a DataFrame into a table (multi-row inserts)."""
    with get_engine().begin() as conn:
        df.to_sql(table, conn, if_exists=if_exists, index=False, method="multi", chunksize=1000)
    return len(df)


def table_exists(table: str) -> bool:
    row = read_sql(
        "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_name = :t",
        {"t": table},
    )
    return bool(row.iloc[0]["n"])
