"""Tests for peer-relative risk on real providers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.risk.provider_risk import compute_provider_risk


def _rtt(n: int = 40) -> pd.DataFrame:
    rows = []
    for i in range(n):
        total = 10_000
        over18 = int(total * (0.25 + 0.01 * i))          # 25% … 64% breach
        over52 = int(total * (0.005 + 0.002 * i))
        rows.append({"period": "2026-07", "org_code": f"P{i:03d}", "region_name": "R",
                     "specialty_name": "S", "total_waiting": total,
                     "waiting_over_18_weeks": over18, "waiting_over_52_weeks": over52})
    return pd.DataFrame(rows)


def _ae(n: int = 30) -> pd.DataFrame:
    rows = []
    for i in range(n):
        att = 20_000
        rows.append({"period": "2026-08", "org_code": f"P{i:03d}", "org_name": f"Trust {i}",
                     "region_name": "R", "attendances": att,
                     "breaches_4hr": int(att * (0.15 + 0.01 * i)),      # 85% … 56% perf
                     "twelve_hour_waits": 10 * i, "emergency_admissions": 4000})
    return pd.DataFrame(rows)


def test_scores_cover_every_provider_from_either_source():
    out = compute_provider_risk(_rtt(40), _ae(30))
    assert len(out) == 40                       # 30 in both, 10 RTT-only
    assert set(out["coverage"]) == {"rtt+ae", "rtt"}
    assert out["peer_count"].iat[0] == 40
    assert out["score"].is_monotonic_decreasing


def test_worst_breach_rates_score_highest():
    out = compute_provider_risk(_rtt(40), _ae(30)).set_index("org_code")
    assert out.loc["P029", "score"] > out.loc["P000", "score"]
    assert out.loc["P000", "classification"] == "Green"


def test_absolute_overlay_escalates_a_collapsed_provider():
    """A provider far below the standard must be Red even if its peers are too."""
    rtt = _rtt(5)
    rtt.loc[rtt["org_code"] == "P004", "waiting_over_18_weeks"] = 9_000  # 10% within 18w
    out = compute_provider_risk(rtt, pd.DataFrame()).set_index("org_code")
    assert out.loc["P004", "classification"] == "Red"
    assert out.loc["P004", "trigger"] == "absolute"
    assert out.loc["P004", "coverage"] == "rtt"


def test_components_are_explained_in_json():
    out = compute_provider_risk(_rtt(10), _ae(10))
    comps = json.loads(out.iloc[0]["components_json"])
    assert set(comps) == {"within_18_weeks_pct", "long_wait_share_pct",
                          "four_hour_performance_pct", "twelve_hour_per_1k"}


def test_ae_only_input_still_scores():
    out = compute_provider_risk(pd.DataFrame(), _ae(12))
    assert len(out) == 12 and set(out["coverage"]) == {"ae"}
    assert out["within_18_weeks_pct"].isna().all()


def test_empty_inputs_give_empty_output():
    assert compute_provider_risk(pd.DataFrame(), pd.DataFrame()).empty
