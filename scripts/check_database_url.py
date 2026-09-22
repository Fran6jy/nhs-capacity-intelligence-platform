"""Fail fast when the Supabase DATABASE_URL secret is invalid."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def _safe_target(url: str) -> str:
    """Describe the connection target without revealing the password.

    The username is included deliberately: it is not a secret, and the single
    most common misconfiguration here is a username the error message alone
    cannot distinguish from a wrong password.
    """
    parsed = urlparse(url)
    user = parsed.username or "<missing-user>"
    host = parsed.hostname or "<missing-host>"
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.path.lstrip("/") or "<missing-database>"
    return f"{user}@{host}{port}/{database}"


def _check_pooler_username(username: str, hostname: str) -> str | None:
    """Return an error message when a pooler URI uses a bare username.

    Supabase's session pooler multiplexes every project through one hostname,
    so it identifies the project from the username: it must be
    ``postgres.<project-ref>``. Connecting as plain ``postgres`` is rejected
    with *"password authentication failed"* — which sends you off rotating a
    password that was never the problem. This outage cost two months of stale
    data, so catch it before we connect.
    """
    if "pooler.supabase.com" not in hostname:
        return None
    if "." in username:
        return None
    return (
        f"DATABASE_URL uses the session pooler ({hostname}) with username "
        f"'{username}'. The pooler requires the project ref appended: "
        f"'{username}.<project-ref>'. A bare username is rejected as a "
        "password failure even when the password is correct."
    )


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

    pooler_problem = _check_pooler_username(parsed.username, parsed.hostname)
    if pooler_problem:
        print(f"::error::{pooler_problem}")
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
