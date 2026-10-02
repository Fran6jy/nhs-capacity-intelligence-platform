"""Real NHS England statistics, and everything derived from them.

This is the real-data spine of the platform. From three published sources —
36 months of provider-level A&E activity, the latest provider-level RTT
extract, and the national RTT time series back to 2007 — it produces:

* ``nhs_ae_monthly``        provider × month A&E activity (history)
* ``nhs_rtt_monthly``       provider × specialty RTT waiting list (latest month)
* ``nhs_rtt_timeseries``    national RTT monthly series, April 2007 →
* ``nhs_monthly_forecast``  12-month national forecasts on the real series
* ``nhs_monthly_metrics``   their rolling-origin back-test vs seasonal naive
* ``nhs_provider_risk``     peer-relative risk across the real providers

It sits alongside the synthetic daily star schema rather than inside it: NHS
England publishes monthly, and the modelling here stays at that grain so
nothing implies a precision the source cannot support.

``build_tables`` is pure — fetched frames in, named tables out — so the same
derivation runs in the DuckDB pipeline and in the local ingestion script that
writes straight to Postgres from a network NHS England does not block.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.config import settings
from src.ingestion.nhs_england import fetch_ae_monthly, fetch_rtt_monthly, fetch_rtt_timeseries
from src.models.monthly import run_all, series_from_tables
from src.risk.provider_risk import compute_provider_risk
from src.utils.logging import get_logger

log = get_logger("pipeline.nhs_real")

AE_TABLE = "nhs_ae_monthly"
RTT_TABLE = "nhs_rtt_monthly"
RTT_TS_TABLE = "nhs_rtt_timeseries"
FORECAST_TABLE = "nhs_monthly_forecast"
METRICS_TABLE = "nhs_monthly_metrics"
PROVIDER_RISK_TABLE = "nhs_provider_risk"

#: Months of A&E history to hold. Three full years gives the monthly
#: forecaster three annual cycles, which is the minimum for yearly seasonality
#: to be estimated rather than imagined.
AE_HISTORY_MONTHS = 36

ALL_TABLES = (AE_TABLE, RTT_TABLE, RTT_TS_TABLE, FORECAST_TABLE, METRICS_TABLE, PROVIDER_RISK_TABLE)


def fetch_all(ae_months: int = AE_HISTORY_MONTHS) -> dict[str, pd.DataFrame]:
    """Pull the three published sources. Each degrades to an empty frame."""
    return {
        AE_TABLE: fetch_ae_monthly(months=ae_months),
        RTT_TABLE: fetch_rtt_monthly(months=1),
        RTT_TS_TABLE: fetch_rtt_timeseries(),
    }


def build_tables(sources: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Derive forecasts, back-test metrics and provider risk from the sources.

    Returns every table that has content, sources included, keyed by name.
    Derived tables are only built when their inputs exist, and a failure in a
    derivation never discards the sources it was built from.
    """
    ae = sources.get(AE_TABLE, pd.DataFrame())
    rtt = sources.get(RTT_TABLE, pd.DataFrame())
    ts = sources.get(RTT_TS_TABLE, pd.DataFrame())
    out = {name: df for name, df in sources.items() if not df.empty}

    try:
        series = series_from_tables(ae, ts)
        if series:
            forecasts, metrics = run_all(series)
            if not forecasts.empty:
                out[FORECAST_TABLE] = forecasts
            if not metrics.empty:
                out[METRICS_TABLE] = metrics
    except Exception as exc:  # noqa: BLE001
        log.warning("nhs_real.forecast_failed", error=str(exc))

    try:
        risk = compute_provider_risk(rtt, ae)
        if not risk.empty:
            out[PROVIDER_RISK_TABLE] = risk
    except Exception as exc:  # noqa: BLE001
        log.warning("nhs_real.provider_risk_failed", error=str(exc))

    return out


def _write(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    con.register("df_in", df)
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM df_in")
    con.unregister("df_in")
    log.info("nhs_real.written", table=table, rows=len(df))
    return len(df)


def run(warehouse_path: Path | None = None, ae_months: int = AE_HISTORY_MONTHS) -> dict[str, int]:
    """Fetch, derive and persist into the DuckDB gold warehouse.

    Never raises on a source failure: tables that could not be built keep
    their previous contents, and the rest of the pipeline is unaffected.
    """
    warehouse_path = warehouse_path or settings.warehouse_path
    tables = build_tables(fetch_all(ae_months))
    con = duckdb.connect(str(warehouse_path))
    try:
        written = {name: _write(con, name, df) for name, df in tables.items()}
    finally:
        con.close()
    for name in ALL_TABLES:
        if name not in written:
            log.warning("nhs_real.skip_empty", table=name)
    log.info("nhs_real.complete", **written)
    return written


if __name__ == "__main__":
    run()
