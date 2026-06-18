"""Hospital Episode Statistics (HES) client.

Real HES data is licensed via NHS Digital's TRUD service. The client here
documents the API call and returns a placeholder; production deployments
plug in credentials via environment variables.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


def fetch(start: date, end: date) -> pd.DataFrame:
    raise NotImplementedError(
        "HES requires NHS Digital TRUD credentials. "
        "The pipeline falls back to synthetic data for local MVP."
    )
