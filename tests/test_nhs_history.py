"""Tests for multi-year NHS England discovery and the RTT national time series.

The filename shapes here are real ones taken from the 2024-25, 2025-26 and
2026-27 collection pages; the parser has to handle all of them to assemble
a history, and must prefer a revised file over the original for a month.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion import nhs_england as ne


@pytest.mark.parametrize(
    "name, period",
    [
        ("February-2026-CSV-Dl8t54.csv", "2026-02"),
        ("Monthly-AE-March-2026-revised-flkg42.csv", "2026-03"),
        ("Monthly-AE-Nov-25-CSV-revised.csv", "2025-11"),
        ("Monthly-AE-December-2024.csv", "2024-12"),
        ("Monthly-AE-April-2024-revised.csv", "2024-04"),
        ("Full-CSV-data-file-Jul26-ZIP-4M-97ylx5.zip", "2026-07"),
        ("RTT-Overview-Timeseries-Including-Estimates-Jul26-XLS-116K.xlsx", "2026-07"),
    ],
)
def test_period_parsing_covers_every_published_shape(name, period):
    assert ne._period_from_name(name) == period


def test_revised_file_wins_regardless_of_page_order(monkeypatch):
    html = """
      <a href="https://x/uploads/Monthly-AE-October-2025-abc.csv">orig</a>
      <a href="https://x/uploads/Monthly-AE-October-2025-revised-xyz.csv">rev</a>
      <a href="https://x/uploads/Monthly-AE-September-2025-revised-1.csv">rev</a>
      <a href="https://x/uploads/Monthly-AE-September-2025-2.csv">orig (later)</a>
    """
    monkeypatch.setattr(ne, "_get", lambda url: type("R", (), {"text": html, "content": b""})())
    rel = ne._releases_on("https://x/page", ne.AE_CSV_LINK)
    assert set(rel) == {"2025-10", "2025-09"}
    assert "revised" in rel["2025-10"].url and "revised" in rel["2025-09"].url


def test_discover_walks_year_pages_only_as_far_as_needed(monkeypatch):
    pages = {
        "https://idx/": '<a href="ae-attendances-and-emergency-admissions-2026-27/">a</a>'
                        '<a href="ae-attendances-and-emergency-admissions-2025-26/">b</a>',
        "https://idx/ae-attendances-and-emergency-admissions-2026-27/":
            '<a href="https://x/August-2026-CSV-a.csv">a</a><a href="https://x/July-2026-CSV-b.csv">b</a>',
        "https://idx/ae-attendances-and-emergency-admissions-2025-26/":
            '<a href="https://x/Monthly-AE-March-2026-revised-c.csv">c</a>',
    }
    fetched: list[str] = []

    def fake_get(url):
        fetched.append(url)
        return type("R", (), {"text": pages[url], "content": b""})()

    monkeypatch.setattr(ne, "_get", fake_get)

    two = ne._discover("https://idx/", ne.AE_YEAR_SLUG, ne.AE_CSV_LINK, months=2)
    assert [r.period for r in two] == ["2026-08", "2026-07"]
    assert not any("2025-26" in u for u in fetched)  # did not need the older page

    three = ne._discover("https://idx/", ne.AE_YEAR_SLUG, ne.AE_CSV_LINK, months=3)
    assert [r.period for r in three] == ["2026-08", "2026-07", "2026-03"]


def _raw_timeseries() -> pd.DataFrame:
    """A minimal replica of the overview workbook read with header=None."""
    ncols = 24
    rows = [[np.nan] * ncols for _ in range(14)]
    rows[10][2], rows[10][3] = "Month", "Incomplete RTT pathways"
    rows[11][3], rows[11][22] = "Median wait (weeks)", "Total waiting (mil) with estimates"
    data = [
        (pd.Timestamp("2026-06-01"), 11.8, 0.651, 2_500_000, 115_000, 7_300_000),
        (pd.Timestamp("2026-07-01"), 12.0, 0.654, 2_535_685, 111_379, 7_328_252),
    ]
    for month, med, pct, over18, over52, total in data:
        r = [np.nan] * ncols
        r[2], r[3], r[8], r[10], r[12], r[22] = month, med, pct, over18, over52, total
        rows.append(r)
    rows.append([np.nan, "1. Footnote text", *([np.nan] * (ncols - 2))])
    return pd.DataFrame(rows)


def test_rtt_timeseries_tidy_keeps_counts_as_counts():
    """Regression: the column is labelled '(mil)' but holds full counts.
    Multiplying by a million reported a 7.3 trillion waiting list."""
    out = ne._tidy_rtt_timeseries(_raw_timeseries())
    assert list(out["period"]) == ["2026-06", "2026-07"]
    assert int(out["total_waiting"].iat[-1]) == 7_328_252
    assert 7_000_000 < int(out["total_waiting"].iat[-1]) < 8_000_000
    assert out["within_18_weeks_pct"].iat[-1] == 65.4
    assert int(out["over_52_weeks"].iat[-1]) == 111_379
    assert out["median_wait_weeks"].iat[-1] == 12.0


def test_rtt_timeseries_drops_footnotes_and_rejects_layout_drift():
    out = ne._tidy_rtt_timeseries(_raw_timeseries())
    assert len(out) == 2  # the footnote row is not a month
    drifted = _raw_timeseries()
    drifted.iat[10, 3] = "Completed admitted"
    with pytest.raises(ValueError, match="layout changed"):
        ne._tidy_rtt_timeseries(drifted)
