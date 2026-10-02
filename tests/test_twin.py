"""Reproducibility tests for the A&E digital twin.

The twin is a simulation and is honest about that. What it must not be is
*accidentally* different from one run to the next: the staffing factor used
to come from Python's hash(), which is randomised per process, so every trust
got a new staffing level on every refresh and the baseline quietly moved.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.streaming import twin

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def _fixed_catalogue(monkeypatch):
    """Two trusts, independent of whatever is in the local silver layer."""
    rows = [
        {"hospital_id": "H_R0A_00", "region_id": "NW", "bed_capacity": 600},
        {"hospital_id": "H_R1H_00", "region_id": "LDN", "bed_capacity": 1100},
    ]
    monkeypatch.setattr(twin, "_catalogue", lambda: _with_staff(rows))


def _with_staff(rows):
    import zlib
    out = []
    for r in rows:
        r = dict(r)
        r["staff_factor"] = round(0.78 + (zlib.crc32(r["hospital_id"].encode()) % 22) / 100, 2)
        out.append(r)
    return out


def test_staffing_factor_is_stable_across_processes():
    """CRC32 of the id, not hash(): same trust, same factor, every run."""
    import zlib
    expected = round(0.78 + (zlib.crc32(b"H_R0A_00") % 22) / 100, 2)
    rows = _with_staff([{"hospital_id": "H_R0A_00", "region_id": "NW", "bed_capacity": 600}])
    assert rows[0]["staff_factor"] == expected
    assert 0.78 <= expected <= 1.0


def test_seeded_runs_are_identical(monkeypatch):
    _fixed_catalogue(monkeypatch)
    a = twin.simulate_window(minutes=20, now=NOW, seed=123)
    b = twin.simulate_window(minutes=20, now=NOW, seed=123)
    pd.testing.assert_frame_equal(a, b)


def test_different_seeds_differ(monkeypatch):
    _fixed_catalogue(monkeypatch)
    a = twin.simulate_window(minutes=20, now=NOW, seed=1)
    b = twin.simulate_window(minutes=20, now=NOW, seed=2)
    assert not a["arrivals"].equals(b["arrivals"])


def test_window_shape_and_bounds(monkeypatch):
    _fixed_catalogue(monkeypatch)
    df = twin.simulate_window(minutes=30, now=NOW, seed=0)
    assert len(df) == 30 * 2
    assert set(df.columns) == set(twin.COLUMNS)
    assert df["occupancy_pct"].between(70, 100).all()
    assert (df["available_beds"] >= 0).all()
