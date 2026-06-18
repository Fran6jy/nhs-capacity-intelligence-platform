"""NHS Capacity & Demand Intelligence — FastAPI backend.

Run:
    DATABASE_URL=postgresql+psycopg2://nhs@localhost:5432/nhs_warehouse \
        uvicorn src.api.main:app --reload

All endpoints read from PostgreSQL via `src.db`. JSON is returned with NaN
coerced to null so the React frontend gets clean payloads.
"""
from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from src import db
from src.api.schemas import AskRequest, AskResponse, HealthResponse, KPIs
from src.config import settings
from src.utils.logging import get_logger

log = get_logger("api")

app = FastAPI(
    title="NHS Capacity & Demand Intelligence API",
    version="1.0.0",
    description="Predictive + prescriptive NHS operational intelligence, served from PostgreSQL.",
)

# CORS — allow the React dev server and configured origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _records(df) -> list[dict[str, Any]]:
    """DataFrame -> list of JSON-safe dicts (NaN/NaT -> None)."""
    out = df.to_dict(orient="records")
    for row in out:
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                row[k] = None
            elif hasattr(v, "isoformat"):
                row[k] = v.isoformat()
    return out


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/api/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    try:
        n = db.read_sql(
            "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema='public'"
        ).iloc[0]["n"]
        return HealthResponse(status="ok", database="postgresql", tables=int(n))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc


# --------------------------------------------------------------------------- #
# Executive overview
# --------------------------------------------------------------------------- #
@app.get("/api/overview/kpis", response_model=KPIs, tags=["overview"])
def kpis() -> KPIs:
    p = db.read_sql(
        "SELECT * FROM v_national_pressure ORDER BY date_key DESC LIMIT 1"
    )
    if p.empty:
        raise HTTPException(404, "no data — has the warehouse been published?")
    r = p.iloc[0]
    n_red = db.read_sql(
        "SELECT COUNT(*) AS n FROM risk_score "
        "WHERE classification='Red' AND date_key=(SELECT MAX(date_key) FROM risk_score)"
    ).iloc[0]["n"]
    return KPIs(
        latest_date=str(r["date_key"]),
        ae_attendances=int(r["ae_attendances"] or 0),
        avg_bed_occupancy_pct=round(float(r["avg_bed_occupancy_pct"] or 0), 1),
        total_waiting_list=int(r["total_waiting_list"] or 0),
        avg_vacancy_rate=round(float(r["avg_vacancy_rate"] or 0), 1),
        trusts_red=int(n_red),
    )


@app.get("/api/overview/national-pressure", tags=["overview"])
def national_pressure(days: int = Query(90, ge=1, le=365)) -> list[dict]:
    df = db.read_sql(
        "SELECT * FROM v_national_pressure ORDER BY date_key DESC LIMIT :n", {"n": days}
    ).sort_values("date_key")
    return _records(df)


# --------------------------------------------------------------------------- #
# Risk
# --------------------------------------------------------------------------- #
@app.get("/api/risk/distribution", tags=["risk"])
def risk_distribution() -> list[dict]:
    return _records(db.read_sql(
        "SELECT classification, COUNT(*) AS n FROM risk_score "
        "WHERE date_key=(SELECT MAX(date_key) FROM risk_score) GROUP BY classification"
    ))


@app.get("/api/risk/top", tags=["risk"])
def risk_top() -> list[dict]:
    return _records(db.read_sql("SELECT * FROM v_top_risk_trusts"))


@app.get("/api/risk/regional", tags=["risk"])
def risk_regional() -> list[dict]:
    return _records(db.read_sql("SELECT * FROM v_regional_risk_latest"))


