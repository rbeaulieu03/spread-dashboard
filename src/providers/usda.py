"""
usda.py
-------
Fetches weekly fed cattle cash trade data from the USDA AMS Datamart API.

BASE URL
---------
    https://mpr.datamart.ams.usda.gov/services/v1.1/reports/{slug}/Summary?allSections=true

No authentication required. Publicly accessible.

REPORTS USED
-------------
    Slug 2477  LM_CT150  5 Area Weekly Weighted Average Direct Slaughter Cattle
    Slug 2484  LM_CT157  Kansas Weekly Direct Slaughter Cattle
    Slug 2485  LM_CT158  Nebraska Weekly Direct Slaughter Cattle

FIELD NAMES (confirmed from live Datamart response 2026-03-19)
---------------------------------------------------------------
Detail section rows contain:
    report_date               — "MM/DD/YYYY"
    class_description         — "STEER" | "HEIFER" | "MIXED STEER/HEIFER" | "ALL BEEF TYPE"
    selling_basis_description — "LIVE FOB" | "LIVE DELIVERED" | "DRESSED DELIVERED" | "DRESSED FOB"
    grade_description         — "Total all grades" | "Over 80% Choice" | etc.
    weighted_avg_price        — "234.83" (string, no commas)
    head_count                — "11,004" (string, with commas)

FILTER APPLIED
---------------
    class_description  == "ALL BEEF TYPE"
    grade_description  contains "Total all grades"

This yields one row per selling_basis per week per report.
All three selling bases are returned as separate columns.
"""

import requests
import pandas as pd
import streamlit as st
from datetime import date, timedelta


# ── Report registry ───────────────────────────────────────────────────────────

CASH_REPORTS = {
    "5area":    {"slug": 2477, "label": "5 Area",   "color": "#FFFFFF"},
    "kansas":   {"slug": 2484, "label": "Kansas",   "color": "#FF8C00"},
    "nebraska": {"slug": 2485, "label": "Nebraska", "color": "#4CAF7D"},
}

_BASE_URL = "https://mpr.datamart.ams.usda.gov/services/v1.1"

# Selling basis keys (uppercase, as returned by the API)
_BASIS_LIVE_FOB       = "LIVE FOB"
_BASIS_LIVE_DELIVERED = "LIVE DELIVERED"
_BASIS_DRESSED        = "DRESSED DELIVERED"


