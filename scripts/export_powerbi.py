"""Export the gold warehouse to an Excel workbook for Power BI (offline import).

A fallback to the live PostgreSQL connection: one .xlsx with a sheet per
view/table, importable via Power BI's Get data -> Excel (no DB handshake/SSL).

    python scripts/export_powerbi.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import pandas as pd

from src.config import settings
from src.utils.logging import get_logger

log = get_logger("export_powerbi")

SHEETS = {
    "v_national_pressure": "SELECT * FROM v_national_pressure",
    "v_regional_risk": "SELECT * FROM v_regional_risk_latest",
    "v_top_risk_trusts": "SELECT * FROM v_top_risk_trusts",
    "v_forecast_long": "SELECT * FROM v_forecast_long",
    "recommendation": "SELECT * FROM recommendation",
    "dim_region": "SELECT * FROM dim_region",
    "dim_hospital": "SELECT * FROM dim_hospital",
    "ae_dept_state": "SELECT * FROM ae_dept_state",
    "model_metrics": "SELECT * FROM model_metrics",
    "model_forecast_actual": "SELECT * FROM model_forecast_actual",
}


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "powerbi" / "nhs_powerbi_data.xlsx"
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        for name, q in SHEETS.items():
            try:
                df = con.execute(q).fetch_df()
                for c in df.columns:  # Excel can't store tz-aware datetimes
                    if str(df[c].dtype).startswith("datetime64") and getattr(df[c].dt, "tz", None) is not None:
                        df[c] = df[c].dt.tz_localize(None)
                df.to_excel(xl, sheet_name=name[:31], index=False)
                log.info("export.sheet", name=name, rows=len(df))
            except Exception as exc:  # noqa: BLE001
                log.warning("export.skip", name=name, error=str(exc)[:60])
    con.close()
    log.info("export.complete", path=str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
