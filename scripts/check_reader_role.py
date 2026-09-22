"""Prove the read-only role actually works before pointing the API at it.

Switching the API to a least-privilege role fails *silently* when it goes
wrong. `nhs_reader` does not own the tables, so row-level security applies to
it: if a read policy is missing, PostgreSQL returns zero rows rather than an
error, and the dashboards render empty with a healthy-looking 200. Verifying
the grants statically is not the same as observing a read.

So this connects as the role and checks both directions:

* every table returns rows through its policy, and
* a write is refused.

Configure the role's credentials separately from the owner's, so the check
never depends on which account the app happens to be using:

    READER_DB_USER=nhs_reader.<project-ref>
    READER_DB_PASSWORD=<the password you chose>

Falls back to DB_HOST/DB_PORT/DB_NAME from the normal settings, or set
READER_DATABASE_URL to give the whole URI yourself. Run:

    python scripts/check_reader_role.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()  # same .env the app reads, so DB_HOST etc. are available

#: A write attempt must fail. Nothing is committed either way — the
#: transaction is rolled back — but the statement should never get that far.
PROBE_TABLE = "dim_region"


def _reader_url() -> str | None:
    explicit = os.getenv("READER_DATABASE_URL")
    if explicit:
        return explicit

    user, password = os.getenv("READER_DB_USER"), os.getenv("READER_DB_PASSWORD")
    host = os.getenv("DB_HOST")
    if not (user and password and host):
        return None

    return (
        f"postgresql+psycopg2://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'postgres')}"
        f"?sslmode={os.getenv('DB_SSLMODE', 'require')}"
    )


def main() -> int:
    url = _reader_url()
    if not url:
        print(
            "::error::Set READER_DB_USER and READER_DB_PASSWORD (plus the existing "
            "DB_HOST), or READER_DATABASE_URL.\n"
            "  On Supabase's pooler the username must carry the project ref, e.g. "
            "READER_DB_USER=nhs_reader.<project-ref>"
        )
        return 1

    engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    failures: list[str] = []

    try:
        with engine.connect() as conn:
            who = conn.execute(text("SELECT current_user")).scalar_one()
            print(f"Connected as {who}\n")

            tables = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' ORDER BY tablename"
                    )
                )
            ]
            if not tables:
                print("::error::No tables visible at all — check GRANT USAGE ON SCHEMA public.")
                return 1

            print("Reading every table:")
            for table in tables:
                try:
                    n = conn.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()
                except SQLAlchemyError as exc:
                    failures.append(f"{table}: cannot read ({str(exc).splitlines()[0]})")
                    print(f"  {table:.<34} ERROR")
                    continue

                # Zero rows is the silent failure this script exists to catch.
                # It is only a problem for tables that actually hold data, so
                # report it and let the operator judge.
                flag = "" if n else "   <- EMPTY (missing read policy?)"
                if not n:
                    failures.append(f"{table}: 0 rows visible")
                print(f"  {table:.<34} {n:>9,}{flag}")

            print("\nChecking writes are refused:")
            trans = conn.begin()
            try:
                conn.execute(
                    text(f"INSERT INTO public.{PROBE_TABLE} (region_id, region_name, country) "
                         "VALUES ('ZZTEST', 'should not exist', 'test')")
                )
                failures.append(f"write to {PROBE_TABLE} SUCCEEDED — the role is not read-only")
                print(f"  INSERT into {PROBE_TABLE} ... ALLOWED  <- should have been refused")
            except SQLAlchemyError:
                print(f"  INSERT into {PROBE_TABLE} ... refused")
            finally:
                trans.rollback()

    except SQLAlchemyError as exc:
        print(f"::error::Could not connect as the reader role: {str(exc).splitlines()[0]}")
        return 1
    finally:
        engine.dispose()

    print()
    if failures:
        print("::error::Not safe to switch the API over yet:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(
        f"All good — {who} reads every table and cannot write.\n"
        f"Safe to point the API's DATABASE_URL at this role.\n"
        f"Keep the publisher (GitHub Actions) on the owner account: it writes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