# --------------------------------------------------------------------------- #
# Forecasts & workforce
# --------------------------------------------------------------------------- #
@app.get("/api/forecasts", tags=["forecasts"])
def forecasts(
    target: str | None = Query(None, description="bed_occupancy | waiting_time | ae_demand | workforce_demand"),
    horizon: int | None = Query(None),
) -> list[dict]:
    sql = "SELECT * FROM v_forecast_long WHERE 1=1"
    params: dict = {}
    if target:
        sql += " AND target = :target"
        params["target"] = target
    if horizon:
        sql += " AND horizon_days = :horizon"
        params["horizon"] = horizon
    sql += " ORDER BY date_key LIMIT 5000"
    return _records(db.read_sql(sql, params))


@app.get("/api/workforce", tags=["workforce"])
def workforce() -> list[dict]:
    # Latest staffing snapshot per trust, derived from the fact table.
    df = db.read_sql(
        """
        WITH latest AS (SELECT MAX(date_key) AS d FROM hospital_activity_fact)
        SELECT h.hospital_name, h.region_id,
               MAX(f.staff_count)  AS staff_count,
               MAX(f.vacancies)    AS vacancies,
               MAX(f.vacancy_rate) AS vacancy_rate
        FROM hospital_activity_fact f
        JOIN dim_hospital h ON f.hospital_id = h.hospital_id
        WHERE f.date_key = (SELECT d FROM latest)
        GROUP BY h.hospital_name, h.region_id
        ORDER BY vacancy_rate DESC NULLS LAST
        """
    )
    return _records(df)


@app.get("/api/recommendations", tags=["recommendations"])
def recommendations() -> list[dict]:
    return _records(db.read_sql(
        "SELECT r.*, h.hospital_name FROM recommendation r "
        "LEFT JOIN dim_hospital h ON r.hospital_id = h.hospital_id "
        "ORDER BY severity DESC, recommendation_id"
    ))


@app.get("/api/stream/ae", tags=["stream"])
def stream_ae(window_minutes: int = Query(60, ge=1, le=1440)) -> dict:
    if not db.table_exists("ae_stream_agg"):
        return {"available": False, "minutes": [], "totals": {}}
    df = db.read_sql(
        """
        SELECT minute_ts, SUM(attendances) AS attendances,
               SUM(ambulance) AS ambulance, SUM(breach_risk) AS breach_risk
        FROM ae_stream_agg
        WHERE minute_ts >= (SELECT MAX(minute_ts) FROM ae_stream_agg) - (:w || ' minutes')::interval
        GROUP BY minute_ts ORDER BY minute_ts
        """,
        {"w": window_minutes},
    )
    totals = {
        "attendances": int(df["attendances"].sum()) if not df.empty else 0,
        "ambulance": int(df["ambulance"].sum()) if not df.empty else 0,
        "breach_risk": int(df["breach_risk"].sum()) if not df.empty else 0,
    }
    return {"available": True, "minutes": _records(df), "totals": totals}


# --------------------------------------------------------------------------- #
# AI insight (RAG): NL -> SQL (validated) -> Postgres -> LLM narration
# --------------------------------------------------------------------------- #
@app.post("/api/ask", response_model=AskResponse, tags=["ai"])
def ask(req: AskRequest) -> AskResponse:
    from src.llm.nl2sql import _heuristic_sql, _validate
    from src.llm.prompts import SYSTEM_INSIGHT
    from src.llm.rag import get_llm

    sql = _heuristic_sql(req.question)
    try:
        _validate(sql)
    except ValueError as exc:
        raise HTTPException(400, f"unsafe query: {exc}") from exc

    df = db.read_sql(sql)
    rows = _records(df)

    llm = get_llm()
    context = f"Question: {req.question}\n\nData (from PostgreSQL):\n{df.head(40).to_string(index=False)}"
    try:
        answer = llm.invoke(
            [{"role": "system", "content": SYSTEM_INSIGHT},
             {"role": "user", "content": context}]
        ).content
    except Exception as exc:  # noqa: BLE001
        log.warning("api.ask_llm_failed", error=str(exc))
        answer = "LLM unavailable; returning retrieved data only."

    return AskResponse(
        question=req.question, answer=answer, sql=sql, rows=rows,
        provider=settings.llm_provider,
    )
