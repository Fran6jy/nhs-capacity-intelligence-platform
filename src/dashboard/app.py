"""Streamlit entry point. Configures layout and provides a sidebar nav."""
from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this script with its own directory on sys.path, not the project
# root, so make the `src` package importable regardless of launch location.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb
import streamlit as st

from src.config import settings
from src.dashboard.components.kpi_card import kpi_card
from src.llm.agents import InsightOrchestrator

st.set_page_config(
    page_title="NHS Capacity & Demand Intelligence",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def _con():
    return duckdb.connect(str(settings.warehouse_path), read_only=True)


def _sidebar():
    st.sidebar.title("🏥 NHS Capacity Platform")
    st.sidebar.caption("Predictive + Prescriptive intelligence for NHS operations")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Navigation")
    pages = [
        "Executive Overview",
        "Forecasting",
        "Workforce",
        "Risk Map",
        "AI Chat",
    ]
    st.sidebar.markdown(
        "\n".join(
            f"- [{p}]({p.replace(' ', '_')})" for p in pages
        )
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Status**")
    badge = st.sidebar.empty()
    return badge


def main() -> None:
    badge = _sidebar()
    try:
        con = _con()
        n_hosp = con.execute("SELECT COUNT(DISTINCT hospital_id) FROM dim_hospital").fetchone()[0]
        n_fact = con.execute("SELECT COUNT(*) FROM hospital_activity_fact").fetchone()[0]
        n_red = con.execute(
            "SELECT COUNT(*) FROM risk_score WHERE classification='Red'"
        ).fetchone()[0]
        con.close()
        badge.success(f"Warehouse OK — {n_hosp} trusts, {n_fact:,} fact rows, {n_red} 🔴")
    except Exception as exc:  # noqa: BLE001
        badge.error(f"Warehouse not ready: {exc}")
        st.stop()

    st.title("NHS Capacity & Demand Intelligence Platform")
    st.markdown(
        """
        Welcome — this platform shifts NHS operations from **reactive reporting**
        to **predictive + prescriptive intelligence**.

        Use the sidebar to navigate between **Executive Overview**, **Forecasting**,
        **Workforce**, **Risk Map**, and the **AI Chat** assistant.
        """
    )
    cols = st.columns(4)
    with cols[0]:
        kpi_card("Trusts monitored", f"{n_hosp}")
    with cols[1]:
        kpi_card("Fact rows (Gold)", f"{n_fact:,}")
    with cols[2]:
        kpi_card("Trusts in Red", f"{n_red}")
    with cols[3]:
        kpi_card("Forecast horizon", "30 / 60 / 90 days")

    st.markdown("### Example questions for the AI assistant")
    orchestrator = InsightOrchestrator()
    sample_qs = [
        "Why are cardiology waiting times increasing?",
        "Which hospitals are at risk of overload?",
        "Where will staffing shortages occur next?",
        "Why is A&E demand rising in the Midlands?",
    ]
    cols = st.columns(2)
    for i, q in enumerate(sample_qs):
        with cols[i % 2]:
            if st.button(q, key=f"sample_{i}"):
                with st.spinner("Running multi-agent analysis…"):
                    result = orchestrator.answer(q)
                st.session_state["chat_history"] = st.session_state.get("chat_history", []) + [
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": result.summary},
                ]
                st.rerun()


if __name__ == "__main__":
    main()
