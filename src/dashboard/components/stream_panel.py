"""Live A&E pressure panel — reads the real-time `ae_stream_agg` table.

Self-contained: opens its own short-lived read-only connection so it always
reflects the latest committed micro-batches, and degrades gracefully (a hint to
run the simulator) when the streaming table doesn't exist yet.
"""
from __future__ import annotations

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import settings


def _stream_table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'ae_stream_agg'"
        ).fetchone()[0]
    )


def render_stream_panel(window_minutes: int = 60) -> None:
    st.subheader("🔴 Live A&E pressure (real-time stream)")

    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        if not _stream_table_exists(con):
            st.info(
                "No live stream data yet. Start the real-time ingester:\n\n"
                "```bash\npython scripts/run_stream_sim.py --events 3000 --rate 1500\n```",
                icon="📡",
            )
            return

        agg = con.execute(
            """
            SELECT minute_ts, hospital_id, region_id,
                   attendances, ambulance, high_acuity, breach_risk
            FROM ae_stream_agg
            """
        ).fetch_df()
    finally:
        con.close()

    if agg.empty:
        st.info("Stream table is empty — run the simulator to populate it.", icon="📡")
        return

    agg["minute_ts"] = pd.to_datetime(agg["minute_ts"])
    cutoff = agg["minute_ts"].max() - pd.Timedelta(minutes=window_minutes)
    recent = agg[agg["minute_ts"] >= cutoff]

    total = int(recent["attendances"].sum())
    amb = int(recent["ambulance"].sum())
    breaches = int(recent["breach_risk"].sum())
    breach_pct = (breaches / total * 100) if total else 0.0
    amb_pct = (amb / total * 100) if total else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Attendances (last {window_minutes}m)", f"{total:,}")
    c2.metric("Ambulance arrivals", f"{amb:,}", f"{amb_pct:.0f}% of arrivals")
    c3.metric("4-hour breach risk", f"{breaches:,}", f"{breach_pct:.0f}% of arrivals",
              delta_color="inverse")
    c4.metric("Sites streaming", f"{recent['hospital_id'].nunique():,}")

    left, right = st.columns([2, 1])
    with left:
        ts = (
            recent.groupby("minute_ts", as_index=False)
            .agg(attendances=("attendances", "sum"), breach_risk=("breach_risk", "sum"))
        )
        fig = px.area(
            ts, x="minute_ts", y="attendances", template="plotly_dark", height=300,
            title="A&E arrivals per minute",
        )
        fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)
    with right:
        by_hosp = (
            recent.groupby("hospital_id", as_index=False)["breach_risk"].sum()
            .sort_values("breach_risk", ascending=False).head(10)
        )
        fig2 = px.bar(
            by_hosp, x="breach_risk", y="hospital_id", orientation="h",
            template="plotly_dark", height=300, title="Breach-risk arrivals by site",
            color="breach_risk", color_continuous_scale="Reds",
        )
        fig2.update_layout(margin=dict(l=20, r=20, t=40, b=20),
                           yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)
