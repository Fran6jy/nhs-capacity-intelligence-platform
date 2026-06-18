"""Executive overview page."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import settings
from src.dashboard.components.kpi_card import kpi_card
from src.dashboard.components.stream_panel import render_stream_panel


@st.cache_resource
def _con():
    return duckdb.connect(str(settings.warehouse_path), read_only=True)


def render() -> None:
    con = _con()
    st.title("Executive Overview — National Demand Pressure")
    st.caption("Latest operational state across all monitored NHS trusts.")

    pressure = con.execute("SELECT * FROM v_national_pressure ORDER BY date_key DESC LIMIT 90").fetch_df()
    pressure["date_key"] = pd.to_datetime(pressure["date_key"])
    pressure = pressure.sort_values("date_key")

    risk = con.execute(
        """
        SELECT classification, COUNT(*) AS n
        FROM risk_score
        WHERE date_key = (SELECT MAX(date_key) FROM risk_score)
        GROUP BY classification
        """
    ).fetch_df()

    latest = pressure.iloc[-1]

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        kpi_card("Latest date", str(latest.date_key.date()))
    with c2:
        kpi_card("A&E attendances", f"{int(latest.ae_attendances):,}")
    with c3:
        kpi_card("Avg bed occupancy", f"{latest.avg_bed_occupancy_pct:.1f}%")
    with c4:
        kpi_card("Total waiting list", f"{int(latest.total_waiting_list):,}")
    with c5:
        kpi_card("Avg vacancy rate", f"{latest.avg_vacancy_rate:.1f}%")

    st.subheader("Bed occupancy — last 90 days")
    fig = px.line(pressure, x="date_key", y="avg_bed_occupancy_pct",
                  template="plotly_dark", height=320)
    fig.update_layout(margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Operational risk distribution")
    cols = st.columns(3)
    color_map = {"Green": "#16a34a", "Amber": "#f59e0b", "Red": "#dc2626"}
    for label, col in zip(["Red", "Amber", "Green"], cols, strict=False):
        n = int(risk.loc[risk.classification == label, "n"].sum() or 0)
        col.markdown(
            f"<div style='background:{color_map[label]};color:#fff;padding:1.2em;"
            f"border-radius:12px;text-align:center;font-size:1.4em;font-weight:600'>"
            f"{label} · {n}</div>",
            unsafe_allow_html=True,
        )

    st.subheader("Top 10 at-risk trusts")
    top = con.execute("SELECT * FROM v_top_risk_trusts").fetch_df()
    st.dataframe(top, use_container_width=True, hide_index=True)

    st.divider()
    render_stream_panel()
    # NB: `con` is a cached_resource shared across reruns — do not close it here.


if __name__ == "__main__":
    render()
