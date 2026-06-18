"""Risk classification badge."""
from __future__ import annotations

import streamlit as st

_COLORS = {
    "Green": ("#16a34a", "🟢"),
    "Amber": ("#f59e0b", "🟡"),
    "Red":   ("#dc2626", "🔴"),
}


def risk_badge(label: str, score: float | None = None) -> None:
    color, dot = _COLORS.get(label, ("#64748b", "•"))
    score_text = f" · {score:.2f}" if score is not None else ""
    st.markdown(
        f"<span style='background:{color};color:#fff;padding:0.2em 0.6em;"
        f"border-radius:6px;font-weight:600'>{dot} {label}{score_text}</span>",
        unsafe_allow_html=True,
    )
