"""Forecast chart — Plotly line with confidence band."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def forecast_chart(history: pd.DataFrame,
                  forecast: pd.DataFrame,
                  title: str = "Forecast",
                  y_title: str = "Value") -> None:
    history = history.copy()
    forecast = forecast.copy()
    history["date_key"] = pd.to_datetime(history["date_key"])
    forecast["date_key"] = pd.to_datetime(forecast["date_key"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history["date_key"], y=history.iloc[:, 1],
        name="History", line=dict(color="#94a3b8", width=2)))
    fig.add_trace(go.Scatter(
        x=forecast["date_key"], y=forecast["yhat"],
        name="Forecast", line=dict(color="#22d3ee", width=2)))
    fig.add_trace(go.Scatter(
        x=pd.concat([forecast["date_key"], forecast["date_key"][::-1]]),
        y=pd.concat([forecast["yhat_upper"], forecast["yhat_lower"][::-1]]),
        fill="toself", fillcolor="rgba(34,211,238,0.2)",
        line=dict(color="rgba(255,255,255,0)"),
        name="95% CI", showlegend=True,
    ))
    fig.update_layout(
        title=title, yaxis_title=y_title,
        template="plotly_dark", height=420,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)
