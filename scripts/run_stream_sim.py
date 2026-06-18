"""Run the real-time A&E ingestion simulation end-to-end.

Producer and consumer run on separate threads against the shared bus (the
in-memory batch-simulation backend by default, or a real Kafka broker if
``STREAM_BACKEND=kafka`` and ``KAFKA_BOOTSTRAP`` are set). On completion the
live aggregate lives in the warehouse table ``ae_stream_agg``.

    python scripts/run_stream_sim.py --events 3000 --rate 500
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from src.config import settings
from src.streaming.consumer import run_consumer
from src.streaming.producer import run_producer
from src.utils.logging import get_logger

log = get_logger("stream_sim")


def main() -> int:
    ap = argparse.ArgumentParser(description="NHS A&E streaming simulation")
    ap.add_argument("--events", type=int, default=3000)
    ap.add_argument("--rate", type=float, default=500.0, help="events/sec")
    ap.add_argument("--spread-minutes", type=int, default=0,
                    help="distribute timestamps across the last N minutes (seed a per-minute curve)")
    args = ap.parse_args()

    log.info("stream_sim.start", events=args.events, rate=args.rate)

    # Consumer first so it is ready to drain as the producer emits.
    consumed: dict[str, int] = {}

    def _consume() -> None:
        consumed["n"] = run_consumer(max_events=args.events)

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    produced = run_producer(n_events=args.events, rate_per_sec=args.rate,
                            spread_minutes=args.spread_minutes)
    t.join(timeout=30)

    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    rows = con.execute(
        "SELECT COUNT(*) AS n_minutes, SUM(attendances) AS n_attendances, "
        "SUM(breach_risk) AS n_breaches FROM ae_stream_agg"
    ).fetchone()
    con.close()

    log.info(
        "stream_sim.complete",
        produced=produced,
        consumed=consumed.get("n", 0),
        agg_minutes=rows[0],
        agg_attendances=rows[1],
        agg_breaches=rows[2],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
