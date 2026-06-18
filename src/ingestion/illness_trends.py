"""UKHSA / GOV.UK respiratory virus trends client."""
from __future__ import annotations

from datetime import date

import pandas as pd


def fetch(start: date, end: date) -> pd.DataFrame:
    raise NotImplementedError("Use the GOV.UK respiratory datahub JSON feed in production.")
