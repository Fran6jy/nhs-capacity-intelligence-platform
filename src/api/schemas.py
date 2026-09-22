"""Pydantic response/request models for the API contract."""
from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    tables: int


class KPIs(BaseModel):
    latest_date: str | None
    ae_attendances: int
    avg_bed_occupancy_pct: float
    total_waiting_list: int
    avg_vacancy_rate: float
    trusts_red: int


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    question: str
    answer: str
    #: The SQL actually executed — surfaced so the user can audit the number.
    sql: str
    rows: list[dict]
    provider: str
    #: Which trust tier answered: "curated" (reviewed query), "generated"
    #: (model-authored SQL), or "unanswerable" (declined rather than guessed).
    source: str = "curated"
    #: Name of the curated intent that matched, when source is "curated".
    intent: str | None = None
    #: One line on what the query computes.
    explanation: str = ""
