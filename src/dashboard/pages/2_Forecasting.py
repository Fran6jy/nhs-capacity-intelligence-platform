"""Forecasting dashboard page."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import duckdb
import streamlit as st

from src.config import settings
from src.dashboard.components.forecast_chart import forecast_chart


@st.cache_resource
def _con():
    return duckdb.connect(str(settings.warehouse_path), read_only=True)


def render() -> None:
    con = _con()
    st.title("Forecasting")
    st.caption("30 / 60 / 90-day projections for bed occupancy, A&E demand, and waiting times.")

    target = st.selectbox("Target", ["bed_occupancy", "ae_demand", "waiting_time"])
    horizon = st.select_slider("Horizon (days)", options=[30, 60, 90], value=60)

    # Map the high-level target to the fact-table column for the history series.
    history_col = {
        "bed_occupancy": "bed_occupancy_pct",
        "ae_demand":     "ae_attendances",
        "waiting_time":  "median_wait_days",
    }[target]

    history = con.execute(
        f"""
        SELECT date_key, AVG({history_col}) AS value
        FROM hospital_activity_fact
        GROUP BY date_key
        ORDER BY date_key DESC
        LIMIT 180
        """
    ).fetch_df()
    # bed/ae are national-level forecasts (one row per date). Waiting-time
    # forecasts are per (hospital, specialty) — average them so the chart
    # renders a single line.
    forecast = con.execute(
        """
        SELECT date_key, AVG(yhat) AS yhat,
               AVG(yhat_lower) AS yhat_lower,
               AVG(yhat_upper) AS yhat_upper
        FROM ml_forecast
        WHERE target = ? AND horizon_days = ?
        GROUP BY date_key
        ORDER BY date_key
        """,
        [target, horizon],
    ).fetch_df()
    # Bed/A&E forecasts in training.py are written with horizon=90 only. If
    # the user picked 30/60, show the 90-day band as a proxy so the chart
    # is never empty after a successful training run.
    if forecast.empty:
        forecast = con.execute(
            """
            SELECT date_key, AVG(yhat) AS yhat,
                   AVG(yhat_lower) AS yhat_lower,
                   AVG(yhat_upper) AS yhat_upper
            FROM ml_forecast
            WHERE target = ?
            GROUP BY date_key
            ORDER BY date_key
            """,
            [target],
        ).fetch_df()
        st.caption(
            f"No forecasts at horizon={horizon}d for {target}; showing closest available."
        )

    if forecast.empty:
        st.warning("No forecasts available — run `python scripts/train_models.py` first.")
        con.close()
        return

    forecast_chart(history, forecast, title=f"{target} — {horizon}-day forecast")
    st.dataframe(forecast.tail(30), use_container_width=True, hide_index=True)
    con.close()


if __name__ == "__main__":
    render()
