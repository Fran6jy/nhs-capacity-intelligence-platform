"""End-to-end pipeline runner: bronze → silver → gold → train → risk → recommend."""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Make src importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings, ensure_dirs
from src.pipeline.bronze import run as bronze_run
from src.pipeline.silver import run as silver_run
from src.pipeline.gold import run as gold_run
from src.models.training import train_all
from src.risk.risk_engine import run as risk_run
from src.llm.recommender import run as recommender_run
from src.utils.logging import get_logger

log = get_logger("run_pipeline")


def main() -> int:
    ensure_dirs()
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end",   type=str, default=None)
    args = parser.parse_args()

    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else (end - timedelta(days=180))

    log.info("run_pipeline.start", start=str(start), end=str(end))

    log.info("step.bronze")
    bronze_run(start, end)
    log.info("step.silver")
    silver_run()
    log.info("step.gold")
    gold_run()
    log.info("step.train")
    train_all()
    log.info("step.risk")
    risk_run()
    log.info("step.recommender")
    recommender_run()

    log.info("run_pipeline.complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
