"""Natural-language question → PostgreSQL, with tiered routing and guard-rails.

Design
======
Text-to-SQL is powerful and unreliable in exactly the wrong proportion: an LLM
will happily emit syntactically valid SQL that joins at the wrong grain or
drops a date filter, and the answer *looks* authoritative. In an NHS
operational context a confidently wrong number is worse than a refusal, so
questions are routed through three tiers in descending order of trust:

1.  **Curated** — hand-written, reviewed queries for the questions that matter
    most. Deterministic, fast, free, and known-correct. Tried first.
2.  **Generated** — for the long tail no curated query covers, an LLM writes
    SQL against the real introspected schema. Validated, capped, executed under
    a read-only transaction, and the SQL is returned so the user can audit it.
3.  **Refusal** — when no curated intent matches and no model is available, say
    so. Never silently answer a different question than the one asked.

Every tier funnels through `validate_sql`, and every execution goes through
`db.read_sql_readonly`, so the safety properties do not depend on which tier
produced the statement.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from src import db
from src.config import settings
from src.llm.rag import get_llm, has_real_llm
from src.utils.logging import get_logger

log = get_logger("nl2sql")

#: Hard ceiling on rows returned to the API, regardless of what the SQL asks for.
MAX_ROWS = 200


class UnanswerableQuestion(Exception):
    """Raised when no tier can answer the question honestly."""


# --------------------------------------------------------------------------- #
# Tier 1 — curated intents
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Intent:
    """A reviewed query plus the language that should route to it.

    Patterns are full regexes matched against the lower-cased question and are
    anchored on word boundaries. Bare substrings are a trap: the previous
    implementation matched ``"ae" in question``, so *"paediatric admissions"*
    routed to the A&E query.
    """

    name: str
    description: str
    patterns: tuple[str, ...]
    sql: str


INTENTS: tuple[Intent, ...] = (
    Intent(
        name="waiting_times",
        description="Median wait by specialty now vs 90 days ago, with the change",
        patterns=(r"\bwait(ing|s|ed)?\b", r"\brtt\b", r"\bbacklog\b"),
        # Returns a *comparison*, not a snapshot. People ask "why are waits
        # rising", and a single-day figure cannot answer that — it leaves the
        # model either refusing or inventing a trend. Handing it both endpoints
        # lets it answer the question, and lets it say "they are not rising"
        # when that is what the data shows.
        sql="""
            WITH bounds AS (
                SELECT MAX(date_key) AS latest,
                       (MAX(date_key) - INTERVAL '90 days')::date AS prior
                FROM hospital_activity_fact
            )
            SELECT s.specialty_name,
                   ROUND(AVG(f.median_wait_days)
                         FILTER (WHERE f.date_key = b.latest)::numeric, 1) AS wait_now_days,
                   ROUND(AVG(f.median_wait_days)
                         FILTER (WHERE f.date_key = b.prior)::numeric, 1) AS wait_90d_ago_days,
                   ROUND((AVG(f.median_wait_days) FILTER (WHERE f.date_key = b.latest)
                        - AVG(f.median_wait_days) FILTER (WHERE f.date_key = b.prior))::numeric, 1)
                        AS change_days
            FROM hospital_activity_fact f
            JOIN dim_specialty s ON f.specialty_id = s.specialty_id
            CROSS JOIN bounds b
            WHERE f.date_key IN (b.latest, b.prior)
            GROUP BY s.specialty_name
            ORDER BY change_days DESC NULLS LAST
            LIMIT 10
        """,
    ),
    Intent(
        name="ae_demand",
        description="Daily A&E attendances, national, most recent 60 days",
        patterns=(
            r"\ba\s*&\s*e\b",
            r"\ba\s*and\s*e\b",
            r"\bemergency\b",
            r"\baccident\b",
            r"\battendance",
            r"\bambulance",
        ),
        sql="""
            SELECT date_key, SUM(ae_attendances) AS ae_attendances
            FROM hospital_activity_fact
            GROUP BY date_key
            ORDER BY date_key DESC
            LIMIT 60
        """,
    ),
    Intent(
        name="workforce",
        description="Vacancy rate and vacancy count by trust, latest date",
        patterns=(r"\bstaff(ing|s)?\b", r"\bworkforce\b", r"\bvacanc", r"\bnurse", r"\brecruit"),
        sql="""
            SELECT h.hospital_name,
                   AVG(f.vacancy_rate) AS vacancy_rate,
                   SUM(f.vacancies)    AS vacancies
            FROM hospital_activity_fact f
            JOIN dim_hospital h ON f.hospital_id = h.hospital_id
            WHERE f.date_key = (SELECT MAX(date_key) FROM hospital_activity_fact)
            GROUP BY h.hospital_name
            ORDER BY vacancy_rate DESC
            LIMIT 10
        """,
    ),
    Intent(
        name="capacity",
        description="Daily national capacity pressure (demand-to-capacity ratio)",
        patterns=(r"\bbeds?\b", r"\boccupanc", r"\bcapacity\b", r"\bdischarge", r"\badmission"),
        sql="""
            SELECT date_key, AVG(bed_occupancy_pct) AS bed_occupancy_pct
            FROM hospital_activity_fact
            GROUP BY date_key
            ORDER BY date_key DESC
            LIMIT 60
        """,
    ),
    Intent(
        name="risk",
        description="Highest-risk trusts with Green/Amber/Red classification",
        patterns=(r"\brisk", r"\boverload", r"\bpressure\b", r"\bescalat", r"\bworst\b"),
        sql="""
            SELECT h.hospital_name, r.region_name, rs.score, rs.classification
            FROM risk_score rs
            JOIN dim_hospital h ON rs.hospital_id = h.hospital_id
            JOIN dim_region   r ON h.region_id    = r.region_id
            WHERE rs.date_key = (SELECT MAX(date_key) FROM risk_score)
            ORDER BY rs.score DESC
            LIMIT 10
        """,
    ),
    Intent(
        name="forecast",
        description="Model forecasts by target and horizon",
        patterns=(r"\bforecast", r"\bpredict", r"\bprojection", r"\boutlook\b"),
        sql="""
            SELECT date_key, hospital_name, target, horizon_days,
                   yhat, yhat_lower, yhat_upper, model
            FROM v_forecast_long
            ORDER BY date_key DESC
            LIMIT 100
        """,
    ),
)


def match_intent(question: str) -> Intent | None:
    """Return the best-matching curated intent, or None to escalate a tier.

    Scored by how many distinct patterns hit, so a question mentioning both
    beds and risk lands on whichever is more specifically evidenced rather than
    on whichever happens to be checked first.
    """
    q = question.lower()
    best: tuple[int, Intent] | None = None
    for intent in INTENTS:
        score = sum(1 for p in intent.patterns if re.search(p, q))
        if score and (best is None or score > best[0]):
            best = (score, intent)
    return best[1] if best else None


# --------------------------------------------------------------------------- #
# Safety validator
# --------------------------------------------------------------------------- #
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|attach|copy|call|pragma|"
    r"set|use|grant|revoke|vacuum|reindex|merge|do|execute|prepare)\b",
    re.IGNORECASE,
)
_STARTS_READ = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w.]*)", re.IGNORECASE)
_CTE_DEF = re.compile(r"(?:\bwith\b|,)\s*([a-zA-Z_]\w*)\s+as\s*\(", re.IGNORECASE)
_LIMIT = re.compile(r"\blimit\s+(\d+)", re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _strip_literals(sql: str) -> str:
    """Blank out string literals so keyword scanning cannot false-positive.

    Without this, a legitimate ``WHERE region_name = 'Created'`` trips the
    forbidden-keyword check.
    """
    return _STRING_LITERAL.sub("''", sql)


def _cap_rows(sql: str, max_rows: int = MAX_ROWS) -> str:
    """Enforce a row ceiling the prompt cannot talk its way out of."""
    match = _LIMIT.search(_strip_literals(sql))
    if match is None:
        return f"{sql.rstrip()} LIMIT {max_rows}"
    if int(match.group(1)) > max_rows:
        start, end = match.span(1)
        return sql[:start] + str(max_rows) + sql[end:]
    return sql


def validate_sql(sql: str) -> str:
    """Validate an untrusted statement and return it with a row cap applied.

    Raises ``ValueError`` on anything that is not a single, read-only,
    allow-listed SELECT. The allow-list test is *containment*: every table
    referenced by a FROM or JOIN must be permitted. The previous version tested
    for intersection, so a query joining an allow-listed view to any other
    table passed.
    """
    s = sql.strip().rstrip(";")
    if not s:
        raise ValueError("Empty query.")

    bare = _strip_literals(s)

    if "--" in bare or "/*" in bare:
        raise ValueError("Comments are not allowed.")
    if ";" in bare:
        raise ValueError("Multiple statements are not allowed.")
    if not _STARTS_READ.match(bare):
        raise ValueError("Only SELECT (or WITH ... SELECT) statements are allowed.")
    if _FORBIDDEN.search(bare):
        raise ValueError("Forbidden keyword detected.")

    allowed = {t.lower() for t in settings.allowed_tables}
    ctes = {m.lower() for m in _CTE_DEF.findall(bare)}
    referenced = {t.lower() for t in _TABLE_REF.findall(bare)}

    if not referenced:
        raise ValueError("Query does not reference any table.")

    for table in referenced:
        if table.count(".") > 1 or (table.count(".") == 1 and not table.startswith("public.")):
            raise ValueError(f"Cross-schema reference is not allowed: {table}")
        name = table.split(".")[-1]
        if name not in allowed and name not in ctes:
            raise ValueError(f"Table not allow-listed: {name}")

    return _cap_rows(s)


# --------------------------------------------------------------------------- #
# Tier 2 — LLM-generated SQL
# --------------------------------------------------------------------------- #
_STATIC_SCHEMA = """
hospital_activity_fact(date_key DATE, hospital_id, specialty_id, region_id,
  admissions INT, discharges INT, bed_occupancy_pct NUMERIC, bed_occupancy_count INT,
  waiting_list_size INT, median_wait_days NUMERIC, staff_count INT, vacancies INT,
  vacancy_rate NUMERIC, ae_attendances INT, referrals INT, flu_index NUMERIC,
  covid_index NUMERIC, avg_temp_c NUMERIC)