# ── Core fetch ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_cash_report(slug: int, lookback_years: int = 3) -> tuple:
    """
    Fetch weekly cash cattle price data for one report slug from the Datamart.

    Parameters
    ----------
    slug           : Datamart report slug integer
    lookback_years : years of history to pull

    Returns
    -------
    (df, status_message)
        df : pd.DataFrame indexed by report_date (Timestamp) with columns:
               price_live_fob, price_live_delivered, price_dressed
               head_live_fob,  head_live_delivered,  head_dressed
             Empty DataFrame on failure.
        status_message : human-readable diagnostic string
    """
    # lastReports=N returns the N most recent report dates.
    # 52 weeks/year * lookback_years gives us full history coverage.
    n_reports = max(52 * lookback_years, 52)
    url    = f"{_BASE_URL}/reports/{slug}/Summary"
    params = {
        "allSections": "true",
        "lastReports": str(n_reports),
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
    except requests.exceptions.ConnectionError as exc:
        return pd.DataFrame(), f"Network error fetching slug {slug}: {exc}"
    except Exception as exc:
        return pd.DataFrame(), f"Unexpected error fetching slug {slug}: {exc}"

    if resp.status_code == 404:
        return pd.DataFrame(), (
            f"Datamart 404 for slug {slug}. "
            "Report may not exist or date range returned no data."
        )
    if resp.status_code != 200:
        return pd.DataFrame(), (
            f"Datamart HTTP {resp.status_code} for slug {slug}: {resp.text[:300]}"
        )

    try:
        raw = resp.json()
    except Exception as exc:
        return pd.DataFrame(), f"Slug {slug}: JSON parse error - {exc}. Raw: {resp.text[:300]}"

    # API sometimes returns a plain JSON string (error message)
    if isinstance(raw, str):
        return pd.DataFrame(), f"Slug {slug}: API returned string: {raw[:400]}"

    # ── Locate the Detail section records ────────────────────────────────────
    records = _extract_records(raw, section_name="Detail")
    if not records:
        # Build a diagnostic showing what we actually got back
        if isinstance(raw, list):
            sections_found = [
                f"{s.get('reportSection','?')} ({len(s.get('results',[]))} rows)"
                for s in raw if isinstance(s, dict)
            ]
            diag = f"Sections returned: {sections_found}"
        elif isinstance(raw, dict):
            diag = f"Dict keys: {list(raw.keys())}"
        else:
            diag = f"Unexpected type: {type(raw)}"
        return pd.DataFrame(), f"Slug {slug}: no Detail records. {diag}"

    return _parse_detail_records(records, slug, lookback_years)


def _extract_records(raw, section_name: str) -> list:
    """
    Pull results from the named reportSection in the Datamart response.
    Falls back to any non-empty results if the named section isn't found.
    """
    if isinstance(raw, list):
        # Try named section first
        for section in raw:
            if isinstance(section, dict) and section.get("reportSection") == section_name:
                return section.get("results", [])
        # Fallback: first non-empty results
        for section in raw:
            if isinstance(section, dict):
                r = section.get("results", [])
                if r:
                    return r
    elif isinstance(raw, dict):
        return raw.get("results", [])
    return []


def _parse_detail_records(records: list, slug: int, lookback_years: int = 3) -> tuple:
    """
    Convert raw Detail records into a clean weekly price DataFrame.

    Keeps only ALL BEEF TYPE / Total all grades rows, then pivots
    by selling_basis into separate price and head-count columns.
    """
    df = pd.DataFrame(records)
    df.columns = [c.lower().strip() for c in df.columns]

    required = {
        "report_date", "class_description", "grade_description",
        "selling_basis_description", "weighted_avg_price", "head_count",
    }
    missing = required - set(df.columns)
    if missing:
        return pd.DataFrame(), (
            f"Slug {slug}: missing columns {missing}. "
            f"Found: {sorted(df.columns)}"
        )

    # Filter to summary rows.
    # 5 Area report uses "ALL BEEF TYPE"; regional reports (KS, NE) use
    # "ALL STEERS & HEIFERS". Accept either.
    all_class_values = df["class_description"].str.strip().str.upper()
    mask_class = all_class_values.isin(["ALL BEEF TYPE", "ALL STEERS & HEIFERS"])
    mask_grade = df["grade_description"].str.strip().str.lower().str.contains(
        "total all grades", na=False
    )
    df = df[mask_class & mask_grade].copy()

    if df.empty:
        return pd.DataFrame(), (
            f"Slug {slug}: no rows match summary filter. "
            f"class_description values seen: "
            f"{pd.DataFrame(records)['class_description'].unique().tolist()}"
        )

    # Parse date
    df["report_date"] = pd.to_datetime(
        df["report_date"], format="%m/%d/%Y", errors="coerce"
    )
    df = df.dropna(subset=["report_date"])

    # Apply lookback cutoff (API returns all history; we filter here)
    import datetime
    cutoff = pd.Timestamp(datetime.date.today()) - pd.DateOffset(years=lookback_years)
    df = df[df["report_date"] >= cutoff]

    if df.empty:
        return pd.DataFrame(), f"Slug {slug}: no records within last {lookback_years} years"

    # Parse numerics (values arrive as strings, possibly with commas)
    def _to_float(series):
        return (
            series.astype(str)
            .str.replace(",", "", regex=False)
            .pipe(pd.to_numeric, errors="coerce")
        )

    df["weighted_avg_price"] = _to_float(df["weighted_avg_price"])
    df["head_count"] = (
        _to_float(df["head_count"]).fillna(0).astype(int)
    )

    df["basis"] = df["selling_basis_description"].str.strip().str.upper()

    # Pivot each selling basis into its own columns
    basis_map = {
        _BASIS_LIVE_FOB:       ("price_live_fob",        "head_live_fob"),
        _BASIS_LIVE_DELIVERED: ("price_live_delivered",   "head_live_delivered"),
        _BASIS_DRESSED:        ("price_dressed",           "head_dressed"),
    }

    frames = []
    for basis, (price_col, head_col) in basis_map.items():
        sub = (
            df[df["basis"] == basis][["report_date", "weighted_avg_price", "head_count"]]
            .copy()
            .rename(columns={
                "weighted_avg_price": price_col,
                "head_count":         head_col,
            })
            .dropna(subset=[price_col])
            .sort_values("report_date")
            .drop_duplicates(subset="report_date", keep="last")
            .set_index("report_date")
        )
        if not sub.empty:
            frames.append(sub)

    if not frames:
        return pd.DataFrame(), f"Slug {slug}: no valid price rows after pivoting"

    result = pd.concat(frames, axis=1).sort_index()

    n      = len(result)
    oldest = result.index[0].strftime("%Y-%m-%d")
    latest = result.index[-1].strftime("%Y-%m-%d")

    return result, f"OK — slug {slug}: {n} weeks ({oldest} → {latest})"


# ── Multi-report loader ───────────────────────────────────────────────────────

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_all_cash_prices(lookback_years: int = 3) -> tuple:
    """
    Fetch all three regional cash price series and merge into one DataFrame.

    Returns
    -------
    (df, status_dict)
        df : pd.DataFrame indexed by report_date with columns:
               price_live_fob_5area / _kansas / _nebraska
               price_live_delivered_* , price_dressed_*
               head_live_fob_*,  head_live_delivered_*,  head_dressed_*
               spread_ne_ks_live_fob  — Nebraska minus Kansas, LIVE FOB
             Empty DataFrame if all three fail.
        status_dict : {region_key: status_message}
    """
    status_dict = {}
    frames      = {}

    for key, info in CASH_REPORTS.items():
        df, msg = fetch_cash_report(info["slug"], lookback_years)
        status_dict[key] = msg
        if not df.empty:
            df.columns = [f"{col}_{key}" for col in df.columns]
            frames[key] = df

    if not frames:
        return pd.DataFrame(), status_dict

    merged = pd.concat(frames.values(), axis=1, join="outer").sort_index()

    # Nebraska − Kansas LIVE FOB spread
    ne = "price_live_fob_nebraska"
    ks = "price_live_fob_kansas"
    if ne in merged.columns and ks in merged.columns:
        merged["spread_ne_ks_live_fob"] = merged[ne] - merged[ks]

    return merged, status_dict


# ── ProphetX Friday close helper ─────────────────────────────────────────────

def get_friday_closes(price_series: pd.Series) -> pd.Series:
    """
    Filter a daily ProphetX price series to Friday closes only (weekday == 4).
    """
    if price_series is None or price_series.empty:
        return pd.Series(dtype=float)
    return price_series[price_series.index.dayofweek == 4].copy()