"""Fetch real NHS England statistics and publish them straight to PostgreSQL.

Run this from a normal network connection:

    python scripts/ingest_nhs_real.py

NHS England's WAF answers datacentre IP ranges — GitHub Actions runners among
them — with `202 Accepted` and an empty body, so the scheduled refresh cannot
collect this data. A laptop or any residential/office connection can. The rest
of the pipeline is unaffected either way; this script only replaces the two
real-data tables, so it is safe to run at any time and as often as you like.

Needs `DATABASE_URL` (or `DB_HOST`/`DB_USER`/`DB_PASSWORD`) pointing at the
warehouse — the same credentials the refresh workflow uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import db
from src.config import settings
from src.ingestion.nhs_england import fetch_ae_monthly, fetch_rtt_monthly
from src.pipeline.nhs_real import AE_TABLE, RTT_TABLE
from src.utils.logging import get_logger

log = get_logger("ingest_nhs_real")


def main() -> int:
    if not settings.database_url:
        print(
            "::error::No database configured. Set DATABASE_URL, or DB_HOST, "
            "DB_USER and DB_PASSWORD."
        )
        return 1

    datasets = [
        (AE_TABLE, "A&E activity", lambda: fetch_ae_monthly(months=3)),
        (RTT_TABLE, "RTT waiting list", lambda: fetch_rtt_monthly(months=1)),
    ]

    published = 0
    for table, label, fetch in datasets:
        print(f"Fetching {label} ...")
        df = fetch()
        if df.empty:
            print(f"  no data returned for {label} — leaving {table} untouched")
            continue

        rows = db.write_table(df, table, if_exists="replace")
        published += rows
        print(f"  published {rows:,} rows to {table} ({df['period'].nunique()} month(s))")

    if not published:
        print(
            "::error::Nothing published. If this ran from CI or a cloud host, "
            "NHS England most likely blocked it — try from a local machine."
        )
        return 1

    log.info("ingest_nhs_real.complete", rows=published)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
