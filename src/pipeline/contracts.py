"""Data contracts at the silver → gold boundary.

Silver deduplicates and clips, but nothing *asserted* anything: an occupancy
of 140%, a negative wait, a fact row whose hospital is absent from
``dim_hospital`` — all of it flowed into the warehouse, the models and the
risk score without a sound. The same silent-success pathology that bit the
infrastructure four times in one day existed in the data path.

These schemas fail the pipeline loudly at the point the data is about to
become the system of record. They are deliberately strict about the things a
model or a ratio would quietly absorb: ranges, nullability of keys, and
referential integrity between fact and dimensions.

Rows the models cannot use (no bed capacity, so no occupancy) are allowed to
carry nulls; rows that would *corrupt* a metric are not allowed at all.
"""
from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

from src.utils.logging import get_logger

log = get_logger("contracts")

# --------------------------------------------------------------------------- #
# Silver
# --------------------------------------------------------------------------- #
_TRUST_CODE = Check.str_matches(r"^[A-Z0-9]{3,5}$", error="trust_code must be 3–5 alphanumerics")

SILVER_HES = DataFrameSchema(
    {
        "trust_code": Column(str, _TRUST_CODE, nullable=False),
        "specialty": Column(str, nullable=False),
        "date": Column(pa.DateTime, nullable=False),
        "admissions": Column("Int64", Check.ge(0), nullable=True, coerce=True),
        "discharges": Column("Int64", Check.ge(0), nullable=True, coerce=True),
        "bed_occupancy_count": Column("Int64", Check.ge(0), nullable=True, coerce=True),
        "ae_attendances": Column("Int64", Check.ge(0), nullable=True, coerce=True),
        "referrals": Column("Int64", Check.ge(0), nullable=True, coerce=True),
    },
    unique=["trust_code", "specialty", "date"],
    strict=False,
    name="silver.hes",
)

SILVER_WAITING_LIST = DataFrameSchema(
    {
        "trust_code": Column(str, _TRUST_CODE, nullable=False),
        "specialty": Column(str, nullable=False),
        "period": Column(str, Check.str_matches(r"^\d{4}-\d{2}"), nullable=False),
        "waiting_list_size": Column(float, Check.in_range(0, 200_000), nullable=True, coerce=True),
        "median_wait_days": Column(float, Check.in_range(0, 365), nullable=True, coerce=True),
    },
    unique=["trust_code", "specialty", "period"],
    strict=False,
    name="silver.nhs_waiting_list",
)

SILVER_WORKFORCE = DataFrameSchema(
    {
        "trust_code": Column(str, _TRUST_CODE, nullable=False),
        "role": Column(str, nullable=False),
        "staff_count": Column(float, Check.ge(0), nullable=True, coerce=True),
        "vacancies": Column(float, Check.ge(0), nullable=True, coerce=True),
        "vacancy_rate": Column(float, Check.in_range(0, 50), nullable=True, coerce=True),
    },
    unique=["trust_code", "role"],
    strict=False,
    name="silver.workforce",
)

SILVER_ILLNESS = DataFrameSchema(
    {
        "date": Column(pa.DateTime, nullable=False, unique=True),
        "flu_index": Column(float, Check.in_range(0, 50), nullable=True, coerce=True),
        "covid_index": Column(float, Check.in_range(0, 50), nullable=True, coerce=True),
    },
    strict=False,
    name="silver.illness_trends",
)

SILVER_WEATHER = DataFrameSchema(
    {
        "date": Column(pa.DateTime, nullable=False),
        "region_id": Column(str, nullable=False),
        "avg_temp_c": Column(float, Check.in_range(-15, 40), nullable=True, coerce=True),
    },
    unique=["date", "region_id"],
    strict=False,
    name="silver.weather",
)

DIM_HOSPITAL = DataFrameSchema(
    {
        "hospital_id": Column(str, nullable=False, unique=True),
        "trust_code": Column(str, _TRUST_CODE, nullable=False),
        "region_id": Column(str, nullable=False),
        "bed_capacity": Column(int, Check.gt(0), nullable=False, coerce=True),
    },
    strict=False,
    name="dim_hospital",
)

DIM_SPECIALTY = DataFrameSchema(
    {"specialty_id": Column(str, nullable=False, unique=True)},
    strict=False, name="dim_specialty",
)

DIM_REGION = DataFrameSchema(
    {"region_id": Column(str, nullable=False, unique=True)},
    strict=False, name="dim_region",
)

