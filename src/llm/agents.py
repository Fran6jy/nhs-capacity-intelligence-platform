"""Multi-agent system — Forecast, Workforce, Risk, Executive agents.

Each agent has a focused prompt, knows which warehouse queries to run,
and produces a *short* structured response. The Executive agent then
synthesises the agent outputs into a final answer.

This module is intentionally LLM-agnostic: if `OPENAI_API_KEY` is not
set, the agents fall back to a no-op implementation that explains
its reasoning with deterministic text from the data.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from src.config import settings
from src.llm.rag import get_llm
from src.llm.prompts import SYSTEM_AGENT_PLANNER, SYSTEM_INSIGHT
from src.utils.logging import get_logger

log = get_logger("agents")


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(settings.warehouse_path), read_only=True)


# --------------------------------------------------------------------------- #
# Agent contracts
# --------------------------------------------------------------------------- #

@dataclass
class AgentResult:
    agent: str
    summary: str
    evidence: dict[str, Any]


class _BaseAgent:
    name: str = "base"

    def run(self, question: str) -> AgentResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Implementations
# --------------------------------------------------------------------------- #

class ForecasterAgent(_BaseAgent):
    name = "ForecasterAgent"

    def run(self, question: str) -> AgentResult:
        con = _con()
        df = con.execute(
            """
            SELECT target, horizon_days, AVG(yhat) AS yhat
            FROM ml_forecast
            WHERE date_key >= (SELECT MAX(date_key) FROM ml_forecast) - INTERVAL '7 day'
            GROUP BY target, horizon_days
            ORDER BY target, horizon_days
            """
        ).fetch_df()
        con.close()
        summary_lines = []
        for _, r in df.iterrows():
            summary_lines.append(
                f"{r.target} @ horizon {r.horizon_days}d ≈ {r.yhat:.1f}"
            )
        return AgentResult(
            agent=self.name,
            summary="\n".join(summary_lines) or "No forecasts available.",
            evidence=df.to_dict(orient="records"),
        )


class WorkforceAgent(_BaseAgent):
    name = "WorkforceAgent"

    def run(self, question: str) -> AgentResult:
        con = _con()
        df = con.execute(
            """
            SELECT h.hospital_name, AVG(f.vacancy_rate) AS vacancy_rate,
                   SUM(f.vacancies) AS vacancies, SUM(f.staff_count) AS staff_count
            FROM hospital_activity_fact f
            JOIN dim_hospital h ON f.hospital_id = h.hospital_id
            WHERE f.date_key = (SELECT MAX(date_key) FROM hospital_activity_fact)
            GROUP BY h.hospital_name
            ORDER BY vacancy_rate DESC
            LIMIT 5
            """
        ).fetch_df()
        con.close()
        summary = "Top 5 trusts by vacancy pressure:\n" + df.to_string(index=False)
        return AgentResult(agent=self.name, summary=summary,
                            evidence=df.to_dict(orient="records"))


class RiskAgent(_BaseAgent):
    name = "RiskAgent"

    def run(self, question: str) -> AgentResult:
        con = _con()
        df = con.execute(
            "SELECT * FROM v_top_risk_trusts"
        ).fetch_df()
        n_red = con.execute(
            "SELECT COUNT(*) FROM risk_score WHERE classification='Red' AND date_key=(SELECT MAX(date_key) FROM risk_score)"
        ).fetchone()[0]
        con.close()
        return AgentResult(
            agent=self.name,
            summary=f"{n_red} trusts in Red. Top: {df.head(3).to_dict(orient='records')}",
            evidence={"n_red": n_red, "top": df.to_dict(orient="records")},
        )


class ExecutiveAgent(_BaseAgent):
    name = "ExecutiveAgent"

    def __init__(self, llm=None) -> None:
        self.llm = llm or get_llm()

    def run(self, question: str, other_outputs: list[AgentResult]) -> AgentResult:
        context = "\n\n".join(
            f"[{o.agent}]\n{o.summary}" for o in other_outputs
        )
        try:
            resp = self.llm.invoke([
                {"role": "system", "content": SYSTEM_INSIGHT},
                {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
            ])
            final = resp.content
        except Exception as exc:  # noqa: BLE001
            log.warning("agents.executive_llm_failed", error=str(exc))
            final = (
                "**Explanation:** " + other_outputs[0].summary.splitlines()[0] + "\n\n"
                "**Quantified insight:** see context above.\n\n"
                "**Forecast:** trend continues in the absence of intervention.\n\n"
                "**Recommendations:**\n"
                "- Open surge capacity.\n- Review staffing hot-spots.\n"
            )
        return AgentResult(agent=self.name, summary=final,
                            evidence={"context": context})


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #

class InsightOrchestrator:
    """Decompose a question into agent calls and synthesise an answer."""

    def __init__(self) -> None:
        self.agents: dict[str, _BaseAgent] = {
            "ForecasterAgent": ForecasterAgent(),
            "WorkforceAgent":  WorkforceAgent(),
            "RiskAgent":       RiskAgent(),
        }
        self.executive = ExecutiveAgent()

    def _plan(self, question: str) -> list[dict]:
        """Return a list of {"agent": ..., "task": ...} dicts."""
        try:
            llm = get_llm()
            resp = llm.invoke([
                {"role": "system", "content": SYSTEM_AGENT_PLANNER},
                {"role": "user", "content": question},
            ])
            plan_text = resp.content
            # Pull the first JSON list out of the response
            match = re.search(r"\[[\s\S]*\]", plan_text)
            if match:
                plan = json.loads(match.group(0))
                return [p for p in plan if p.get("agent") in self.agents]
        except Exception as exc:  # noqa: BLE001
            log.warning("agents.planner_failed", error=str(exc))

        # Heuristic fallback
        q = question.lower()
        chosen = []
        if "wait" in q or "forecast" in q or "ae" in q or "bed" in q:
            chosen.append({"agent": "ForecasterAgent", "task": "explain projections"})
        if "staff" in q or "workforce" in q or "nurse" in q or "doctor" in q:
            chosen.append({"agent": "WorkforceAgent", "task": "explain staffing"})
        if "risk" in q or "overload" in q or "pressure" in q or "red" in q:
            chosen.append({"agent": "RiskAgent", "task": "explain risk score"})
        if not chosen:
            chosen = [{"agent": "RiskAgent", "task": "default overview"}]
        return chosen

    def answer(self, question: str) -> AgentResult:
        log.info("agents.answer", question=question)
        plan = self._plan(question)
        outputs: list[AgentResult] = []
        for step in plan:
            agent = self.agents[step["agent"]]
            outputs.append(agent.run(question))
        return self.executive.run(question, outputs)
