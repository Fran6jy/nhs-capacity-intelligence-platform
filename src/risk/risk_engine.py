"""Composite Operational Risk Score.

```
score = 0.30 * z(bed_occupancy_pct)
      + 0.30 * [ z(waiting_list_growth_30d) + z(waiting_list_size) ]
      + 0.25 * z(vacancy_rate)
      + 0.15 * z(ae_surge_index)

< 0.0   -> Green
0.0–1.0 -> Amber
>= 1.0  -> Red
```

Each component is z-scored relative to the **national** distribution on the
latest available date so a trust is judged by its *peer* performance, not
absolute thresholds. Absolute thresholds vary by trust type (specialist vs
district general) and would mask structural issues.

An **absolute safety overlay** sits on top of the peer-relative score: any
trust breaching a hard limit (occupancy >= 95% or vacancy >= 15%) is escalated
regardless of how it ranks against its peers. This covers the blind spot of a
purely relative index — a system-wide surge where *every* trust is in trouble
would otherwise average out to Green. Only true percentages with recognised
safety lines go in the overlay; the A&E surge index is scale-relative and
stays in the z-scored composite only. The final classification is the worse
of the peer-relative and absolute verdicts.
"""
from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd

from src.config import settings
from src.utils.logging import get_logger

log = get_logger("risk_engine")


# Weighting per component (sum to 1.0)
WEIGHTS = {
    "bed_occupancy": 0.30,
    "waiting_list_growth": 0.30,
    "vacancy_rate": 0.25,
    "ae_surge": 0.15,
}

# We cap z-scores to keep the index robust to extreme outliers
Z_CLIP = 3.0

# Absolute safety overlay — breaches escalate a trust regardless of how it
# ranks against its peers. Peer-relative z-scores find the *worst* trust this
# week; these catch a system-wide surge where everyone is in trouble at once.
#
# Only metrics whose *absolute* value is clinically meaningful belong here:
# bed occupancy % and vacancy % are true percentages with recognised safety
# lines. The A&E surge index is a scale-relative signal (its magnitude depends
# on the aggregation grain), so it stays in the z-scored composite only and is
# deliberately excluded from the absolute overlay.
ABSOLUTE_RED = {
    "bed_occupancy": 95.0,   # % — sustained >95% is the recognised safety ceiling
    "vacancy_rate": 15.0,    # % — chronic understaffing
}
ABSOLUTE_AMBER = {
    "bed_occupancy": 92.0,
    "vacancy_rate": 12.0,
}

_SEVERITY = {"Green": 0, "Amber": 1, "Red": 2}
_SEVERITY_INV = {v: k for k, v in _SEVERITY.items()}


def _zscore(s: pd.Series, clip: float = Z_CLIP) -> pd.Series:
    mean, std = s.mean(), s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    z = (s - mean) / std
    return z.clip(-clip, clip)


def _classify(score: float) -> str:
    if score < 0.0:
        return "Green"
    if score < 1.0:
        return "Amber"
    return "Red"


def _absolute_class(row: pd.Series) -> str:
    """Absolute-threshold verdict, independent of peer ranking."""
    breaches_red = (
        row["bed_occupancy"] >= ABSOLUTE_RED["bed_occupancy"]
        or row["vacancy_rate"] >= ABSOLUTE_RED["vacancy_rate"]
    )
    if breaches_red:
        return "Red"
    breaches_amber = (
        row["bed_occupancy"] >= ABSOLUTE_AMBER["bed_occupancy"]
        or row["vacancy_rate"] >= ABSOLUTE_AMBER["vacancy_rate"]
    )
    return "Amber" if breaches_amber else "Green"


