"""KPI card component for Streamlit."""
from __future__ import annotations

import streamlit as st


def kpi_card(label: str, value: str, delta: str | None = None, help: str | None = None) -> None:
    delta_html = (
        f"<div style='font-size:0.8em;color:#94a3b8;margin-top:0.2em'>{delta}</div>"
        if delta else ""
    )
    help_html = f"<span title='{help}'>ℹ️</span>" if help else ""
    st.markdown(
        f"""
        <div style='background:#0f172a;border:1px solid #1e293b;border-radius:12px;
                    padding:1.1em;height:100%'>
          <div style='color:#94a3b8;font-size:0.85em;letter-spacing:0.05em;
                      text-transform:uppercase'>{label} {help_html}</div>
          <div style='color:#f8fafc;font-size:1.9em;font-weight:600;
                      margin-top:0.3em'>{value}</div>
          {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
