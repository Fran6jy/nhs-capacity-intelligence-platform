"""Real NHS trust roster from the NHS Organisation Data Service (ODS) API.

The ODS directory (https://directory.spineservices.nhs.uk) is the authoritative,
free, no-auth register of NHS organisations. We pull active NHS trusts
(PrimaryRoleId RO197) — real OrgId codes, names and postcodes — and map each
postcode area to an NHS England region.

This makes the platform's hospital dimension *real NHS organisations*. Note:
trust-level **operational** data (A&E attendances, RTT waiting lists, bed
occupancy) is not openly machine-consumable (NHS England publishes rotating
Excel/CSV bulk files that block direct fetch), so those metrics remain modelled
on top of the real roster. Bed capacity and hospital_type are derived.
"""
from __future__ import annotations

import re

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.logging import get_logger

log = get_logger("ingestion.ods")

ODS_URL = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"

# Postcode area (alpha prefix) → NHS England region_id (matches dim_region).
_POSTCODE_REGION: dict[str, str] = {
    # London
    "E": "LON", "EC": "LON", "N": "LON", "NW": "LON", "SE": "LON", "SW": "LON",
    "W": "LON", "WC": "LON", "EN": "LON", "HA": "LON", "IG": "LON", "RM": "LON",
    "UB": "LON", "TW": "LON", "KT": "LON", "SM": "LON", "CR": "LON", "BR": "LON", "DA": "LON",
    # North West
    "M": "NW", "L": "NW", "BL": "NW", "BB": "NW", "PR": "NW", "FY": "NW", "LA": "NW",
    "CA": "NW", "WA": "NW", "WN": "NW", "SK": "NW", "OL": "NW", "CH": "NW", "CW": "NW",
    # Yorkshire & Humber
    "LS": "YOR", "BD": "YOR", "HX": "YOR", "HD": "YOR", "WF": "YOR", "S": "YOR",
    "DN": "YOR", "HU": "YOR", "YO": "YOR", "HG": "YOR",
    # North East
    "NE": "NE", "SR": "NE", "DH": "NE", "TS": "NE", "DL": "NE",
    # Midlands
    "B": "MDL", "CV": "MDL", "WV": "MDL", "WS": "MDL", "DY": "MDL", "ST": "MDL",
    "TF": "MDL", "DE": "MDL", "NG": "MDL", "LE": "MDL", "LN": "MDL", "NN": "MDL", "WR": "MDL", "HR": "MDL",
    # East of England
    "CB": "EST", "CO": "EST", "CM": "EST", "SS": "EST", "IP": "EST", "NR": "EST",
    "AL": "EST", "LU": "EST", "SG": "EST", "HP": "EST", "MK": "EST", "PE": "EST",
    # South East
    "OX": "SE", "RG": "SE", "SL": "SE", "GU": "SE", "ME": "SE", "CT": "SE",
    "TN": "SE", "BN": "SE", "RH": "SE", "PO": "SE", "SO": "SE",
    # South West
    "BS": "SW", "BA": "SW", "TA": "SW", "EX": "SW", "PL": "SW", "TQ": "SW",
    "TR": "SW", "DT": "SW", "GL": "SW", "SN": "SW", "SP": "SW", "BH": "SW",
}


def _region_for(postcode: str | None) -> str:
    area = re.match(r"^([A-Z]+)", (postcode or "").upper())
    if not area:
        return "MDL"
    code = area.group(1)
    return _POSTCODE_REGION.get(code[:2]) or _POSTCODE_REGION.get(code[:1]) or "MDL"


def _type_for(name: str) -> str:
    n = name.upper()
    if "MENTAL HEALTH" in n or "WELLBEING" in n:
        return "Mental Health"
    if "COMMUNITY" in n:
        return "Community"
    if "AMBULANCE" in n:
        return "Ambulance"
    return "Acute"


def _beds_for(code: str) -> int:
    # Deterministic modelled capacity (no open bed-count feed): 300–1500.
    return 300 + (abs(hash(code)) % 25) * 50


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def fetch_trusts(limit: int = 40) -> list[tuple[str, str, str, str, int]]:
    """Return real active NHS trusts as (code, name, region_id, type, beds).

    Restricted to acute trusts (the platform models acute demand) and capped at
    ``limit`` for a manageable demo footprint.
    """
    resp = requests.get(
        ODS_URL,
        params={"PrimaryRoleId": "RO197", "Status": "Active", "Limit": 250},
        headers={"User-Agent": "nhs-platform/1.0", "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    orgs = resp.json().get("Organisations", [])
    trusts: list[tuple[str, str, str, str, int]] = []
    for o in orgs:
        name = o.get("Name", "").title().replace("Nhs", "NHS")
        code = o.get("OrgId", "")
        if _type_for(o.get("Name", "")) != "Acute":
            continue
        trusts.append((code, name, _region_for(o.get("PostCode")), "Acute", _beds_for(code)))
        if len(trusts) >= limit:
            break
    if not trusts:
        raise RuntimeError("ODS returned no acute trusts")
    log.info("ods.trusts", count=len(trusts))
    return trusts
