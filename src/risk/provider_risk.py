"""Peer-relative operational risk on real NHS providers.

The original risk engine scores sixteen synthetic trusts on synthetic daily
data, and z-scores against a "national distribution" of sixteen points. This
one scores the providers NHS England actually publishes — 533 with an RTT
waiting list, 182 with A&E activity — on their published monthly figures, so
the peer set is a real distribution and the inputs are real.

Components (all oriented so that higher = worse):

* ``rtt_breach``   — share of the waiting list beyond 18 weeks
* ``rtt_long_wait`` — share of the waiting list beyond 52 weeks
* ``ae_breach``    — share of A&E attendances beyond four hours
* ``ae_twelve_hr`` — twelve-hour DTA waits per 1,000 attendances

Each is z-scored against the latest month's peer distribution and clipped, then
combined with the same judgement weights as the synthetic engine. An absolute
overlay escalates any provider past a published standard by a wide margin
(RTT within-18-weeks below 50%, four-hour performance below 60%), so a
system-wide collapse cannot average out to Green.

Providers appear in only one of the two sources (community trusts have RTT
lists but no type-1 A&E, for instance); components they lack are neutral
(z = 0) and the ``coverage`` column says which inputs informed the score.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.utils.logging import get_logger

log = get_logger("risk.provider")

WEIGHTS = {"rtt_breach": 0.30, "rtt_long_wait": 0.25, "ae_breach": 0.30, "ae_twelve_hr": 0.15}
Z_CLIP = 3.0

#: Absolute escalation lines. Far past the published standards (92% / 95%),
#: because the standards themselves have not been met nationally for years and
#: using them as "Red" would classify almost every provider the same.
ABSOLUTE_RED = {"within_18_weeks_pct": 50.0, "four_hour_performance_pct": 60.0}
ABSOLUTE_AMBER = {"within_18_weeks_pct": 58.0, "four_hour_performance_pct": 70.0}

_SEV = {"Green": 0, "Amber": 1, "Red": 2}
_SEV_INV = {v: k for k, v in _SEV.items()}


def _z(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return ((s - s.mean()) / std).clip(-Z_CLIP, Z_CLIP)


def _classify_relative(score: float) -> str:
    return "Green" if score < 0.0 else ("Amber" if score < 1.0 else "Red")


def _classify_absolute(row: pd.Series) -> str:
    w18, fh = row.get("within_18_weeks_pct"), row.get("four_hour_performance_pct")
    red = (pd.notna(w18) and w18 < ABSOLUTE_RED["within_18_weeks_pct"]) or (
        pd.notna(fh) and fh < ABSOLUTE_RED["four_hour_performance_pct"])
    if red:
        return "Red"
    amber = (pd.notna(w18) and w18 < ABSOLUTE_AMBER["within_18_weeks_pct"]) or (
        pd.notna(fh) and fh < ABSOLUTE_AMBER["four_hour_performance_pct"])
    return "Amber" if amber else "Green"


def _latest(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["period"] == df["period"].max()] if not df.empty else df


def compute_provider_risk(rtt_monthly: pd.DataFrame, ae_monthly: pd.DataFrame) -> pd.DataFrame:
    """Score every provider in the latest month of each source."""
    parts = []

    rtt = _latest(rtt_monthly)
    if not rtt.empty:
        r = rtt.groupby("org_code", as_index=False).agg(
            region_name=("region_name", "first"),
            total_waiting=("total_waiting", "sum"),
            over_18=("waiting_over_18_weeks", "sum"),
            over_52=("waiting_over_52_weeks", "sum"),
        )
        r = r[r["total_waiting"] > 0]
        r["rtt_breach"] = r["over_18"] / r["total_waiting"]
        r["rtt_long_wait"] = r["over_52"] / r["total_waiting"]
        r["within_18_weeks_pct"] = ((1 - r["rtt_breach"]) * 100).round(1)
        r["rtt_period"] = rtt["period"].iat[0]
        parts.append(r[["org_code", "region_name", "total_waiting", "rtt_breach",
                        "rtt_long_wait", "within_18_weeks_pct", "rtt_period"]])

    ae = _latest(ae_monthly)
    if not ae.empty:
        a = ae.groupby("org_code", as_index=False).agg(
            org_name=("org_name", "first"), ae_region=("region_name", "first"),
            attendances=("attendances", "sum"), breaches=("breaches_4hr", "sum"),
            twelve=("twelve_hour_waits", "sum"),
        )
        a = a[a["attendances"] > 0]
        a["ae_breach"] = a["breaches"] / a["attendances"]
        a["ae_twelve_hr"] = a["twelve"] / a["attendances"] * 1000
        a["four_hour_performance_pct"] = ((1 - a["ae_breach"]) * 100).round(1)
        a["ae_period"] = ae["period"].iat[0]
        parts.append(a[["org_code", "org_name", "ae_region", "attendances", "ae_breach",
                        "ae_twelve_hr", "four_hour_performance_pct", "ae_period"]])

    if not parts:
        return pd.DataFrame()

    df = parts[0]
    for p in parts[1:]:
        df = df.merge(p, on="org_code", how="outer")
    if "region_name" not in df.columns:
        df["region_name"] = np.nan
    if "ae_region" in df.columns:
        df["region_name"] = df["region_name"].fillna(df["ae_region"])
        df = df.drop(columns=["ae_region"])
    if "org_name" not in df.columns:
        df["org_name"] = np.nan

    comps = list(WEIGHTS)
    for c in comps:
        if c not in df.columns:
            df[c] = np.nan
        df[f"{c}_z"] = _z(df[c]).where(df[c].notna(), 0.0)

    df["score"] = sum(WEIGHTS[c] * df[f"{c}_z"] for c in comps).round(3)
    rel = df["score"].apply(_classify_relative)
    absolute = df.apply(_classify_absolute, axis=1)
    df["classification"] = [_SEV_INV[max(_SEV[x], _SEV[y])] for x, y in zip(rel, absolute, strict=True)]
    df["coverage"] = np.select(
        [df["rtt_breach"].notna() & df["ae_breach"].notna(), df["rtt_breach"].notna()],
        ["rtt+ae", "rtt"], default="ae",
    )
    df["trigger"] = [
        "absolute" if _SEV[y] > _SEV[x] else "peer-relative" for x, y in zip(rel, absolute, strict=True)
    ]
    df["components_json"] = df.apply(
        lambda r: json.dumps({
            "within_18_weeks_pct": None if pd.isna(r.get("within_18_weeks_pct")) else float(r["within_18_weeks_pct"]),
            "long_wait_share_pct": None if pd.isna(r.get("rtt_long_wait")) else round(float(r["rtt_long_wait"]) * 100, 2),
            "four_hour_performance_pct": None if pd.isna(r.get("four_hour_performance_pct")) else float(r["four_hour_performance_pct"]),
            "twelve_hour_per_1k": None if pd.isna(r.get("ae_twelve_hr")) else round(float(r["ae_twelve_hr"]), 2),
        }), axis=1,
    )
    df["peer_count"] = len(df)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    keep = ["org_code", "org_name", "region_name", "coverage", "score", "classification", "trigger",
            "within_18_weeks_pct", "four_hour_performance_pct", "total_waiting", "attendances",
            "rtt_period", "ae_period", "peer_count", "components_json"]
    for k in keep:
        if k not in df.columns:
            df[k] = np.nan
    log.info("provider_risk.complete", providers=len(df),
             red=int((df["classification"] == "Red").sum()),
             amber=int((df["classification"] == "Amber").sum()))
    return df[keep]