dim_hospital(hospital_id, hospital_name, trust_code, trust_name, region_id,
  hospital_type, bed_capacity INT)
dim_specialty(specialty_id, specialty_name, category, is_emergency BOOL)
dim_region(region_id, region_name, icb_code, country, population INT)
ml_forecast(forecast_id, date_key DATE, hospital_id, specialty_id, target,
  horizon_days INT, yhat NUMERIC, yhat_lower NUMERIC, yhat_upper NUMERIC, model)
risk_score(risk_id, date_key DATE, hospital_id, score NUMERIC, classification,
  components_json JSON)
recommendation(recommendation_id, date_key DATE, hospital_id, severity, category,
  action, expected_impact)
v_national_pressure(date_key, ae_attendances, admissions, discharges,
  avg_bed_occupancy_pct, total_waiting_list, avg_vacancy_rate)
v_regional_risk_latest(region_id, region_name, date_key, red_count, amber_count,
  green_count, avg_score)
v_forecast_long(date_key, hospital_name, specialty_name, target, horizon_days,
  yhat, yhat_lower, yhat_upper, model)
v_top_risk_trusts(hospital_name, region_name, classification, score, date_key)
""".strip()


@lru_cache(maxsize=1)
def schema_card() -> str:
    """Real column names and types for the allow-listed relations.

    Introspected from the live database so the prompt can never drift from the
    deployed schema; falls back to a static card if the database is
    unreachable. Most generated-SQL failures are hallucinated columns, and
    handing the model the actual schema is the cheapest fix available.
    """
    try:
        rows = db.read_sql(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ANY(:tables)
            ORDER BY table_name, ordinal_position
            """,
            {"tables": list(settings.allowed_tables)},
        )
        if rows.empty:
            raise RuntimeError("no columns found for allow-listed tables")
        lines = []
        for table, grp in rows.groupby("table_name"):
            cols = ", ".join(f"{c} {t}" for c, t in zip(grp.column_name, grp.data_type, strict=True))
            lines.append(f"{table}({cols})")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        log.warning("nl2sql.schema_introspection_failed", error=str(exc))
        return _STATIC_SCHEMA


