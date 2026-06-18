"""Recommendation engine — prescriptive actions for at-risk trusts.

The engine blends rule-based logic on the latest risk score with
LLM-generated action text so outputs are (a) deterministic and
(b) human-readable. It writes rows to `recommendation` in the warehouse.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from src.config import settings
from src.utils.logging import get_logger

log = get_logger("recommender")


# --------------------------------------------------------------------- rules
# Threshold-based, deterministic. The recommender LLM can embellish later.
RULES = [
    {
        "category": "Staffing",
        "trigger": lambda r: r.get("vacancy_rate", 0) > 9,
        "action_template": (
            "Trust {hospital_id} has a {vacancy_rate:.1f}% vacancy rate. "
            "Open international recruitment + bank incentive shifts; prioritise "
            "the {top_role} role."
        ),
        "expected_impact": "Reduce vacancy rate by ~3pp in 60 days.",
    },
    {
        "category": "Capacity",
        "trigger": lambda r: r.get("bed_occupancy_pct", 0) > 92,
        "action_template": (
            "Bed occupancy at {bed_occupancy_pct:.1f}% — open 8–12 surge beds "
            "and review discharge pathway for the 5 longest-stay patients."
        ),
        "expected_impact": "Drop occupancy below 90% within 14 days.",
    },
    {
        "category": "Workload",
        "trigger": lambda r: r.get("waiting_list_growth_30d", 0) > 0.08,
        "action_template": (
            "Waiting list grew {waiting_list_growth_30d*100:.1f}% in 30 days. "
            "Redistribute elective lists to partner trusts and extend weekend clinics."
        ),
        "expected_impact": "Stabilise list size within 45 days.",
    },
    {
        "category": "Pathway",
        "trigger": lambda r: r.get("ae_surge_index", 0) > 0.2,
        "action_template": (
            "A&E attendances {ae_surge_pct:.0f}% above 7-day baseline. "
            "Activate same-day emergency care unit and divert ambulatory cases "
            "to urgent treatment centres."
        ),
        "expected_impact": "Restore A&E flow to baseline within 7 days.",
    },
]


def _role_with_highest_vacancy(workforce: pd.DataFrame, trust_code: str) -> str:
    sub = workforce[workforce["trust_code"] == trust_code]
    if sub.empty:
        return "Nursing"
    return str(sub.sort_values("vacancy_rate", ascending=False).iloc[0]["role"])


def _run_llm_action(prompt: str) -> str:
    """Optional LLM embellishment of a rule-based action.

    Off by default: the batch pipeline must stay fast and deterministic, so it
    does not block on (potentially slow) live LLM calls. Enable by setting
    ``RECOMMENDER_USE_LLM=true``. Always falls back to the rule text on error.
    """
    if not settings.recommender_use_llm:
        return prompt
    try:
        from src.llm.prompts import SYSTEM_RECOMMENDER
        from src.llm.rag import get_llm
        llm = get_llm()
        if llm is None:
            return prompt
        return llm.invoke([{"role": "system", "content": SYSTEM_RECOMMENDER},
                            {"role": "user", "content": prompt}]).content
    except Exception:  # noqa: BLE001
        return prompt


def generate_recommendations() -> pd.DataFrame:
    log.info("recommender.start")
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    risk = con.execute(
        "SELECT * FROM risk_score "
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY hospital_id ORDER BY date_key DESC) = 1"
    ).fetch_df()
    if risk.empty:
        log.warning("recommender.no_risk_scores")
        con.close()
        return pd.DataFrame()

    # Pull the underlying components from hospital_activity_fact. The risk
    # score only stores the *z-scored composite*; the per-component values
    # we need to evaluate rules live in the fact table.
    fact = con.execute(
        """
        SELECT f.hospital_id,
               AVG(f.bed_occupancy_pct) AS bed_occupancy_pct,
               AVG(f.vacancy_rate)      AS vacancy_rate,
               AVG(f.ae_attendances)    AS ae_attendances
        FROM hospital_activity_fact f
        WHERE f.date_key = (SELECT MAX(date_key) FROM hospital_activity_fact)
        GROUP BY f.hospital_id
        """
    ).fetch_df()

    # Pull the A&E surge index out of the components_json (it's not a fact column).
    surge = con.execute(
        """
        SELECT hospital_id,
               AVG(CAST(json_extract(components_json, '$.ae_surge_index') AS DOUBLE)) AS ae_surge_index
        FROM risk_score
        GROUP BY hospital_id
        """
    ).fetch_df()

    # Pull 30-day waiting-list growth from the fact table (true snapshot).
    waiting_growth = con.execute(
        """
        WITH latest AS (SELECT MAX(date_key) AS d FROM hospital_activity_fact),
             now   AS (SELECT hospital_id, specialty_id, waiting_list_size
                       FROM hospital_activity_fact
                       WHERE date_key = (SELECT d FROM latest)),
             past  AS (
                 SELECT hospital_id, specialty_id, waiting_list_size AS wl_past
                 FROM (
                     SELECT hospital_id, specialty_id, date_key, waiting_list_size,
                            ROW_NUMBER() OVER (PARTITION BY hospital_id, specialty_id
                                               ORDER BY date_key DESC) AS rn
                     FROM hospital_activity_fact
                     WHERE date_key <= (SELECT d - INTERVAL '30 day' FROM latest)
                 ) WHERE rn = 1
             ),
             g AS (
                 SELECT n.hospital_id, n.specialty_id,
                        (n.waiting_list_size - COALESCE(p.wl_past, n.waiting_list_size))
                            / NULLIF(COALESCE(p.wl_past, n.waiting_list_size), 0) AS wl_growth_30d
                 FROM now n LEFT JOIN past p USING (hospital_id, specialty_id)
             )
        SELECT hospital_id, AVG(wl_growth_30d) AS waiting_list_growth_30d
        FROM g GROUP BY hospital_id
        """
    ).fetch_df()

    # hospital_id ↔ trust_code (workforce is keyed by trust_code)
    trust_map = con.execute("SELECT hospital_id, trust_code FROM dim_hospital").fetch_df()
    con.close()

    workforce = pd.read_parquet(settings.silver_path / "workforce.parquet")

    df = risk.merge(fact, on="hospital_id", how="left")
    df = df.merge(surge, on="hospital_id", how="left")
    df = df.merge(waiting_growth, on="hospital_id", how="left")
    df = df.merge(trust_map, on="hospital_id", how="left")

    rows: list[dict] = []
    rid = 1
    today = date.today()
    for _, r in df.iterrows():
        comps = {
            "hospital_id":        r["hospital_id"],
            "bed_occupancy_pct":  float(r.get("bed_occupancy_pct") or 0),
            "vacancy_rate":       float(r.get("vacancy_rate") or 0),
            "ae_surge_index":     float(r.get("ae_surge_index") or 0),
            "waiting_list_growth_30d": float(r.get("waiting_list_growth_30d") or 0),
            "ae_surge_pct":       float(r.get("ae_surge_index") or 0) * 100,
            "top_role":           _role_with_highest_vacancy(workforce, r.get("trust_code") or ""),
        }
        if r["classification"] == "Green":
            continue
        severity = "High" if r["classification"] == "Red" else "Medium"
        for rule in RULES:
            if rule["trigger"](comps):
                action_text = rule["action_template"].format(**comps)
                action_text = _run_llm_action(action_text)
                rows.append(
                    {
                        "recommendation_id": rid,
                        "date_key": today,
                        "hospital_id": comps["hospital_id"],
                        "severity": severity,
                        "category": rule["category"],
                        "action": action_text,
                        "expected_impact": rule["expected_impact"],
                    }
                )
                rid += 1
    if not rows:
        log.info("recommender.no_recommendations")
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    log.info("recommender.complete", rows=len(out))
    return out


def run() -> None:
    recs = generate_recommendations()
    if recs.empty:
        return
    con = duckdb.connect(str(settings.warehouse_path))
    con.execute("DELETE FROM recommendation")
    con.register("df_rec", recs)
    con.execute("INSERT INTO recommendation SELECT * FROM df_rec")
    con.close()


if __name__ == "__main__":
    run()