def _latest_components(fact: pd.DataFrame) -> pd.DataFrame:
    """Compute the latest-by-hospital components for the score."""
    f = fact.copy()
    f["date_key"] = pd.to_datetime(f["date_key"])
    latest = f["date_key"].max()

    # Tolerate facts that don't carry every grouping/metric column (e.g. a
    # hospital-level rollup with no specialty dimension): fill sensible defaults
    # so the composite score still computes.
    if "specialty_id" not in f.columns:
        f["specialty_id"] = "ALL"
    for col in ("waiting_list_size", "bed_occupancy_pct", "vacancy_rate", "ae_attendances"):
        if col not in f.columns:
            f[col] = 0.0

    # 30-day-ago snapshot for waiting-list growth. Pick the most recent
    # date <= (latest - 30d) per (hospital, specialty) so the comparison is
    # a true snapshot, not an accumulation of every historical day's value.
    cutoff = latest - pd.Timedelta(days=30)
    now = f[f["date_key"] == latest]
    past_candidates = f[f["date_key"] <= cutoff]
    past = (
        past_candidates
        .sort_values("date_key")
        .groupby(["hospital_id", "specialty_id"], as_index=False)
        .tail(1)[["hospital_id", "specialty_id", "waiting_list_size"]]
        .rename(columns={"waiting_list_size": "wl_past"})
    )
    cur = (
        now.groupby(["hospital_id", "specialty_id"], as_index=False)
        .agg({
            "waiting_list_size": "sum",
            "bed_occupancy_pct": "mean",
            "vacancy_rate": "mean",
            "ae_attendances": "sum",
        })
    )
    merged = cur.merge(past, on=["hospital_id", "specialty_id"], how="left")
    merged["wl_past"] = merged["wl_past"].fillna(merged["waiting_list_size"])
    merged["wl_growth_30d"] = (
        (merged["waiting_list_size"] - merged["wl_past"]) / merged["wl_past"].replace(0, np.nan)
    ).fillna(0.0)
    # Roll up to trust/hospital
    grp = (
        merged.groupby("hospital_id", as_index=False)
        .agg(
            bed_occupancy=("bed_occupancy_pct", "mean"),
            waiting_list_growth=("wl_growth_30d", "mean"),
            waiting_list_size=("waiting_list_size", "sum"),
            vacancy_rate=("vacancy_rate", "mean"),
            ae_attendances=("ae_attendances", "sum"),
        )
    )
    # A&E surge = z-score vs. same trust's own 7-day mean (intuitive surge)
    trust_window = (
        f[f["date_key"] >= latest - pd.Timedelta(days=7)]
        .groupby("hospital_id", as_index=False)["ae_attendances"].sum()
        .rename(columns={"ae_attendances": "ae_7d"})
    )
    trust_long = (
        f.groupby("hospital_id", as_index=False)["ae_attendances"].mean().rename(
            columns={"ae_attendances": "ae_daily_mean"}
        )
    )
    trust_long["ae_baseline_7d"] = trust_long["ae_daily_mean"] * 7
    grp = grp.merge(trust_window, on="hospital_id", how="left")
    grp = grp.merge(trust_long[["hospital_id", "ae_baseline_7d"]], on="hospital_id", how="left")
    grp["ae_surge_index"] = (grp["ae_7d"] - grp["ae_baseline_7d"]) / grp["ae_baseline_7d"].replace(0, np.nan)
    grp["ae_surge_index"] = grp["ae_surge_index"].fillna(0)
    grp["date_key"] = latest.date()
    return grp


def compute_risk(fact: pd.DataFrame) -> pd.DataFrame:
    components = _latest_components(fact)
    components["bed_occupancy_z"] = _zscore(components["bed_occupancy"])
    # Waiting-list pressure blends trend (growth rate) and standing backlog
    # (absolute level) so a large-but-stable list still registers as risk, and
    # the component stays meaningful even on a single-snapshot input.
    components["waiting_list_z"] = (
        _zscore(components["waiting_list_growth"]) + _zscore(components["waiting_list_size"])
    )
    components["vacancy_rate_z"]  = _zscore(components["vacancy_rate"])
    components["ae_surge_z"]      = _zscore(components["ae_surge_index"])

    components["score"] = (
        WEIGHTS["bed_occupancy"]     * components["bed_occupancy_z"]
        + WEIGHTS["waiting_list_growth"] * components["waiting_list_z"]
        + WEIGHTS["vacancy_rate"]    * components["vacancy_rate_z"]
        + WEIGHTS["ae_surge"]        * components["ae_surge_z"]
    ).round(3)

    # Peer-relative verdict from the composite z-score …
    relative_class = components["score"].apply(_classify)
    # … escalated by absolute safety breaches. Final verdict = the worse of the two.
    absolute_class = components.apply(_absolute_class, axis=1)
    components["classification_relative"] = relative_class.values
    components["classification_absolute"] = absolute_class.values
    components["classification"] = [
        _SEVERITY_INV[max(_SEVERITY[r], _SEVERITY[a])]
        for r, a in zip(relative_class, absolute_class)
    ]
    components["risk_id"] = range(1, len(components) + 1)
    components["components_json"] = components.apply(
        lambda r: json.dumps({
            "bed_occupancy_pct": float(r["bed_occupancy"]),
            "waiting_list_growth_30d": float(r["waiting_list_growth"]),
            "vacancy_rate": float(r["vacancy_rate"]),
            "ae_surge_index": float(r["ae_surge_index"]),
            # Which path drove the verdict, so the UI/AI layer can explain it.
            "trigger": (
                "absolute"
                if _SEVERITY[r["classification_absolute"]] > _SEVERITY[r["classification_relative"]]
                else "peer-relative"
            ),
        }),
        axis=1,
    )
    return components


def run() -> None:
    log.info("risk_engine.start")
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    fact = con.execute("SELECT * FROM hospital_activity_fact").fetch_df()
    con.close()

    risk = compute_risk(fact)
    keep = [
        "risk_id", "date_key", "hospital_id", "score", "classification", "components_json",
    ]
    risk = risk[keep]

    con = duckdb.connect(str(settings.warehouse_path))
    con.execute("DELETE FROM risk_score")
    con.register("df_risk", risk)
    con.execute("INSERT INTO risk_score SELECT * FROM df_risk")
    con.close()
    log.info("risk_engine.complete", rows=len(risk),
             red=int((risk.classification == "Red").sum()),
             amber=int((risk.classification == "Amber").sum()),
             green=int((risk.classification == "Green").sum()))


if __name__ == "__main__":
    run()
