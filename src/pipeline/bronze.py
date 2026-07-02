"""🥉 Bronze ingestion.

For each external source we either pull from a live endpoint or
read a local sample file (controlled by env). Output is partitioned
parquet under `data/raw/<source>/`.

Design notes:
* Bronze is **immutable**. We only append new partitions.
* Each source declares its own schema. We *do not* coerce types
  here — that is Silver's job.
* The clients below wrap network calls with tenacity retries.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.ingestion import (
    hes_client,
    illness_trends,
    population,
    weather,
    workforce,
)
from src.utils.dates import build_dim_date
from src.utils.io import write_parquet
from src.utils.logging import get_logger

log = get_logger("bronze")


# --------------------------------------------------------------------------- #
# Synthetic fallback — keeps the pipeline runnable offline.
# --------------------------------------------------------------------------- #

NHS_TRUSTS = [
    ("R1K", "London North West University Healthcare NHS Trust", "London", "Acute", 850),
    ("R1H", "Barts Health NHS Trust", "London", "Acute", 1100),
    ("RR8", "Leeds Teaching Hospitals NHS Trust", "Yorkshire", "Acute", 1200),
    ("RX1", "Nottingham University Hospitals NHS Trust", "Midlands", "Acute", 950),
    ("R0A", "Manchester University NHS Foundation Trust", "North West", "Acute", 1700),
    ("RJE", "North Staffordshire Combined Healthcare NHS Trust", "Midlands", "Community", 320),
    ("RH8", "Royal Devon and Exeter NHS Foundation Trust", "South West", "Acute", 800),
    ("R7A", "Cambridge University Hospitals NHS Foundation Trust", "East", "Acute", 1100),
    ("RYJ", "Imperial College Healthcare NHS Trust", "London", "Acute", 1300),
    ("RRK", "University Hospitals Birmingham NHS Foundation Trust", "Midlands", "Acute", 1400),
    ("RA3", "East Suffolk and North Essex NHS Foundation Trust", "East", "Acute", 750),
    ("REF", "Royal Cornwall Hospitals NHS Trust", "South West", "Acute", 700),
    ("RBD", "Dorset County Hospital NHS Foundation Trust", "South West", "Acute", 500),
    ("RGT", "Cambridge Community Services NHS Trust", "East", "Community", 280),
    ("RN3", "Great Ormond Street Hospital for Children NHS FT", "London", "Specialist", 400),
    ("RCD", "Harrogate and District NHS Foundation Trust", "Yorkshire", "Acute", 350),
]

SPECIALTIES = [
    ("SP_GEN", "General Medicine", "Medicine", False),
    ("SP_CARD", "Cardiology", "Medicine", False),
    ("SP_ONC",  "Oncology", "Medicine", False),
    ("SP_ORTH", "Trauma & Orthopaedics", "Surgery", False),
    ("SP_GAS",  "General Surgery", "Surgery", False),
    ("SP_PAED", "Paediatrics", "Medicine", False),
    ("SP_EMED", "Emergency Medicine", "Medicine", True),
    ("SP_NEU",  "Neurology", "Medicine", False),
    ("SP_DER",  "Dermatology", "Medicine", False),
    ("SP_OBS",  "Obstetrics & Gynaecology", "Surgery", False),
]

REGIONS = [
    ("LON", "London", "E40000003", "England", 9_000_000),
    ("YOR", "Yorkshire & Humber", "E40000006", "England", 5_500_000),
    ("MDL", "Midlands", "E40000008", "England", 10_800_000),
    ("NW",  "North West", "E40000007", "England", 7_400_000),
    ("SE",  "South East", "E40000005", "England", 9_200_000),
    ("SW",  "South West", "E40000004", "England", 5_600_000),
    ("EST", "East of England", "E40000012", "England", 6_200_000),
    ("NE",  "North East", "E40000010", "England", 2_700_000),
]


# Map the informal region label used in NHS_TRUSTS to the canonical
# dim_region.region_id code, so the star-schema FK joins resolve.
REGION_CODE_BY_LABEL = {
    "London": "LON",
    "Yorkshire": "YOR",
    "Midlands": "MDL",
    "North West": "NW",
    "South East": "SE",
    "South West": "SW",
    "East": "EST",
    "North East": "NE",
}


def _region_code(label: str) -> str:
    return REGION_CODE_BY_LABEL.get(label, label)


def _seed() -> None:
    random.seed(42)


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def _safe_get(url: str, **kwargs) -> requests.Response:
    r = requests.get(url, timeout=30, **kwargs)
    r.raise_for_status()
    return r


def ingest_nhs_waiting_list(period_start: date, period_end: date) -> pd.DataFrame:
    """Pull waiting list CSV from NHS England. Falls back to synthetic on error."""
    try:
        url = (
            f"https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/"
            f"{period_start:%Y}/{period_start:%Y}-{period_end:%Y}-rtt-waiting-times.csv"
        )
        df = pd.read_csv(url)
        log.info("ingest_nhs_waiting_list.live", rows=len(df))
        return df
    except Exception as exc:  # noqa: BLE001 — fallback to synthetic
        log.warning("ingest_nhs_waiting_list.fallback", error=str(exc))
        # Monthly snapshots across the whole period so the waiting-time model
        # has a continuous series. Each (trust, specialty) starts at a random
        # baseline and drifts month-over-month with mild seasonality.
        months = pd.date_range(period_start, period_end, freq="MS").to_pydatetime()
        if len(months) == 0:
            months = [period_start]
        rows = []
        for trust_code, _, _region, _htype, _beds in NHS_TRUSTS:
            for sp, _, _, _ in SPECIALTIES:
                size = random.randint(800, 18000)
                wait = random.uniform(8, 35)
                for m in months:
                    seasonal = 1.0 + 0.08 * (1 if m.month in (11, 12, 1, 2) else -0.4)
                    size = max(200, int(size * random.uniform(0.97, 1.05) * seasonal))
                    wait = max(3.0, wait * random.uniform(0.97, 1.04) * seasonal)
                    rows.append(
                        {
                            "trust_code": trust_code,
                            "specialty": sp,
                            "period": f"{m:%Y-%m}",
                            "waiting_list_size": size,
                            "median_wait_days": round(wait, 1),
                        }
                    )
        return pd.DataFrame(rows)


def ingest_hes(period_start: date, period_end: date) -> pd.DataFrame:
    """HES inpatient activity sample. Falls back to synthetic."""
    try:
        # The real HES API requires NHS_DIGITAL_TRUD credentials; show the call.
        return hes_client.fetch(period_start, period_end)
    except Exception as exc:  # noqa: BLE001
        log.warning("ingest_hes.fallback", error=str(exc))
        rows = []
        for trust_code, _, _region, _htype, beds in NHS_TRUSTS:
            for sp, _, _, is_em in SPECIALTIES:
                days = (period_end - period_start).days
                for d in range(days):
                    rows.append(
                        {
                            "trust_code": trust_code,
                            "specialty": sp,
                            "date": period_start + timedelta(days=d),
                            "admissions": random.randint(0, 60),
                            "discharges": random.randint(0, 60),
                            "bed_occupancy_count": int(beds * random.uniform(0.82, 0.97)),
                            "ae_attendances": random.randint(40, 360) if is_em else 0,
                            "referrals": random.randint(0, 90),
                        }
                    )
        return pd.DataFrame(rows)


def ingest_workforce() -> pd.DataFrame:
    """Workforce statistics from NHS Digital WFS."""
    try:
        return workforce.fetch()
    except Exception as exc:  # noqa: BLE001
        log.warning("ingest_workforce.fallback", error=str(exc))
        rows = []
        for trust_code, _, _, _htype, beds in NHS_TRUSTS:
            for role in ("Consultant", "Junior Doctor", "Nurse", "Allied Health"):
                base = int(beds * {"Consultant": 0.12, "Junior Doctor": 0.18,
                                    "Nurse": 0.9, "Allied Health": 0.25}[role])
                vac = int(base * random.uniform(0.03, 0.16))
                rows.append(
                    {
                        "trust_code": trust_code,
                        "role": role,
                        "staff_count": base - vac,
                        "vacancies": vac,
                        "vacancy_rate": round(vac / max(base, 1) * 100, 2),
                    }
                )
        return pd.DataFrame(rows)


def ingest_demographics() -> pd.DataFrame:
    """ONS population estimates."""
    try:
        return population.fetch()
    except Exception as exc:  # noqa: BLE001
        log.warning("ingest_demographics.fallback", error=str(exc))
        return pd.DataFrame(
            [{"region_id": r, "region_name": n, "population": p, "country": c}
             for r, n, _, c, p in REGIONS]
        )


def ingest_illness(period_start: date, period_end: date) -> pd.DataFrame:
    """Flu/COVID/RSV trends."""
    try:
        return illness_trends.fetch(period_start, period_end)
    except Exception as exc:  # noqa: BLE001
        log.warning("ingest_illness.fallback", error=str(exc))
        rows = []
        for d in range((period_end - period_start).days + 1):
            day = period_start + timedelta(days=d)
            # Flu peaks Dec–Feb, COVID lower amplitude
            flu = max(0.0, 6 + 5 * (1 - abs(day.month - 1) / 6)) + random.gauss(0, 1)
            covid = 2 + random.gauss(0, 0.7) + (1.5 if day.month in (11, 12, 1) else 0)
            rows.append({"date": day, "flu_index": round(flu, 2),
                         "covid_index": round(covid, 2)})
        return pd.DataFrame(rows)


def ingest_weather(period_start: date, period_end: date) -> pd.DataFrame:
    """Met Office daily temperatures by region (sample)."""
    try:
        return weather.fetch(period_start, period_end)
    except Exception as exc:  # noqa: BLE001
        log.warning("ingest_weather.fallback", error=str(exc))
        rows = []
        for region_id, _, _, _, _ in REGIONS:
            for d in range((period_end - period_start).days + 1):
                day = period_start + timedelta(days=d)
                # UK seasonal temperature pattern
                base = 10 + 10 * (1 - abs(day.month - 7) / 6)
                rows.append(
                    {
                        "date": day,
                        "region_id": region_id,
                        "avg_temp_c": round(base + random.gauss(0, 3.5), 1),
                    }
                )
        return pd.DataFrame(rows)


def ingest_dimensions(period_start: date, period_end: date) -> dict[str, pd.DataFrame]:
    """Static dimension tables (loaded once)."""
    dim_date = build_dim_date(period_start, period_end)
    dim_hosp = pd.DataFrame(
        [
            {
                "hospital_id": f"H_{code}_{i:02d}",
                "hospital_name": f"{name} – Site {i+1}",
                "trust_code": code,
                "trust_name": name,
                "region_id": _region_code(reg),
                "hospital_type": htype,
                "bed_capacity": beds,
            }
            for i, (code, name, reg, htype, beds) in enumerate(NHS_TRUSTS)
            for _ in range(1)
        ]
    )
    dim_spec = pd.DataFrame(
        [
            {"specialty_id": sid, "specialty_name": sname, "category": cat, "is_emergency": ie}
            for sid, sname, cat, ie in SPECIALTIES
        ]
    )
    dim_reg = pd.DataFrame(
        [
            {"region_id": rid, "region_name": rname, "icb_code": icb, "country": c, "population": pop}
            for rid, rname, icb, c, pop in REGIONS
        ]
    )
    return {"dim_date": dim_date, "dim_hospital": dim_hosp,
            "dim_specialty": dim_spec, "dim_region": dim_reg}


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

def run(period_start: date | None = None, period_end: date | None = None) -> None:
    """Ingest everything into the bronze layer."""
    _seed()
    period_end = period_end or date.today()
    period_start = period_start or (period_end - timedelta(days=180))

    # Use the REAL NHS trust roster from the ODS API when reachable, so every
    # downstream generator/dimension runs over genuine NHS organisations.
    # Falls back to the static synthetic roster offline.
    global NHS_TRUSTS
    try:
        from src.ingestion import ods
        NHS_TRUSTS = ods.fetch_trusts(limit=16)
        log.info("bronze.trusts_live", source="ods", count=len(NHS_TRUSTS))
    except Exception as exc:  # noqa: BLE001
        log.warning("bronze.trusts_fallback", error=str(exc))

    log.info("bronze.start", start=str(period_start), end=str(period_end))

    sources = {
        "nhs_waiting_list":   ingest_nhs_waiting_list(period_start, period_end),
        "hes":                ingest_hes(period_start, period_end),
        "workforce":          ingest_workforce(),
        "demographics":       ingest_demographics(),
        "illness_trends":     ingest_illness(period_start, period_end),
        "weather":            ingest_weather(period_start, period_end),
    }

    dims = ingest_dimensions(period_start, period_end)
    sources.update({f"dim_{k.split('_', 1)[1]}": v for k, v in dims.items() if k.startswith("dim_")})

    for name, df in sources.items():
        out = settings.bronze_path / f"{name}.parquet"
        write_parquet(df, out)

    log.info("bronze.complete", sources=list(sources.keys()))


if __name__ == "__main__":
    run()
