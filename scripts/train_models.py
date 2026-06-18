"""Train all models and write forecasts to the warehouse."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.training import train_all
from src.utils.logging import get_logger

log = get_logger("scripts.train_models")

if __name__ == "__main__":
    train_all()
    log.info("done")
