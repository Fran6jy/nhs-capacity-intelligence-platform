"""Tests for the real-time A&E streaming ingestion (in-memory simulation)."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings
from src.streaming.bus import InMemoryBus
from src.streaming.consumer import run_consumer
from src.streaming.events import AEAttendanceEvent, generate_event
from src.streaming.producer import run_producer


def test_event_roundtrip():
    e = generate_event()
    assert AEAttendanceEvent.from_json(e.to_json()) == e
    assert 1 <= e.acuity <= 5


def test_digital_twin_state():
    from src.streaming.twin import COLUMNS, simulate_window

    df = simulate_window(minutes=60)
    assert not df.empty
    assert list(df.columns) == COLUMNS
    # Behavioural sanity: EDs run hot, beds never negative, queues non-negative.
    assert df["occupancy_pct"].between(60, 100).all()
    assert (df["available_beds"] >= 0).all()
    assert (df["queue_length"] >= 0).all()
    assert df["minute_ts"].nunique() == 60


def test_producer_consumer_aggregates(tmp_path):
    # Isolate the warehouse + bronze layer for the test.
    settings.bronze_path = tmp_path / "raw"
    settings.warehouse_path = tmp_path / "wh.duckdb"
    settings.bronze_path.mkdir(parents=True, exist_ok=True)

    bus = InMemoryBus()
    n = 500
    assert run_producer(n_events=n, rate_per_sec=0, bus=bus) == n
    processed = run_consumer(batch_size=100, max_events=n, bus=bus)
    assert processed == n

    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    total = con.execute("SELECT SUM(attendances) FROM ae_stream_agg").fetchone()[0]
    con.close()
    # No event is lost in aggregation.
    assert total == n
