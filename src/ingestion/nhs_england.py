"""Real NHS England open statistics: monthly RTT and A&E, at provider level.

This is genuinely published data, not a synthetic stand-in. Two monthly
releases are ingested:

* **RTT** (Referral to Treatment) — the incomplete-pathway waiting list by
  provider and treatment function, as a zipped full CSV extract (~82MB
  uncompressed, 121 columns: 104 weekly waiting bands plus totals).
* **A&E** — attendances, four-hour breaches, twelve-hour DTA waits and
  emergency admissions by provider, as a monthly CSV.

Why the URLs are discovered rather than constructed
---------------------------------------------------
NHS England appends a rotating token to every upload, e.g.
``Full-CSV-data-file-Jul26-ZIP-4M-97ylx5.zip``. That token is not derivable,
so a constructed URL works until the next publication and then 404s silently.
The collection page is therefore scraped for links, and the collection page
*itself* is discovered from the work-area index so the ingester survives the
April financial-year rollover without a code change.

Everything degrades to an empty frame rather than raising: the batch pipeline
must not fail because a government website changed its markup.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.logging import get_logger

log = get_logger("ingestion.nhs_england")

WORK_AREA = "https://www.england.nhs.uk/statistics/statistical-work-areas"
AE_INDEX = f"{WORK_AREA}/ae-waiting-times-and-activity/"
RTT_INDEX = f"{WORK_AREA}/rtt-waiting-times/"

AE_YEAR_SLUG = re.compile(r"ae-attendances-and-emergency-admissions-(\d{4}-\d{2})/?", re.I)
RTT_YEAR_SLUG = re.compile(r"rtt-data-(\d{4}-\d{2})/?", re.I)

AE_CSV_LINK = re.compile(r'href="([^"]*?-CSV-[^"]*?\.csv)"', re.I)
RTT_ZIP_LINK = re.compile(r'href="([^"]*?Full-CSV-data-file[^"]*?\.zip)"', re.I)

TIMEOUT = 120
USER_AGENT = "nhs-capacity-intelligence-platform/1.0 (open data ingestion)"

MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}


@dataclass(frozen=True)
class Release:
    """One published monthly file."""

    url: str
    period: str  # YYYY-MM


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get(url: str) -> requests.Response:
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp


def _period_from_name(name: str) -> str | None:
    """Pull YYYY-MM out of a file name or a Period cell.

    Handles the several shapes NHS England uses: ``August-2026-CSV``,
    ``MSitAE-AUGUST-2026``, ``RTT-July-2026`` and ``...-Jul26-ZIP...``.
    """
    full = re.search(r"(" + "|".join(MONTHS) + r")[-_ ]*(\d{4})", name, re.I)
    if full:
        return f"{int(full.group(2)):04d}-{MONTHS[full.group(1).upper()]:02d}"

    short = re.search(r"\b([A-Z][a-z]{2})(\d{2})\b", name)
    if short:
        for label, num in MONTHS.items():
            if label.startswith(short.group(1).upper()):
                return f"20{short.group(2)}-{num:02d}"
    return None


def _latest_year_page(index_url: str, slug: re.Pattern[str]) -> str | None:
    """Find the newest financial-year collection page linked from an index."""
    html = _get(index_url).text
    years = {m.group(1): m.group(0) for m in slug.finditer(html)}
    if not years:
        log.warning("nhs_england.no_year_page", index=index_url)
        return None
    newest = max(years)
    href = years[newest]
    url = href if href.startswith("http") else f"{index_url.rstrip('/')}/{href.lstrip('/')}"
    log.info("nhs_england.year_page", year=newest, url=url)
    return url


def _discover(index_url: str, slug: re.Pattern[str], link: re.Pattern[str]) -> list[Release]:
    """Return published releases, newest first."""
    page = _latest_year_page(index_url, slug)
    if not page:
        return []

    html = _get(page).text
    seen: dict[str, Release] = {}
    for url in link.findall(html):
        period = _period_from_name(url.rsplit("/", 1)[-1])
        if period and period not in seen:
            seen[period] = Release(url=url, period=period)
    return [seen[p] for p in sorted(seen, reverse=True)]


# --------------------------------------------------------------------------- #
# A&E
# --------------------------------------------------------------------------- #
def _drop_aggregate_rows(raw: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Remove NHS England's pre-aggregated subtotal rows.

    The A&E extract mixes regional and national roll-ups into the provider
    rows, marked by the literal ``TOTAL`` in the Period and Parent Org columns.
    Summing the file as-published therefore double-counts every figure — a
    silent 2x error that leaves ratios such as four-hour performance looking
    perfectly correct while every absolute number is wrong.
    """
    mask = pd.Series(True, index=raw.index)
    for col in columns:
        if col in raw.columns:
            mask &= raw[col].astype(str).str.strip().str.upper() != "TOTAL"
    return raw[mask]


def _tidy_ae(raw: pd.DataFrame, period: str) -> pd.DataFrame:
    raw = _drop_aggregate_rows(raw, ["Period", "Parent Org", "Org Code"])

    def total(prefix: str) -> pd.Series:
        cols = [c for c in raw.columns if c.startswith(prefix)]
        return raw[cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)

    attendances = total("A&E attendances")
    breaches = total("Attendances over 4hrs")
    admissions = total("Emergency admissions via A&E") + total("Other emergency admissions")
    twelve_hour = pd.to_numeric(
        raw.get("Patients who have waited 12+ hrs from DTA to admission"), errors="coerce"
    ).fillna(0)

    out = pd.DataFrame(
        {
            "period": period,
            "org_code": raw["Org Code"].astype(str).str.strip(),
            "org_name": raw["Org name"].astype(str).str.strip(),
            "region_name": raw["Parent Org"].astype(str).str.strip(),
            "attendances": attendances.astype("int64"),
            "breaches_4hr": breaches.astype("int64"),
            "twelve_hour_waits": twelve_hour.astype("int64"),
            "emergency_admissions": admissions.astype("int64"),
        }
    )
    out = out[out["attendances"] > 0].copy()
    out["four_hour_performance_pct"] = (
        (1 - out["breaches_4hr"] / out["attendances"]) * 100
    ).round(1)
    return out


