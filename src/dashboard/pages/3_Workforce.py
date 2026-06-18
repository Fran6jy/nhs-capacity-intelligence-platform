"""Workforce analytics page."""
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
    st.title("Workforce Analytics")
    st.caption("Staffing gaps, vacancy pressure, and demand projections.")

    top = con.execute(
        """
        SELECT h.hospital_name, r.region_name,
               AVG(f.vacancy_rate) AS vacancy_rate,
               SUM(f.vacancies)    AS vacancies,
               SUM(f.staff_count)  AS staff_count
        FROM hospital_activity_fact f
        JOIN dim_hospital h ON f.hospital_id = h.hospital_id
        JOIN dim_region   r ON h.region_id    = r.region_id
        WHERE f.date_key = (SELECT MAX(date_key) FROM hospital_activity_fact)
        GROUP BY h.hospital_name, r.region_name
        ORDER BY vacancy_rate DESC
        LIMIT 20
        """
    ).fetch_df()
    st.subheader("Top 20 trusts by vacancy rate")
    fig = px.bar(top, x="vacancy_rate", y="hospital_name", color="region_name",
                 orientation="h", template="plotly_dark", height=620)
    fig.update_layout(margin=dict(l=20, r=20, t=30, b=20), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Workforce demand projection (60d)")
    demand = con.execute(
        """
        SELECT date_key, AVG(yhat) AS demand_fte
        FROM ml_forecast
        WHERE target = 'workforce_demand' AND horizon_days = 60
        GROUP BY date_key
        ORDER BY date_key
        """
    ).fetch_df()
    if not demand.empty:
        fig = px.line(demand, x="date_key", y="demand_fte", template="plotly_dark", height=320)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No workforce demand forecasts available — train models first.")

    st.dataframe(top, use_container_width=True, hide_index=True)
    con.close()


if __name__ == "__main__":
    render()
