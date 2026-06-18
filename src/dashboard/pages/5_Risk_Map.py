"""Risk map / regional breakdown page."""
from __future__ import annotations

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import settings


@st.cache_resource
def _con():
    return duckdb.connect(str(settings.warehouse_path), read_only=True)


def render() -> None:
    con = _con()
    st.title("Risk Map — Regional Pressure")
    st.caption("Composite Operational Risk Score by region and trust.")

    regional = con.execute("SELECT * FROM v_regional_risk_latest").fetch_df()
    st.dataframe(regional, use_container_width=True, hide_index=True)

    if not regional.empty:
        fig = px.bar(
            regional.melt(id_vars=["region_name"],
                          value_vars=["red_count", "amber_count", "green_count"]),
            x="region_name", y="value", color="variable",
            barmode="group", template="plotly_dark", height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top recommendations")
    recs = con.execute(
        "SELECT * FROM recommendation ORDER BY severity, category LIMIT 50"
    ).fetch_df()
    if not recs.empty:
        st.dataframe(recs[["hospital_id", "severity", "category", "action", "expected_impact"]],
                     use_container_width=True, hide_index=True)
    else:
        st.info("No recommendations generated yet — run the recommender.")
    con.close()


if __name__ == "__main__":
    render()
