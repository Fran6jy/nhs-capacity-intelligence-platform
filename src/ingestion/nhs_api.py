"""NHS England waiting-list / RTT API client."""
from __future__ import annotations

import requests


def fetch_rtt(period: str) -> dict:
    """Fetch the monthly RTT waiting times JSON for a YYYY-MM period."""
    url = (
        "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/"
        f"{period[:4]}/rtt-summary-{period}.json"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()
