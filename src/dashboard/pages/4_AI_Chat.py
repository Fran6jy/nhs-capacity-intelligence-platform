"""AI chat interface — multi-agent insight generation."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import duckdb
import streamlit as st

from src.config import settings
from src.llm.agents import InsightOrchestrator
from src.llm.nl2sql import translate_and_run


@st.cache_resource
def _orchestrator() -> InsightOrchestrator:
    return InsightOrchestrator()


@st.cache_resource
def _con():
    return duckdb.connect(str(settings.warehouse_path), read_only=True)


def render() -> None:
    con = _con()
    st.title("🤖 AI Insights Chat")
    st.caption("Ask natural-language questions. The system plans, queries the warehouse, "
               "and synthesises an answer via the multi-agent system.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # History
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_q = st.chat_input("Ask about waiting times, A&E demand, staffing, risk…")
    if user_q:
        st.session_state.chat_history.append({"role": "user", "content": user_q})
        with st.chat_message("user"):
            st.markdown(user_q)
        with st.chat_message("assistant"):
            with st.spinner("Planning, querying, synthesising…"):
                result = _orchestrator().answer(user_q)
                st.markdown(result.summary)

                # Show evidence
                sql_result = translate_and_run(user_q)
                with st.expander("Underlying SQL"):
                    st.code(sql_result.sql, language="sql")
                with st.expander("Retrieved data"):
                    st.dataframe(sql_result.df, use_container_width=True, hide_index=True)
        st.session_state.chat_history.append(
            {"role": "assistant", "content": result.summary}
        )
    con.close()


if __name__ == "__main__":
    render()