def _system_prompt() -> str:
    return (
        "You convert a natural-language question about NHS operational data into a "
        "single read-only PostgreSQL query.\n\n"
        f"Schema (use ONLY these relations and columns):\n{schema_card()}\n\n"
        "Rules:\n"
        "- Emit ONE SELECT statement (a leading WITH clause is fine). No semicolons.\n"
        "- No DDL, DML, comments, or references to anything outside the schema above.\n"
        "- PostgreSQL dialect. Cast to ::numeric before round(x, n) — "
        "round(double precision, int) does not exist in PostgreSQL.\n"
        "- 'Latest' means date_key = (SELECT MAX(date_key) FROM <the relevant table>).\n"
        f"- Always include LIMIT {MAX_ROWS} or fewer.\n"
        "- Prefer the v_* views when they already answer the question.\n\n"
        'Return ONLY a JSON object: {"sql": "...", "explanation": "one sentence on '
        'what the query computes"}'
    )


def generate_sql(question: str) -> tuple[str, str]:
    """Ask the model for SQL. Returns (sql, explanation); raises on failure."""
    resp = get_llm().invoke(
        [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": question},
        ]
    )
    match = re.search(r"\{[\s\S]*\}", resp.content or "")
    if not match:
        raise ValueError("Model did not return a JSON object.")
    payload = json.loads(match.group(0))
    sql = (payload.get("sql") or "").strip()
    if not sql:
        raise ValueError("Model returned no SQL.")
    return sql, (payload.get("explanation") or "").strip()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