SILVER_SCHEMAS: dict[str, DataFrameSchema] = {
    "hes": SILVER_HES,
    "nhs_waiting_list": SILVER_WAITING_LIST,
    "workforce": SILVER_WORKFORCE,
    "illness_trends": SILVER_ILLNESS,
    "weather": SILVER_WEATHER,
    "dim_hospital": DIM_HOSPITAL,
    "dim_specialty": DIM_SPECIALTY,
    "dim_region": DIM_REGION,
}

# --------------------------------------------------------------------------- #
# Gold
# --------------------------------------------------------------------------- #
# Occupancy is a demand/capacity ratio and legitimately exceeds 100% under
# surge (the KPI is labelled "capacity pressure" for that reason), but 200%
# means the capacity join went wrong, not that a trust is twice full.
GOLD_FACT = DataFrameSchema(
    {
        "activity_id": Column(int, nullable=False, unique=True, coerce=True),
        "date_key": Column(object, nullable=False),
        "hospital_id": Column(str, nullable=False),
        "specialty_id": Column(str, nullable=False),
        "region_id": Column(str, nullable=False),
        "admissions": Column(float, Check.ge(0), nullable=True, coerce=True),
        "discharges": Column(float, Check.ge(0), nullable=True, coerce=True),
        "bed_occupancy_pct": Column(float, Check.in_range(0, 200), nullable=True, coerce=True),
        "bed_occupancy_count": Column(float, Check.ge(0), nullable=True, coerce=True),
        "waiting_list_size": Column(float, Check.ge(0), nullable=True, coerce=True),
        "median_wait_days": Column(float, Check.in_range(0, 365), nullable=True, coerce=True),
        "staff_count": Column(float, Check.ge(0), nullable=True, coerce=True),
        "vacancies": Column(float, Check.ge(0), nullable=True, coerce=True),
        "vacancy_rate": Column(float, Check.in_range(0, 100), nullable=True, coerce=True),
        "ae_attendances": Column(float, Check.ge(0), nullable=True, coerce=True),
        "referrals": Column(float, Check.ge(0), nullable=True, coerce=True),
        "flu_index": Column(float, Check.in_range(0, 50), nullable=True, coerce=True),
        "covid_index": Column(float, Check.in_range(0, 50), nullable=True, coerce=True),
        "avg_temp_c": Column(float, Check.in_range(-15, 40), nullable=True, coerce=True),
    },
    unique=["date_key", "hospital_id", "specialty_id"],
    strict=False,
    name="gold.hospital_activity_fact",
)


class ContractViolation(RuntimeError):
    """A frame failed its contract. The message lists the failing checks."""


def _format_failures(err: pa.errors.SchemaErrors, limit: int = 8) -> str:
    cases = err.failure_cases
    lines = []
    for _, r in cases.head(limit).iterrows():
        lines.append(f"{r.get('column')}: {r.get('check')} (e.g. {r.get('failure_case')!r})")
    extra = len(cases) - limit
    return "; ".join(lines) + (f"; +{extra} more" if extra > 0 else "")


def validate(df: pd.DataFrame, schema: DataFrameSchema) -> pd.DataFrame:
    """Validate ``df`` against ``schema``; raise :class:`ContractViolation` on failure.

    ``lazy=True`` so every failing check is collected and reported together,
    rather than the first one stopping the run and hiding the rest.
    """
    try:
        out = schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as err:
        summary = _format_failures(err)
        log.error("contract.violated", schema=schema.name, rows=len(df), failures=summary)
        raise ContractViolation(f"{schema.name}: {summary}") from None
    log.info("contract.ok", schema=schema.name, rows=len(out))
    return out


def validate_fact_integrity(fact: pd.DataFrame, dim_hospital: pd.DataFrame,
                            dim_specialty: pd.DataFrame, dim_region: pd.DataFrame) -> None:
    """Referential integrity between the fact and its dimensions.

    A fact row pointing at a hospital, specialty or region that the dimension
    does not contain joins to nothing downstream: it vanishes from every view
    and every model input, silently.
    """
    problems = []
    for col, dim, key in (
        ("hospital_id", dim_hospital, "hospital_id"),
        ("specialty_id", dim_specialty, "specialty_id"),
        ("region_id", dim_region, "region_id"),
    ):
        missing = set(fact[col].dropna().unique()) - set(dim[key].astype(str))
        if missing:
            sample = sorted(missing)[:5]
            problems.append(f"{col}: {len(missing)} value(s) not in dimension, e.g. {sample}")
    if problems:
        log.error("contract.integrity_violated", problems=problems)
        raise ContractViolation("gold.hospital_activity_fact integrity: " + "; ".join(problems))
    log.info("contract.integrity_ok", rows=len(fact))
