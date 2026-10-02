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

AE_CSV_LINK = re.compile(r'href="([^"]+?\.csv)"', re.I)
RTT_TIMESERIES_LINK = re.compile(r'href="([^"]*?RTT-Overview-Timeseries[^"]*?\.xlsx?)"', re.I)
RTT_ZIP_LINK = re.compile(r'href="([^"]*?Full-CSV-data-file[^"]*?\.zip)"', re.I)

TIMEOUT = 120
# A browser User-Agent. NHS England sits behind a WAF that serves a challenge
# page — HTTP 200, no data links — to unfamiliar clients from datacentre IP
# ranges. A polite bot string is enough to get the challenge instead of the
# page when the request comes from CI rather than a laptop.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

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


class NhsEnglandUnavailable(RuntimeError):
    """The publisher returned a bot-mitigation response instead of content."""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get(url: str) -> requests.Response:
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()

    # NHS England's WAF answers datacentre IP ranges — GitHub Actions runners
    # among them — with `202 Accepted` and an empty body. That is a success
    # status, so raise_for_status() lets it through and the caller sees a page
    # with no links, indistinguishable from a markup change. Name it instead.
    if resp.status_code == 202 or not resp.content:
        raise NhsEnglandUnavailable(
            f"blocked by bot mitigation (HTTP {resp.status_code}, "
            f"{len(resp.content)} bytes) — run the ingestion from an "
            f"un-blocked network: {url}"
        )
    return resp


def _period_from_name(name: str) -> str | None:
    """Pull YYYY-MM out of a file name or a Period cell.

    Handles the several shapes NHS England uses: ``August-2026-CSV``,
    ``MSitAE-AUGUST-2026``, ``RTT-July-2026`` and ``...-Jul26-ZIP...``.
    """
    full = re.search(r"(" + "|".join(MONTHS) + r")[-_ ]*(\d{4})", name, re.I)
    if full:
        return f"{int(full.group(2)):04d}-{MONTHS[full.group(1).upper()]:02d}"

    # "Jul26", "Nov-25", "Nov_25": three-letter month, optional separator,
    # two-digit year. The lookahead stops "Jul26" matching inside "Jul2026".
    short = re.search(r"\b([A-Z][a-z]{2})[-_ ]?(\d{2})(?!\d)", name)
    if short:
        for label, num in MONTHS.items():
            if label.startswith(short.group(1).upper()):
                return f"20{short.group(2)}-{num:02d}"
    return None


def _year_pages(index_url: str, slug: re.Pattern[str]) -> list[str]:
    """Every financial-year collection page linked from an index, newest first.

    Each year page carries that year's twelve monthly files, so walking back
    through them is how a multi-year history is assembled.
    """
    html = _get(index_url).text
    years = {m.group(1): m.group(0) for m in slug.finditer(html)}
    out = []
    for year in sorted(years, reverse=True):
        href = years[year]
        out.append(href if href.startswith("http") else f"{index_url.rstrip('/')}/{href.lstrip('/')}")
    return out


def _latest_year_page(index_url: str, slug: re.Pattern[str]) -> str | None:
    """Find the newest financial-year collection page linked from an index."""
    resp = _get(index_url)
    html = resp.text
    years = {m.group(1): m.group(0) for m in slug.finditer(html)}
    if not years:
        # A bare "not found" here is unactionable — the fetch returns 200 either
        # way. Record enough to tell a markup change from a WAF challenge.
        log.warning(
            "nhs_england.no_year_page",
            index=index_url,
            status=resp.status_code,
            content_length=len(html),
            snippet=re.sub(r"\s+", " ", html[:200]),
        )
        return None
    newest = max(years)
    href = years[newest]
    url = href if href.startswith("http") else f"{index_url.rstrip('/')}/{href.lstrip('/')}"
    log.info("nhs_england.year_page", year=newest, url=url)
    return url


def _releases_on(page_url: str, link: re.Pattern[str]) -> dict[str, Release]:
    """Monthly releases on one collection page, keyed by period.

    NHS England re-publishes months as "revised" files; when a period appears
    twice the revised one wins, regardless of page order.
    """
    html = _get(page_url).text
    seen: dict[str, Release] = {}
    for url in link.findall(html):
        period = _period_from_name(url.rsplit("/", 1)[-1])
        if not period:
            continue
        revised = "revised" in url.lower()
        if period not in seen or (revised and "revised" not in seen[period].url.lower()):
            seen[period] = Release(url=url, period=period)
    return seen


