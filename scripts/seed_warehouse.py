"""Initialise the warehouse end-to-end.

Runs the full medallion pipeline (bronze → silver → gold) so a fresh
checkout can go from `pip install` to a populated warehouse with one
command. For just creating an empty DDL-only warehouse (e.g. pointing
at a fresh Postgres or Synapse instance), run `python -m src.warehouse.seed`
instead.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ensure_dirs
from src.pipeline.bronze import run as bronze_run
from src.pipeline.silver import run as silver_run
from src.pipeline.gold import run as gold_run
from src.utils.logging import get_logger

log = get_logger("scripts.seed_warehouse")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default=None,
                        help="ISO date for the back-fill window start "
                             "(default: 180 days before --end).")
    parser.add_argument("--end", type=str, default=None,
                        help="ISO date for the back-fill window end (default: today).")
    args = parser.parse_args()

    ensure_dirs()
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else (end - timedelta(days=180))

    log.info("seed.start", start=str(start), end=str(end))
    bronze_run(start, end)
    silver_run()
    warehouse = gold_run()
    log.info("seed.complete", warehouse=str(warehouse))
    print(f"✓ Warehouse seeded at {warehouse}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