@dataclass
class QueryResult:
    sql: str
    df: pd.DataFrame
    explanation: str
    #: "curated" (reviewed query) or "generated" (model-authored — audit the SQL)
    source: str
    intent: str | None = None


SUPPORTED_TOPICS = "; ".join(i.description for i in INTENTS)


def answer_question(question: str) -> QueryResult:
    """Route a question through the trust tiers and execute the winning query.

    Raises ``UnanswerableQuestion`` rather than guessing when no tier applies.
    """
    question = (question or "").strip()
    if not question:
        raise UnanswerableQuestion("Ask a question about NHS operational data.")

    intent = match_intent(question)
    if intent is not None:
        log.info("nl2sql.curated", intent=intent.name)
        sql = validate_sql(intent.sql)
        return QueryResult(
            sql=sql,
            df=db.read_sql_readonly(sql),
            explanation=intent.description,
            source="curated",
            intent=intent.name,
        )

    if has_real_llm():
        try:
            raw, explanation = generate_sql(question)
            sql = validate_sql(raw)
            log.info("nl2sql.generated", sql=sql[:120])
            return QueryResult(
                sql=sql,
                df=db.read_sql_readonly(sql),
                explanation=explanation or "Query generated from your question.",
                source="generated",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("nl2sql.generation_failed", error=str(exc))

    raise UnanswerableQuestion(
        "I can't answer that from the warehouse without guessing, so I'd rather not. "
        f"I can answer questions about: {SUPPORTED_TOPICS}."
    )
