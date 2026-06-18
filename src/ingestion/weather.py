"""Real weather ingestion via the Open-Meteo Archive API (free, no API key).

Pulls daily mean 2m temperature per NHS region (region centroid lat/lon) for the
requested window. This is a genuine live external data source feeding the gold
warehouse's `avg_temp_c` feature. On any network/parse error the caller
(`bronze.ingest_weather`) falls back to a synthetic series so the pipeline stays
runnable offline.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.logging import get_logger

log = get_logger("ingestion.weather")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# NHS region centroids (approx lat/lon) — keyed by dim_region.region_id.
REGION_CENTROIDS: dict[str, tuple[float, float]] = {
    "LON": (51.51, -0.12),
    "YOR": (53.80, -1.55),
    "MDL": (52.48, -1.90),
    "NW": (53.48, -2.60),
    "SE": (51.20, -0.60),
    "SW": (50.80, -3.50),
    "EST": (52.20, 0.50),
    "NE": (54.90, -1.60),
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _archive(lat: float, lon: float, start: date, end: date) -> dict:
    resp = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_mean",
            "timezone": "UTC",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch(start: date, end: date) -> pd.DataFrame:
    """Daily mean temperature per region. Columns: date, region_id, avg_temp_c."""
    # The Archive API lags real time by ~5 days; cap the end date so recent
    # windows still return real measurements (the last few days are left NaN
    # and handled by the downstream left-join).
    end = min(end, date.today() - timedelta(days=5))
    if start > end:
        raise RuntimeError("weather window entirely within the Archive API lag")

    rows: list[dict] = []
    for region_id, (lat, lon) in REGION_CENTROIDS.items():
        data = _archive(lat, lon, start, end)
        daily = data.get("daily", {})
        times = daily.get("time", [])
        temps = daily.get("temperature_2m_mean", [])
        for d, t in zip(times, temps, strict=False):
            if t is None:
                continue
            rows.append({"date": pd.to_datetime(d).date(), "region_id": region_id,
                         "avg_temp_c": round(float(t), 1)})
    if not rows:
        raise RuntimeError("Open-Meteo returned no temperature data")
    df = pd.DataFrame(rows)
    log.info("weather.live", rows=len(df), regions=df["region_id"].nunique())
    return df
