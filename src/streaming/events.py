"""Streaming event schema + synthetic generator.

The canonical real-time signal for NHS operational pressure is A&E arrivals:
high-frequency, bursty, and the leading indicator of bed/staff strain. Each
event is a single attendance at a hospital site.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config import settings

TOPIC_AE_ATTENDANCE = "nhs.ae.attendance"

# Acuity follows the Manchester Triage System (1 = immediate … 5 = non-urgent).
_ACUITY_WEIGHTS = [0.04, 0.12, 0.30, 0.34, 0.20]
_ARRIVAL_MODES = ["walk_in", "ambulance", "referral"]
_ARRIVAL_WEIGHTS = [0.62, 0.28, 0.10]


@dataclass(frozen=True)
class AEAttendanceEvent:
    """A single A&E attendance — the unit of the real-time stream."""

    event_id: str
    hospital_id: str
    region_id: str
    event_ts: str          # ISO-8601 UTC
    acuity: int            # 1..5 (1 = most urgent)
    arrival_mode: str      # walk_in | ambulance | referral
    is_breach_risk: bool   # likely to breach the 4-hour target

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "AEAttendanceEvent":
        return cls(**json.loads(raw))


def _hospital_catalogue() -> list[tuple[str, str]]:
    """(hospital_id, region_id) pairs, read from the gold dim_hospital if the
    pipeline has run, else a small static fallback so the demo always works."""
    parquet = settings.silver_path / "dim_hospital.parquet"
    if parquet.exists():
        df = pd.read_parquet(parquet, columns=["hospital_id", "region_id"])
        return list(df.itertuples(index=False, name=None))
    return [("H_R1K_00", "LON"), ("H_RR8_02", "YOR"), ("H_R0A_04", "NW")]


def generate_event(now: datetime | None = None) -> AEAttendanceEvent:
    """Produce one realistic A&E attendance event."""
    now = now or datetime.now(timezone.utc)
    hospital_id, region_id = random.choice(_hospital_catalogue())
    acuity = random.choices([1, 2, 3, 4, 5], weights=_ACUITY_WEIGHTS)[0]
    mode = random.choices(_ARRIVAL_MODES, weights=_ARRIVAL_WEIGHTS)[0]
    # Breach risk rises overnight and for low-acuity walk-ins (crowding).
    breach_p = 0.10 + (0.15 if now.hour >= 20 or now.hour < 6 else 0) + (0.10 if acuity >= 4 else 0)
    return AEAttendanceEvent(
        event_id=f"AE-{now:%Y%m%d}-{random.randint(0, 1_000_000_000):09d}",
        hospital_id=hospital_id,
        region_id=region_id,
        event_ts=now.isoformat(),
        acuity=acuity,
        arrival_mode=mode,
        is_breach_risk=random.random() < breach_p,
    )