def _discover(
    index_url: str, slug: re.Pattern[str], link: re.Pattern[str], months: int = 3
) -> list[Release]:
    """Return up to ``months`` published releases, newest first.

    Walks back through financial-year pages only as far as needed, so a
    three-month refresh costs one page and a three-year history costs four.
    """
    seen: dict[str, Release] = {}
    for page in _year_pages(index_url, slug):
        seen.update({p: r for p, r in _releases_on(page, link).items() if p not in seen})
        if len(seen) >= months:
            break
    return [seen[p] for p in sorted(seen, reverse=True)][:months]


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
        releases = _discover(AE_INDEX, AE_YEAR_SLUG, AE_CSV_LINK, months)
    except NhsEnglandUnavailable as exc:
        log.warning("nhs_england.blocked", dataset="ae", error=str(exc))
        return pd.DataFrame()
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
        releases = _discover(RTT_INDEX, RTT_YEAR_SLUG, RTT_ZIP_LINK, months)
    except NhsEnglandUnavailable as exc:
        log.warning("nhs_england.blocked", dataset="rtt", error=str(exc))
        return pd.DataFrame()
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


# --------------------------------------------------------------------------- #
# RTT national time series (April 2007 onwards)
# --------------------------------------------------------------------------- #
#: Column positions in the "Full Time Series" sheet of the overview workbook.
#: The header is two rows (block name, measure), so positions are more robust
#: than names; a check on the block label guards against layout drift.
_TS_COLS = {
    "month": 2,
    "median_wait_weeks": 3,
    "within_18_weeks_pct": 8,      # with estimates for missing trusts
    "over_18_weeks": 10,           # with estimates
    "over_52_weeks": 12,           # with estimates
    "total_waiting_millions": 22,  # with estimates; a count despite the label
}


def _tidy_rtt_timeseries(raw: pd.DataFrame) -> pd.DataFrame:
    """Tidy the overview workbook (read with ``header=None``) into one row per month."""
    header_row = next(
        (i for i in range(min(30, len(raw))) if str(raw.iat[i, 2]).strip() == "Month"), None
    )
    if header_row is None:
        raise ValueError("RTT time series: 'Month' header not found in the first 30 rows")
    block = str(raw.iat[header_row, 3])
    if "Incomplete" not in block:
        raise ValueError(f"RTT time series layout changed: expected incomplete block, got {block!r}")

    body = raw.iloc[header_row + 2:]
    month = pd.to_datetime(body.iloc[:, _TS_COLS["month"]], errors="coerce")
    body = body[month.notna()]
    month = month[month.notna()]

    def num(col: str) -> pd.Series:
        return pd.to_numeric(body.iloc[:, _TS_COLS[col]], errors="coerce")

    out = pd.DataFrame({
        "period": month.dt.strftime("%Y-%m").values,
        # Labelled "(mil)" in the workbook, but the cells hold full counts
        # (7,328,252, not 7.33). Multiplying by a million gave 7.3 trillion.
        "total_waiting": num("total_waiting_millions").round().values,
        "within_18_weeks_pct": (num("within_18_weeks_pct") * 100).round(1).values,
        "over_18_weeks": num("over_18_weeks").values,
        "over_52_weeks": num("over_52_weeks").values,
        "median_wait_weeks": num("median_wait_weeks").round(1).values,
    })
    out = out.dropna(subset=["total_waiting"]).reset_index(drop=True)
    for c in ("total_waiting", "over_18_weeks", "over_52_weeks"):
        out[c] = out[c].astype("Int64")
    return out


def fetch_rtt_timeseries() -> pd.DataFrame:
    """National RTT waiting-list history, one row per month, from April 2007.

    One small workbook rather than two hundred 82MB extracts. This is the
    series the national forecaster and the monthly back-test run on.
    """
    try:
        page = _latest_year_page(RTT_INDEX, RTT_YEAR_SLUG)
        if not page:
            return pd.DataFrame()
        links = RTT_TIMESERIES_LINK.findall(_get(page).text)
        if not links:
            log.warning("nhs_england.rtt_timeseries_not_found", page=page)
            return pd.DataFrame()
        raw = pd.read_excel(io.BytesIO(_get(links[0]).content), sheet_name=0, header=None)
        out = _tidy_rtt_timeseries(raw)
        log.info("nhs_england.rtt_timeseries_loaded", months=len(out),
                 first=out["period"].iat[0], last=out["period"].iat[-1])
        return out
    except NhsEnglandUnavailable as exc:
        log.warning("nhs_england.blocked", dataset="rtt_timeseries", error=str(exc))
        return pd.DataFrame()
    except Exception as exc:  # noqa: BLE001
        log.warning("nhs_england.rtt_timeseries_failed", error=str(exc))
        return pd.DataFrame()
