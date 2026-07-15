"""Fail fast when the Supabase DATABASE_URL secret is invalid."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def _safe_target(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "<missing-host>"
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.path.lstrip("/") or "<missing-database>"
    return f"{host}{port}/{database}"


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("::error::DATABASE_URL secret is not set.")
        return 1

    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgresql"):
        print("::error::DATABASE_URL must use a postgresql scheme.")
        return 1
    if not parsed.username or not parsed.password or not parsed.hostname:
        print("::error::DATABASE_URL must include username, password, and host.")
        return 1

    target = _safe_target(database_url)
    print(f"Checking database connection to {target}")

    engine = create_engine(database_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except SQLAlchemyError as exc:
        print(f"::error::Database preflight failed for {target}: {exc}")
        return 1
    finally:
        engine.dispose()

    print(f"Database preflight passed for {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
