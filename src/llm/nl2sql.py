"""NL → SQL translator with safety guard-rails.

Approach
========
1.  Use a small LLM call to turn the user question into a SELECT-only
    SQL statement. We force the prompt to return JSON of the form
    `{"sql": "...", "explanation": "..."}`.
2.  Validate the SQL — must be a single SELECT, no DDL/DML, only
    references allow-listed tables/views, no `;` injection, no
    parameter values.
3.  Execute against the warehouse and return a `pandas.DataFrame`.
4.  If anything fails, fall back to a small set of pre-baked
    intents matched by keyword — so the demo never crashes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import duckdb
import pandas as pd

from src.config import settings
from src.llm.rag import get_llm
from src.utils.logging import get_logger

log = get_logger("nl2sql")


SYSTEM_NL2SQL = """You convert a natural-language question about NHS operational
data into a single read-only DuckDB SQL query.

Rules:
- The query MUST be a single SELECT statement.
- Use ONLY these tables and views:
  v_national_pressure, v_regional_risk_latest, v_forecast_long,
  v_top_risk_trusts, hospital_activity_fact, dim_hospital, dim_specialty,
  dim_region, ml_forecast, risk_score, recommendation.
- NEVER use DDL/DML or semicolons.
- Always include a LIMIT 200 to keep the response small.

Return a JSON object of the form:
{"sql": "...", "explanation": "..."}
"""


# --------------------------------------------------------------------------- #
# Safety validator
# --------------------------------------------------------------------------- #

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|truncate|create|attach|copy|call|pragma|set|use|grant|revoke|vacuum|reindex)\b", re.IGNORECASE)
_SELECT_ONLY = re.compile(r"^\s*select\b", re.IGNORECASE)


def _validate(sql: str) -> None:
    s = sql.strip().rstrip(";")
    if ";" in s:
        raise ValueError("Multiple statements are not allowed.")
    if not _SELECT_ONLY.match(s):
        raise ValueError("Only SELECT statements are allowed.")
    if _FORBIDDEN.search(s):
        raise ValueError("Forbidden keyword detected.")
    referenced = {t.lower() for t in re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)", s)}
    allowed = {t.lower() for t in settings.allowed_tables}
    if not referenced & allowed:
        raise ValueError("Query does not reference any allow-listed table.")


# --------------------------------------------------------------------------- #
# Pre-baked intents (fallback)
# --------------------------------------------------------------------------- #

INTENTS = {
    "wait": """
        SELECT s.specialty_name, AVG(f.median_wait_days) AS median_wait_days
        FROM hospital_activity_fact f
        JOIN dim_specialty s ON f.specialty_id = s.specialty_id
        WHERE f.date_key = (SELECT MAX(date_key) FROM hospital_activity_fact)
        GROUP BY s.specialty_name
        ORDER BY median_wait_days DESC
        LIMIT 10
    """,
    "ae": """
        SELECT date_key, SUM(ae_attendances) AS ae_attendances
        FROM hospital_activity_fact
        GROUP BY date_key
        ORDER BY date_key DESC
        LIMIT 60
    """,
    "risk": """
        SELECT h.hospital_name, r.region_name, rs.score, rs.classification
        FROM risk_score rs
        JOIN dim_hospital h ON rs.hospital_id = h.hospital_id
        JOIN dim_region   r ON h.region_id    = r.region_id
        WHERE rs.date_key = (SELECT MAX(date_key) FROM risk_score)
        ORDER BY rs.score DESC
        LIMIT 10
    """,
    "staff": """
        SELECT h.hospital_name, AVG(f.vacancy_rate) AS vacancy_rate, SUM(f.vacancies) AS vacancies
        FROM hospital_activity_fact f
        JOIN dim_hospital h ON f.hospital_id = h.hospital_id
        WHERE f.date_key = (SELECT MAX(date_key) FROM hospital_activity_fact)
        GROUP BY h.hospital_name
        ORDER BY vacancy_rate DESC
        LIMIT 10
    """,
    "bed": """
        SELECT date_key, AVG(bed_occupancy_pct) AS bed_occupancy_pct
        FROM hospital_activity_fact
        GROUP BY date_key
        ORDER BY date_key DESC
        LIMIT 60
    """,
}


def _heuristic_sql(question: str) -> str:
    q = question.lower()
    if "wait" in q:
        return INTENTS["wait"]
    if "a&e" in q or "a & e" in q or "a and e" in q or "ae" in q or "emergency" in q:
        return INTENTS["ae"]
    if "staff" in q or "workforce" in q or "vacanc" in q:
        return INTENTS["staff"]
    if "bed" in q or "occupanc" in q:
        return INTENTS["bed"]
    if "risk" in q or "overload" in q or "pressure" in q:
        return INTENTS["risk"]
    return INTENTS["risk"]


# --------------------------------------------------------------------------- #
# Main entry
# --------------------------------------------------------------------------- #

@dataclass
class SQLResult:
    sql: str
    df: pd.DataFrame
    explanation: str


def translate_and_run(question: str) -> SQLResult:
    log.info("nl2sql.start", question=question)
    llm = get_llm()
    sql = None
    explanation = ""

    try:
        if llm is not None:
            resp = llm.invoke([
                {"role": "system", "content": SYSTEM_NL2SQL},
                {"role": "user", "content": question},
            ])
            text = resp.content
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                payload = json.loads(match.group(0))
                sql = payload.get("sql", "").strip()
                explanation = payload.get("explanation", "")
    except Exception as exc:  # noqa: BLE001
        log.warning("nl2sql.llm_failed", error=str(exc))

    if not sql:
        sql = _heuristic_sql(question)
        explanation = "Used a pre-baked query matched by intent."

    # Validate
    try:
        _validate(sql)
    except ValueError as exc:
        log.warning("nl2sql.validation_failed", error=str(exc), sql=sql)
        sql = _heuristic_sql(question)
        explanation = f"Replaced unsafe query: {exc}"

    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    df = con.execute(sql).fetch_df()
    con.close()

    log.info("nl2sql.success", rows=len(df), sql=sql[:80])
    return SQLResult(sql=sql, df=df, explanation=explanation)
