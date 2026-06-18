"""Met Office DataPoint client."""
from __future__ import annotations

from datetime import date

import pandas as pd


def fetch(start: date, end: date) -> pd.DataFrame:
    raise NotImplementedError("Use Met Office DataPoint or Open-Meteo for live weather.")
