"""Load real NHS England monthly statistics into the gold warehouse.

This sits alongside the synthetic daily star schema rather than inside it. The
two have genuinely different grains — NHS England publishes monthly, per
provider, while the modelling layer needs daily data for forecasting, the risk
engine and the A&E digital twin — and collapsing one into the other would
either destroy the daily signal or silently imply a precision the published
data does not have.

Keeping them separate means the Evidence & Validation page can state plainly
which figures are real and which are modelled.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.config import settings
from src.ingestion.nhs_england import fetch_ae_monthly, fetch_rtt_monthly
from src.utils.logging import get_logger

log = get_logger("pipeline.nhs_real")

RTT_TABLE = "nhs_rtt_monthly"
AE_TABLE = "nhs_ae_monthly"


def _write(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    if df.empty:
        log.warning("nhs_real.skip_empty", table=table)
        return 0
    con.register("df_in", df)
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM df_in")
    con.unregister("df_in")
    log.info("nhs_real.written", table=table, rows=len(df))
    return len(df)


def run(warehouse_path: Path | None = None, ae_months: int = 3) -> dict[str, int]:
    """Fetch and persist the real monthly releases.

    Never raises on a source failure: the published tables simply keep their
    previous contents, and the rest of the pipeline is unaffected.
    """
    warehouse_path = warehouse_path or settings.warehouse_path
    con = duckdb.connect(str(warehouse_path))
    try:
        written = {
            AE_TABLE: _write(con, AE_TABLE, fetch_ae_monthly(months=ae_months)),
            RTT_TABLE: _write(con, RTT_TABLE, fetch_rtt_monthly(months=1)),
        }
    finally:
        con.close()

    log.info("nhs_real.complete", **written)
    return written


if __name__ == "__main__":
    run()