def fetch_ae_monthly(months: int = 3) -> pd.DataFrame:
    """Provider-level A&E activity for the most recent published months."""
    try:
        releases = _discover(AE_INDEX, AE_YEAR_SLUG, AE_CSV_LINK)[:months]
    except Exception as exc:  # noqa: BLE001
        log.warning("nhs_england.ae_discovery_failed", error=str(exc))
        return pd.DataFrame()

    frames = []
    for rel in releases:
        try:
            raw = pd.read_csv(io.BytesIO(_get(rel.url).content))
            frames.append(_tidy_ae(raw, rel.period))
            log.info("nhs_england.ae_loaded", period=rel.period, rows=len(frames[-1]))
        except Exception as exc:  # noqa: BLE001
            log.warning("nhs_england.ae_failed", period=rel.period, error=str(exc))

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# --------------------------------------------------------------------------- #
# RTT
# --------------------------------------------------------------------------- #
_BAND = re.compile(r"Gt (\d+)(?: To \d+)? Weeks", re.I)
#: Incomplete pathways — the waiting list, and the basis of the 18-week standard.
#:
#: Not ``Part_2A``, which is the narrower "Incomplete Pathways with DTA"
#: (decision to admit) subset and lands at ~2.4M against the ~7.2M headline.
#: Note also that for incomplete pathways the file's own ``Total`` column is
#: zero — only the weekly bands carry the counts, so they are summed instead.
RTT_INCOMPLETE = "Part_2"


def _band_weeks(column: str) -> float | None:
    """Midpoint of a waiting band in weeks; `Gt 04 To 05 Weeks` -> 4.5."""
    m = _BAND.match(column)
    return float(m.group(1)) + 0.5 if m else None


def _tidy_rtt(raw: pd.DataFrame, period: str) -> pd.DataFrame:
    bands = {c: w for c in raw.columns if (w := _band_weeks(c)) is not None}
    if not bands:
        return pd.DataFrame()

    raw = _drop_aggregate_rows(
        raw, ["Treatment Function Name", "Provider Org Code", "Provider Parent Name"]
    )
    df = raw[raw["RTT Part Type"].astype(str).str.strip() == RTT_INCOMPLETE].copy()
    if df.empty:
        return pd.DataFrame()

    counts = df[list(bands)].apply(pd.to_numeric, errors="coerce").fillna(0)
    weeks = pd.Series(bands)

    grouped = counts.groupby(
        [
            df["Provider Org Code"].astype(str).str.strip(),
            df["Provider Parent Name"].astype(str).str.strip(),
            df["Treatment Function Name"].astype(str).str.strip(),
        ]
    ).sum()

    total = grouped.sum(axis=1)
    over_18 = grouped.loc[:, weeks[weeks >= 18].index].sum(axis=1)
    over_52 = grouped.loc[:, weeks[weeks >= 52].index].sum(axis=1)

    # Median waiting time, interpolated from the band distribution — the
    # published extract gives counts per band, never a median.
    cumulative = grouped.cumsum(axis=1)
    half = total / 2
    reached = cumulative.ge(half, axis=0)
    median_weeks = reached.idxmax(axis=1).map(bands).where(total > 0)

    out = pd.DataFrame(
        {
            "period": period,
            "total_waiting": total.astype("int64"),
            "waiting_over_18_weeks": over_18.astype("int64"),
            "waiting_over_52_weeks": over_52.astype("int64"),
            "median_wait_weeks": median_weeks.astype(float).round(1),
        }
    ).reset_index()
    out.columns = [
        "org_code", "region_name", "specialty_name",
        "period", "total_waiting", "waiting_over_18_weeks",
        "waiting_over_52_weeks", "median_wait_weeks",
    ]
    out = out[out["total_waiting"] > 0].copy()
    out["within_18_weeks_pct"] = (
        (1 - out["waiting_over_18_weeks"] / out["total_waiting"]) * 100
    ).round(1)
    return out


def fetch_rtt_monthly(months: int = 1) -> pd.DataFrame:
    """Provider × specialty RTT waiting list for the most recent months.

    Only ``months=1`` by default: each extract is ~82MB uncompressed, and the
    headline figures move slowly enough that one month is the useful unit.
    """
    try:
        releases = _discover(RTT_INDEX, RTT_YEAR_SLUG, RTT_ZIP_LINK)[:months]
    except Exception as exc:  # noqa: BLE001
        log.warning("nhs_england.rtt_discovery_failed", error=str(exc))
        return pd.DataFrame()

    frames = []
    for rel in releases:
        try:
            archive = zipfile.ZipFile(io.BytesIO(_get(rel.url).content))
            member = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
            with archive.open(member) as handle:
                raw = pd.read_csv(handle, low_memory=False)
            tidy = _tidy_rtt(raw, rel.period)
            if not tidy.empty:
                frames.append(tidy)
                log.info("nhs_england.rtt_loaded", period=rel.period, rows=len(tidy))
        except Exception as exc:  # noqa: BLE001
            log.warning("nhs_england.rtt_failed", period=rel.period, error=str(exc))

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
