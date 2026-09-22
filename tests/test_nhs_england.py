"""Tests for real NHS England open-statistics ingestion.

Both parsers hit the same class of bug during development: NHS England mixes
pre-aggregated subtotal rows into the provider rows, so summing a file as
published double-counts every figure. The failure is silent — ratios such as
four-hour performance stay correct while every absolute number is twice what
it should be — so it is pinned here rather than left to sanity-checking.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion.nhs_england import (
    RTT_INCOMPLETE,
    _band_weeks,
    _period_from_name,
    _tidy_ae,
    _tidy_rtt,
)


def _ae_frame() -> pd.DataFrame:
    """Two providers plus the national TOTAL roll-up NHS England embeds."""
    return pd.DataFrame(
        [
            {
                "Period": "MSitAE-AUGUST-2026", "Org Code": "RAA",
                "Parent Org": "NHS ENGLAND LONDON", "Org name": "ALPHA TRUST",
                "A&E attendances Type 1": 1000, "A&E attendances Type 2": 0,
                "A&E attendances Other A&E Department": 200,
                "Attendances over 4hrs Type 1": 250,
                "Patients who have waited 12+ hrs from DTA to admission": 10,
                "Emergency admissions via A&E - Type 1": 300,
                "Other emergency admissions": 50,
            },
            {
                "Period": "MSitAE-AUGUST-2026", "Org Code": "RBB",
                "Parent Org": "NHS ENGLAND MIDLANDS", "Org name": "BETA TRUST",
                "A&E attendances Type 1": 800, "A&E attendances Type 2": 0,
                "A&E attendances Other A&E Department": 0,
                "Attendances over 4hrs Type 1": 200,
                "Patients who have waited 12+ hrs from DTA to admission": 5,
                "Emergency admissions via A&E - Type 1": 200,
                "Other emergency admissions": 0,
            },
            {
                "Period": "TOTAL", "Org Code": "TOTAL", "Parent Org": "TOTAL",
                "Org name": "TOTAL",
                "A&E attendances Type 1": 1800, "A&E attendances Type 2": 0,
                "A&E attendances Other A&E Department": 200,
                "Attendances over 4hrs Type 1": 450,
                "Patients who have waited 12+ hrs from DTA to admission": 15,
                "Emergency admissions via A&E - Type 1": 500,
                "Other emergency admissions": 50,
            },
        ]
    )


def test_ae_excludes_the_embedded_total_row():
    out = _tidy_ae(_ae_frame(), "2026-08")
    assert len(out) == 2
    assert "TOTAL" not in set(out["org_code"])
    # 2000 is the true national figure; 4000 would be the double-counted one.
    assert out["attendances"].sum() == 2000
    assert out["emergency_admissions"].sum() == 550


def test_ae_computes_four_hour_performance():
    out = _tidy_ae(_ae_frame(), "2026-08").set_index("org_code")
    assert out.loc["RAA", "four_hour_performance_pct"] == 79.2  # 1 - 250/1200
    assert out.loc["RBB", "four_hour_performance_pct"] == 75.0  # 1 - 200/800


def _rtt_frame() -> pd.DataFrame:
    """One provider, two specialties plus a Total row, across two part types."""
    bands = {
        "Gt 00 To 01 Weeks SUM 1": 0,
        "Gt 10 To 11 Weeks SUM 1": 0,
        "Gt 20 To 21 Weeks SUM 1": 0,
        "Gt 52 To 53 Weeks SUM 1": 0,
    }

    def row(part: str, specialty: str, counts: list[int]) -> dict:
        r = {
            "Period": "RTT-July-2026", "Provider Org Code": "RAA",
            "Provider Parent Name": "NHS ENGLAND LONDON",
            "RTT Part Type": part, "Treatment Function Name": specialty,
        }
        r.update(dict(zip(bands, counts, strict=True)))
        return r

    return pd.DataFrame(
        [
            row(RTT_INCOMPLETE, "Ophthalmology Service", [100, 50, 20, 10]),
            row(RTT_INCOMPLETE, "General Surgery Service", [40, 20, 0, 0]),
            row(RTT_INCOMPLETE, "Total", [140, 70, 20, 10]),
            row("Part_2A", "Ophthalmology Service", [5, 5, 5, 5]),
        ]
    )


def test_rtt_excludes_total_specialty_and_other_part_types():
    out = _tidy_rtt(_rtt_frame(), "2026-07")
    assert set(out["specialty_name"]) == {"Ophthalmology Service", "General Surgery Service"}
    # 240 is the real total; 480 would double-count the Total row, and the
    # Part_2A (decision-to-admit) rows must not be added either.
    assert out["total_waiting"].sum() == 240


def test_rtt_counts_long_waits_by_band_threshold():
    out = _tidy_rtt(_rtt_frame(), "2026-07").set_index("specialty_name")
    eye = out.loc["Ophthalmology Service"]
    assert eye["total_waiting"] == 180
    assert eye["waiting_over_18_weeks"] == 30  # the 20-21 and 52-53 bands
    assert eye["waiting_over_52_weeks"] == 10
    assert out.loc["General Surgery Service", "waiting_over_18_weeks"] == 0


def test_rtt_part_type_is_the_waiting_list_not_the_dta_subset():
    """Part_2A is "Incomplete Pathways with DTA" and is ~3x too small."""
    assert RTT_INCOMPLETE == "Part_2"


def test_band_midpoints():
    assert _band_weeks("Gt 04 To 05 Weeks SUM 1") == 4.5
    assert _band_weeks("Gt 104 Weeks SUM 1") == 104.5
    assert _band_weeks("Total All") is None


def test_period_parsing_across_the_published_name_shapes():
    assert _period_from_name("August-2026-CSV-De2k3n.csv") == "2026-08"
    assert _period_from_name("MSitAE-AUGUST-2026") == "2026-08"
    assert _period_from_name("RTT-July-2026") == "2026-07"
    assert _period_from_name("Full-CSV-data-file-Jul26-ZIP-4M-97ylx5.zip") == "2026-07"
    assert _period_from_name("no-date-here.csv") is None
