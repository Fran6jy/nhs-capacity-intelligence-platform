"""Emergency-department digital twin — behavioural operational-state simulator.

Models per-trust, per-minute A&E department state with the operational
relationships NHS datasets are designed to capture:

* **Seasonality** — winter (Dec–Feb) + flu surge lift arrivals & admissions.
* **Time-of-day** — arrivals peak late morning → evening.
* **Flow** — occupied beds evolve as admissions minus discharges; available beds
  fall as occupancy rises.
* **Bed block** — discharges slow stochastically, raising occupancy and trolley waits.
* **Staffing** — a per-trust staff factor (from vacancy rate) throttles throughput.
* **Queueing** — queue grows when arrivals outpace throughput / beds are scarce.
* **Ambulance handovers** — rise with occupancy and queue length.

Output rows feed `ae_dept_state` (the live layer of the digital twin). This is a
*simulation* of the operational feed real trusts generate (the Emergency Care
Data Set, ECDS), layered on the real ODS trust roster.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.config import settings
from src.utils.logging import get_logger

log = get_logger("streaming.twin")

COLUMNS = [
    "minute_ts", "hospital_id", "region_id", "arrivals", "ambulance_arrivals",
    "admissions", "discharges", "occupied_beds", "available_beds", "beds_total",
    "occupancy_pct", "queue_length", "ambulances_waiting", "breach_risk", "staff_factor",
]


def _catalogue() -> list[dict]:
    """Real trusts with bed capacity + a staff factor, from the gold dims."""
    dh = settings.silver_path / "dim_hospital.parquet"
    if dh.exists():
        df = pd.read_parquet(dh, columns=["hospital_id", "region_id", "bed_capacity"])
        rows = df.to_dict("records")
    else:
        rows = [{"hospital_id": "H_R0A_00", "region_id": "NW", "bed_capacity": 600}]
    for r in rows:
        # Deterministic per-trust staffing health in [0.78, 1.0] (1.0 = fully staffed).
        r["staff_factor"] = round(0.78 + (abs(hash(r["hospital_id"])) % 22) / 100, 2)
    return rows


def _season_mult(ts: datetime) -> float:
    # Winter respiratory + flu surge; trough in summer.
    winter = math.cos((ts.month - 1) / 12 * 2 * math.pi)  # +1 in Jan, -1 in Jul
    flu = 0.15 if ts.month in (12, 1, 2) else 0.0
    return 1.0 + 0.18 * winter + flu


def _tod_mult(ts: datetime) -> float:
    # Arrivals peak ~11:00–20:00, trough overnight.
    h = ts.hour + ts.minute / 60
    return 0.55 + 0.65 * max(0.0, math.sin((h - 6) / 24 * 2 * math.pi) + 0.4)


def simulate_window(minutes: int = 180, now: datetime | None = None) -> pd.DataFrame:
    """Simulate the last ``minutes`` of department state for every trust."""
    now = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    start = now - timedelta(minutes=minutes - 1)
    cat = _catalogue()
    rows: list[dict] = []

    for h in cat:
        beds = int(h["bed_capacity"])
        staff = float(h["staff_factor"])
        base_arr = max(0.8, beds / 300.0)              # arrivals/min scales with size
        occupied = beds * random.uniform(0.90, 0.98)   # EDs run hot (NHS reality)
        queue = random.randint(8, 30)
        block = 1.0                                     # discharge-slowdown factor
        for i in range(minutes):
            ts = start + timedelta(minutes=i)
            mult = _season_mult(ts) * _tod_mult(ts)
            arrivals = max(0, int(random.gauss(base_arr * mult, base_arr * 0.5)))
            ambulance_arrivals = int(arrivals * random.uniform(0.22, 0.34))
            admissions = int(arrivals * random.uniform(0.25, 0.35) * _season_mult(ts))

            # Bed block: occasionally discharges stall for a stretch.
            if random.random() < 0.05:
                block = random.uniform(0.4, 0.7)
            else:
                block = min(1.0, block + 0.04)
            discharges = int(admissions * random.uniform(0.88, 1.04) * staff * block)

            # Occupancy stays high (clamped to 70–100%); bed block pushes it up.
            occupied = min(beds, max(0.70 * beds, occupied + admissions - discharges))
            available = max(0, int(beds - occupied))
            occ_pct = round(occupied / beds * 100, 1)

            # Throughput into beds drops as beds vanish / staffing falls → queue builds.
            throughput = staff * base_arr * (0.45 + 0.55 * available / beds) * (0.8 * mult)
            queue = max(2, int(queue + arrivals - throughput))
            ambulances_waiting = int(max(0, (occ_pct - 90) / 2.5 + queue / 9) * random.uniform(0.7, 1.2))
            breach = int(queue * random.uniform(0.12, 0.20) + max(0, occ_pct - 94) * 0.4)

            rows.append({
                "minute_ts": ts, "hospital_id": h["hospital_id"], "region_id": h["region_id"],
                "arrivals": arrivals, "ambulance_arrivals": ambulance_arrivals,
                "admissions": admissions, "discharges": discharges,
                "occupied_beds": int(occupied), "available_beds": available, "beds_total": beds,
                "occupancy_pct": occ_pct, "queue_length": queue,
                "ambulances_waiting": ambulances_waiting, "breach_risk": breach,
                "staff_factor": staff,
            })

    df = pd.DataFrame(rows, columns=COLUMNS)
    log.info("twin.simulated", minutes=minutes, trusts=len(cat), rows=len(df))
    return df


def persist(df: pd.DataFrame) -> int:
    """Replace the `ae_dept_state` table in the DuckDB warehouse with `df`."""
    import duckdb

    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.warehouse_path))
    con.register("twin_df", df)
    con.execute("CREATE OR REPLACE TABLE ae_dept_state AS SELECT * FROM twin_df")
    con.unregister("twin_df")
    con.close()
    return len(df)


def seed(minutes: int = 180) -> int:
    """Simulate and persist a fresh department-state window."""
    return persist(simulate_window(minutes))

