"""Fetch real NHS England statistics, derive the real-data tables, and publish
them straight to PostgreSQL.

Run this from a normal network connection:

    python scripts/ingest_nhs_real.py

NHS England's WAF answers datacentre IP ranges — GitHub Actions runners among
them — with `202 Accepted` and an empty body, so the scheduled refresh cannot
collect this data. A laptop or any residential/office connection can.

What it writes (see src/pipeline/nhs_real.py):

    nhs_ae_monthly        36 months of provider-level A&E activity
    nhs_rtt_monthly       latest provider × specialty RTT waiting list
    nhs_rtt_timeseries    national RTT series, April 2007 onwards
    nhs_monthly_forecast  12-month national forecasts on the real series
    nhs_monthly_metrics   their back-test against the seasonal naive
    nhs_provider_risk     peer-relative risk across the real providers

Afterwards it re-applies the database security posture itself, because the
tables above are recreated and a recreated table loses its row-level
security; there is no longer a manual follow-up step.

Needs `DATABASE_URL` (or `DB_HOST`/`DB_USER`/`DB_PASSWORD`) for the owner
role — the same credentials the refresh workflow uses.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import db
from src.config import settings
from src.pipeline.nhs_real import ALL_TABLES, build_tables, fetch_all
from src.utils.logging import get_logger

ROOT = Path(__file__).resolve().parents[1]
log = get_logger("ingest_nhs_real")


def _harden() -> None:
    spec = importlib.util.spec_from_file_location("publish_pg", ROOT / "scripts" / "publish_to_postgres.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.harden()


def main() -> int:
    if not settings.database_url:
        print("::error::No database configured. Set DATABASE_URL, or DB_HOST, DB_USER and DB_PASSWORD.")
        return 1

    print("Fetching NHS England sources (A&E history, RTT extract, RTT time series) ...")
    sources = fetch_all()
    for name, df in sources.items():
        print(f"  {name:<22} {len(df):>7,} rows" if not df.empty else f"  {name:<22} no data returned")

    if all(df.empty for df in sources.values()):
        print("::error::Nothing fetched. If this ran from CI or a cloud host, NHS England most "
              "likely blocked it — run it from a local machine.")
        return 1

    print("Deriving forecasts, back-tests and provider risk ...")
    tables = build_tables(sources)

    published = 0
    for name in ALL_TABLES:
        df = tables.get(name)
        if df is None or df.empty:
            print(f"  {name:<22} not built — leaving any existing table untouched")
            continue
        rows = db.write_table(df, name, if_exists="replace")
        published += rows
        print(f"  {name:<22} published {rows:>7,} rows")

    if not published:
        print("::error::Nothing published.")
        return 1

    print("Re-applying the database security posture ...")
    _harden()
    log.info("ingest_nhs_real.complete", rows=published, tables=len(tables))
    print(f"Done: {published:,} rows across {len(tables)} tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
