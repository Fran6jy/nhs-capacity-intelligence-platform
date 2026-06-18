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
    sql: str
    rows: list[dict]
    provider: str
