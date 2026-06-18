"""Micro-batching consumer.

Reads A&E events off the bus, buffers them into micro-batches, and on each
flush:
* appends the raw events to the bronze stream layer (parquet), and
* upserts a per-hospital, per-minute aggregate into a live DuckDB table
  (`ae_stream_agg`) that the dashboard's real-time panel can query.

This is the streaming equivalent of the batch bronze->silver step, and the
aggregate is what a live "current A&E pressure" tile reads from.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from src.config import settings
from src.streaming.bus import EventBus, get_bus
from src.streaming.events import TOPIC_AE_ATTENDANCE, AEAttendanceEvent
from src.utils.io import write_parquet
from src.utils.logging import get_logger

log = get_logger("streaming.consumer")

_AGG_DDL = """
CREATE TABLE IF NOT EXISTS ae_stream_agg (
    minute_ts      TIMESTAMP,
    hospital_id    VARCHAR,
    region_id      VARCHAR,
    attendances    INTEGER,
    ambulance      INTEGER,
    high_acuity    INTEGER,   -- acuity 1-2
    breach_risk    INTEGER,
    PRIMARY KEY (minute_ts, hospital_id)
);
"""


def _aggregate(events: list[AEAttendanceEvent]) -> pd.DataFrame:
    df = pd.DataFrame([e.__dict__ for e in events])
    df["minute_ts"] = pd.to_datetime(df["event_ts"]).dt.floor("min")
    grp = (
        df.groupby(["minute_ts", "hospital_id", "region_id"], as_index=False)
        .agg(
            attendances=("event_id", "count"),
            ambulance=("arrival_mode", lambda s: int((s == "ambulance").sum())),
            high_acuity=("acuity", lambda s: int((s <= 2).sum())),
            breach_risk=("is_breach_risk", lambda s: int(s.sum())),
        )
    )
    return grp


def _upsert(con: duckdb.DuckDBPyConnection, agg: pd.DataFrame) -> None:
    con.register("batch", agg)
    # Sum into existing minute buckets (idempotent across micro-batches).
    con.execute(
        """
        INSERT INTO ae_stream_agg
        SELECT minute_ts, hospital_id, region_id, attendances, ambulance, high_acuity, breach_risk
        FROM batch
        ON CONFLICT (minute_ts, hospital_id) DO UPDATE SET
            attendances = ae_stream_agg.attendances + EXCLUDED.attendances,
            ambulance   = ae_stream_agg.ambulance   + EXCLUDED.ambulance,
            high_acuity = ae_stream_agg.high_acuity + EXCLUDED.high_acuity,
            breach_risk = ae_stream_agg.breach_risk + EXCLUDED.breach_risk;
        """
    )
    con.unregister("batch")


def run_consumer(
    batch_size: int = 250,
    idle_polls: int = 3,
    poll_timeout: float = 0.5,
    max_events: int | None = None,
    bus: EventBus | None = None,
) -> int:
    """Consume until ``idle_polls`` consecutive empty polls (stream drained) or
    ``max_events`` reached. Returns total events processed."""
    bus = bus or get_bus(topics=[TOPIC_AE_ATTENDANCE])
    warehouse = settings.warehouse_path
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(warehouse))
    con.execute(_AGG_DDL)

    bronze_stream = settings.bronze_path / "stream"
    buffer: list[AEAttendanceEvent] = []
    total = 0
    empty_streak = 0

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        agg = _aggregate(buffer)
        _upsert(con, agg)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        write_parquet(
            pd.DataFrame([e.__dict__ for e in buffer]),
            bronze_stream / f"ae_attendance_{ts}.parquet",
        )
        log.info("consumer.flush", events=len(buffer), minutes=len(agg))
        buffer = []

    while True:
        msg = bus.poll(timeout=poll_timeout)
        if msg is None:
            empty_streak += 1
            flush()
            if empty_streak >= idle_polls:
                break
            continue
        empty_streak = 0
        buffer.append(AEAttendanceEvent.from_json(msg.value))
        total += 1
        if len(buffer) >= batch_size:
            flush()
        if max_events is not None and total >= max_events:
            flush()
            break

    flush()
    con.close()
    log.info("consumer.done", total=total)
    return total


if __name__ == "__main__":
    run_consumer()
