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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    """Require an X-API-Key header on /api/* when API_KEY is configured.

    Open when API_KEY is unset (default), so the deploy keeps working until you
    opt in. Health, docs, and CORS preflight (OPTIONS) are always exempt.
    """
    if settings.api_key and request.method != "OPTIONS":
        path = request.url.path
        exempt = path == "/api/health" or not path.startswith("/api")
        if not exempt and request.headers.get("x-api-key") != settings.api_key:
            return JSONResponse({"detail": "invalid or missing API key"}, status_code=401)
    return await call_next(request)


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
# Digital twin — live department operational state + AI pressure copilot
# --------------------------------------------------------------------------- #
def _ops_series():
    """National per-minute department state from the behavioural twin."""
    return db.read_sql(
        """
        SELECT minute_ts,
               SUM(arrivals)            AS arrivals,
               SUM(admissions)          AS admissions,
               SUM(discharges)          AS discharges,
               SUM(available_beds)      AS available_beds,
               SUM(queue_length)        AS queue_length,
               SUM(ambulances_waiting)  AS ambulances_waiting,
               ROUND(AVG(occupancy_pct)::numeric, 1) AS occupancy_pct,
               SUM(breach_risk)         AS breach_risk
        FROM ae_dept_state
        GROUP BY minute_ts ORDER BY minute_ts
        """
    )


@app.get("/api/ops/state", tags=["digital-twin"])
def ops_state() -> dict:
    """Live ED department state (arrivals, occupancy, beds, queue, ambulances)."""
    if not db.table_exists("ae_dept_state"):
        return {"available": False, "minutes": [], "latest": {}}
    df = _ops_series()
    if df.empty:
        return {"available": False, "minutes": [], "latest": {}}
    last = df.iloc[-1]
    latest = {
        "minute_ts": last["minute_ts"].isoformat(),
        "arrivals": int(last["arrivals"]),
        "occupancy_pct": float(last["occupancy_pct"]),
        "available_beds": int(last["available_beds"]),
        "queue_length": int(last["queue_length"]),
        "ambulances_waiting": int(last["ambulances_waiting"]),
        "breach_risk": int(last["breach_risk"]),
    }
    return {"available": True, "minutes": _records(df), "latest": latest}


def _pressure_metrics(df) -> dict:
    """Current (last 20m) vs baseline (full window) operational deltas."""
    recent = df.tail(20)
    base = df.head(max(len(df) - 20, 1))
    base_arr = max(base["arrivals"].mean(), 0.01)
    cur_arr = recent["arrivals"].mean()
    return {
        "arrivals_vs_baseline_pct": round((cur_arr - base_arr) / base_arr * 100, 1),
        "occupancy_pct": round(recent["occupancy_pct"].mean(), 1),
        "available_beds_now": int(df.iloc[-1]["available_beds"]),
        "available_beds_change": int(df.iloc[-1]["available_beds"] - base["available_beds"].mean()),
        "queue_now": int(df.iloc[-1]["queue_length"]),
        "ambulances_waiting_now": int(df.iloc[-1]["ambulances_waiting"]),
        "ambulances_vs_baseline_pct": round(
            (recent["ambulances_waiting"].mean() - max(base["ambulances_waiting"].mean(), 0.01))
            / max(base["ambulances_waiting"].mean(), 0.01) * 100, 1),
    }


@app.get("/api/ops/explain", tags=["digital-twin"])
def ops_explain() -> dict:
    """AI copilot: explain current A&E pressure from live twin deltas vs baseline."""
    if not db.table_exists("ae_dept_state"):
        raise HTTPException(404, "no live operational state — seed the digital twin")
    df = _ops_series()
    if df.empty:
        raise HTTPException(404, "no live operational state")
    m = _pressure_metrics(df)

    from src.llm.rag import get_llm
    system = (
        "You are an NHS A&E operations copilot. Given live department metrics, explain "
        "in 2-3 sentences why pressure is rising or easing, citing the numbers, and give a "
        "short projection. Be concrete and concise; no preamble."
    )
    ctx = (
        f"Arrivals vs baseline: {m['arrivals_vs_baseline_pct']:+}%. "
        f"Mean bed occupancy: {m['occupancy_pct']}%. "
        f"Available beds now: {m['available_beds_now']} (change {m['available_beds_change']:+}). "
        f"Patients queued: {m['queue_now']}. Ambulances waiting: {m['ambulances_waiting_now']} "
        f"({m['ambulances_vs_baseline_pct']:+}% vs baseline)."
    )
    try:
        narrative = get_llm().invoke(
            [{"role": "system", "content": system}, {"role": "user", "content": ctx}]
        ).content
    except Exception as exc:  # noqa: BLE001
        log.warning("api.ops_explain_llm_failed", error=str(exc))
        narrative = (
            f"Arrivals are {m['arrivals_vs_baseline_pct']:+}% vs baseline with mean occupancy "
            f"{m['occupancy_pct']}% and {m['ambulances_waiting_now']} ambulances waiting; "
            "pressure is elevated and likely to persist without additional capacity."
        )
    return {"metrics": m, "narrative": narrative, "provider": settings.llm_provider}


# --------------------------------------------------------------------------- #
# Evidence & validation — real back-test accuracy + data provenance
# --------------------------------------------------------------------------- #
DATA_SOURCES = [
    {"name": "NHS Organisation Data Service (ODS)", "category": "Trust roster",
     "kind": "real", "detail": "Live register of active NHS trusts (codes, names, regions)."},
    {"name": "Open-Meteo Archive", "category": "Weather",
     "kind": "real", "detail": "Daily mean temperature per NHS region."},
    {"name": "NHS RTT waiting lists", "category": "Waiting times",
     "kind": "modelled", "detail": "Bulk Excel/CSV not machine-consumable — modelled on the real roster."},
    {"name": "A&E attendances / ECDS", "category": "Emergency demand",
     "kind": "modelled", "detail": "Behavioural digital-twin event stream (seasonality, bed-flow, queueing)."},
    {"name": "Workforce statistics", "category": "Staffing",
     "kind": "modelled", "detail": "Vacancy/staffing modelled per trust."},
    {"name": "ONS population", "category": "Demographics",
     "kind": "modelled", "detail": "Regional population (ONS API reachable; modelled in demo)."},
]


@app.get("/api/validation/sources", tags=["validation"])
def validation_sources() -> list[dict]:
    return DATA_SOURCES


@app.get("/api/validation/metrics", tags=["validation"])
def validation_metrics() -> dict:
    if not db.table_exists("model_metrics"):
        return {"available": False, "metrics": []}
    df = db.read_sql("SELECT target, model, accuracy, mae, mape, n_eval, holdout_days FROM model_metrics")
    return {"available": True, "metrics": _records(df)}


@app.get("/api/validation/forecast-actual", tags=["validation"])
def validation_forecast_actual() -> dict:
    if not db.table_exists("model_forecast_actual"):
        return {"available": False, "series": []}
    df = db.read_sql("SELECT target, date, actual, predicted FROM model_forecast_actual ORDER BY date")
    return {"available": True, "series": _records(df)}


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
