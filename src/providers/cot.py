"""
cot.py
------
Fetches and processes CFTC Disaggregated Commitments of Traders (COT) data.

Unlike ProphetX/Bloomberg providers which require manual Excel exports,
COT data is fetched automatically from the CFTC's public website — no
manual steps required.

RELEASE SCHEDULE
-----------------
Data is released every Friday at 3:30 PM ET, reflecting positions as of
the prior Tuesday. The "as of" date is surfaced in the UI so traders
always know the data vintage.

CFTC URL PATTERN
-----------------
    https://www.cftc.gov/files/dea/history/fut_disagg_txt_{YEAR}.zip

Each zip contains one CSV with all disaggregated futures-only data
for that calendar year.

CACHING STRATEGY
-----------------
Historical years (< current year): 30-day TTL — data never changes.
Current year: 6-hour TTL — refreshes well ahead of each Friday release.

VERIFYING CFTC COMMODITY NAMES
--------------------------------
If a commodity shows no data on the dashboard, the CFTC name string in
COT_COMMODITIES may not match exactly. To verify:
    1. Download a year zip from the URL above manually.
    2. Open the CSV and inspect the 'Market_and_Exchange_Names' column.
    3. Copy the exact string (including spaces and punctuation) into
       the 'cftc_name' field below.
"""

import io
import zipfile

import numpy as np
import pandas as pd
import requests
import streamlit as st
from datetime import date


# ── Commodity registry ────────────────────────────────────────────────────────
# 'cftc_name'        : must match Market_and_Exchange_Names in the CFTC file exactly.
# 'yahoo_continuous' : Yahoo Finance continuous contract ticker for price overlay.
# 'category'         : used for the sidebar category filter.

COT_COMMODITIES = {
    "Corn": {
        "cftc_name":        "CORN - CHICAGO BOARD OF TRADE",
        "display":          "Corn",
        "unit":             "cents/bu",
        "yahoo_continuous": "ZC=F",
        "category":         "Grains",
    },
    "Chicago Wheat": {
        "cftc_name":        "WHEAT - CHICAGO BOARD OF TRADE",
        "display":          "Chicago Wheat",
        "unit":             "cents/bu",
        "yahoo_continuous": "ZW=F",
        "category":         "Grains",
    },
    "KC Wheat": {
        # NOTE: After KCBT merged into CME Group, KC Wheat may appear
        # under "WHEAT-HRW - CHICAGO BOARD OF TRADE". Verify in raw file.
        "cftc_name":        "WHEAT-HRW - CHICAGO BOARD OF TRADE",
        "display":          "KC Wheat",
        "unit":             "cents/bu",
        "yahoo_continuous": "KE=F",
        "category":         "Grains",
    },
    "Soybean Meal": {
        "cftc_name":        "SOYBEAN MEAL - CHICAGO BOARD OF TRADE",
        "display":          "Soybean Meal",
        "unit":             "$/ton",
        "yahoo_continuous": "ZM=F",
        "category":         "Grains",
    },
    "Soybean Oil": {
        "cftc_name":        "SOYBEAN OIL - CHICAGO BOARD OF TRADE",
        "display":          "Soybean Oil",
        "unit":             "cents/lb",
        "yahoo_continuous": "ZL=F",
        "category":         "Grains",
    },
    "WTI Crude": {
        "cftc_name":        "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
        "display":          "WTI Crude",
        "unit":             "$/bbl",
        "yahoo_continuous": "CL=F",
        "category":         "Energy",
    },
    "Natural Gas": {
        "cftc_name":        "NATURAL GAS - NEW YORK MERCANTILE EXCHANGE",
        "display":          "Natural Gas",
        "unit":             "$/MMBtu",
        "yahoo_continuous": "NG=F",
        "category":         "Energy",
    },
    "Live Cattle": {
        "cftc_name":        "LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE",
        "display":          "Live Cattle",
        "unit":             "cents/lb",
        "yahoo_continuous": "LE=F",
        "category":         "Livestock",
    },
    "Feeder Cattle": {
        "cftc_name":        "FEEDER CATTLE - CHICAGO MERCANTILE EXCHANGE",
        "display":          "Feeder Cattle",
        "unit":             "cents/lb",
        "yahoo_continuous": "GF=F",
        "category":         "Livestock",
    },
    "Lean Hogs": {
        "cftc_name":        "LEAN HOGS - CHICAGO MERCANTILE EXCHANGE",
        "display":          "Lean Hogs",
        "unit":             "cents/lb",
        "yahoo_continuous": "HE=F",
        "category":         "Livestock",
    },
}

# ── CFTC column name constants ────────────────────────────────────────────────
_DATE_COL  = "Report_Date_as_YYYY-MM-DD"
_NAME_COL  = "Market_and_Exchange_Names"
_OI_COL    = "Open_Interest_All"

_MM_LONG   = "M_Money_Positions_Long_All"
_MM_SHORT  = "M_Money_Positions_Short_All"
_MM_SPREAD = "M_Money_Positions_Spreading_All"

_PROD_LONG  = "Prod_Merc_Positions_Long_All"
_PROD_SHORT = "Prod_Merc_Positions_Short_All"

# Note: CFTC has a known typo — double underscore on Swap short column.
# We try both names during load.
_MM_TRADERS_LONG   = "Traders_M_Money_Long_All"
_MM_TRADERS_SHORT  = "Traders_M_Money_Short_All"
_MM_TRADERS_SPREAD = "Traders_M_Money_Spread_All"

_SWAP_LONG       = "Swap_Positions_Long_All"
_SWAP_SHORT_v1   = "Swap__Positions_Short_All"   # double underscore (most common)
_SWAP_SHORT_v2   = "Swap_Positions_Short_All"    # single underscore (fallback)

_CFTC_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"


# ── Download helpers ──────────────────────────────────────────────────────────

def _download_year(year: int) -> pd.DataFrame:
    """Download one calendar year's disaggregated COT zip from the CFTC."""
    url  = _CFTC_URL.format(year=year)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith((".txt", ".csv"))]
        if not csv_names:
            raise ValueError(f"No CSV/TXT found in COT zip for {year}")
        with z.open(csv_names[0]) as f:
            return pd.read_csv(f, low_memory=False)


@st.cache_data(ttl=3600 * 24 * 30, show_spinner=False)   # historical: 30-day cache
def _fetch_historical_year(year: int) -> pd.DataFrame:
    return _download_year(year)


@st.cache_data(ttl=3600 * 6, show_spinner=False)           # current year: 6-hour cache
def _fetch_current_year(year: int) -> pd.DataFrame:
    return _download_year(year)


# ── Main data loader ──────────────────────────────────────────────────────────

@st.cache_data(ttl=3600 * 6, show_spinner=False)
def fetch_cot_data(lookback_years: int = 5) -> tuple:
    """
    Download, concatenate, and process CFTC disaggregated COT data.

    Parameters
    ----------
    lookback_years : number of prior calendar years to include (default 5)

    Returns
    -------
    (df, status_message)
        df             : processed DataFrame filtered to COT_COMMODITIES,
                         with derived columns (MM_Net, Prod_Net, WoW, etc.)
                         Empty DataFrame on complete failure.
        status_message : human-readable string for the troubleshoot expander.
    """
    current_year   = date.today().year
    years_to_fetch = list(range(current_year - lookback_years, current_year + 1))

    frames, errors = [], []

    for yr in years_to_fetch:
        try:
            raw = _fetch_historical_year(yr) if yr < current_year else _fetch_current_year(yr)
            frames.append(raw)
        except Exception as e:
            errors.append(f"{yr}: {e}")

    if not frames:
        return pd.DataFrame(), f"Failed to download any COT data. Errors: {'; '.join(errors)}"

    full = pd.concat(frames, ignore_index=True)

    # ── Resolve the Swap short column name (handle CFTC typo) ────────────────
    swap_short_col = _SWAP_SHORT_v1 if _SWAP_SHORT_v1 in full.columns else _SWAP_SHORT_v2

    keep = [
        _DATE_COL, _NAME_COL, _OI_COL,
        _MM_LONG, _MM_SHORT, _MM_SPREAD,
        _PROD_LONG, _PROD_SHORT,
        _SWAP_LONG, swap_short_col,
        _MM_TRADERS_LONG, _MM_TRADERS_SHORT, _MM_TRADERS_SPREAD,
    ]
    keep = [c for c in keep if c in full.columns]   # drop any truly absent cols
    full = full[keep].copy()

    # ── Parse and sort dates ──────────────────────────────────────────────────
    full[_DATE_COL] = pd.to_datetime(full[_DATE_COL], errors="coerce")
    full = full.dropna(subset=[_DATE_COL]).sort_values(_DATE_COL)

    # ── Filter to our commodity universe ──────────────────────────────────────
    target_names = {v["cftc_name"] for v in COT_COMMODITIES.values()}
    full = full[full[_NAME_COL].isin(target_names)].copy()

    if full.empty:
        return pd.DataFrame(), (
            "COT data downloaded but no matching commodities found. "
            "Verify 'cftc_name' strings in COT_COMMODITIES against the raw file."
        )

    # ── Cast numeric columns ──────────────────────────────────────────────────
    num_cols = [c for c in keep if c not in (_DATE_COL, _NAME_COL)]
    for col in num_cols:
        full[col] = pd.to_numeric(full[col], errors="coerce")

    # ── Derived columns ───────────────────────────────────────────────────────
    full["MM_Net"]            = full[_MM_LONG]   - full[_MM_SHORT]
    full["Prod_Net"]          = full[_PROD_LONG] - full[_PROD_SHORT]
    full["MM_Pct_OI"]         = (full["MM_Net"]   / full[_OI_COL] * 100).round(1)
    full["Prod_Pct_OI"]       = (full["Prod_Net"] / full[_OI_COL] * 100).round(1)
    # Trader counts — long + short is the standard way to express total participation.
    # Spreading traders are already captured in one of the two sides.
    full["Traders_MM_Long"]   = full[_MM_TRADERS_LONG]
    full["Traders_MM_Short"]  = full[_MM_TRADERS_SHORT]
    full["Traders_MM_Total"]  = full[_MM_TRADERS_LONG].fillna(0) + full[_MM_TRADERS_SHORT].fillna(0)

    # Add commodity key (reverse lookup from CFTC name)
    name_to_key = {v["cftc_name"]: k for k, v in COT_COMMODITIES.items()}
    full["commodity_key"] = full[_NAME_COL].map(name_to_key)

    # Week-over-week change in MM net — computed within each commodity group
    full = full.sort_values([_NAME_COL, _DATE_COL])
    full["MM_Net_WoW"] = full.groupby(_NAME_COL)["MM_Net"].diff()

    # Store the resolved swap short column name for callers that need it
    full.attrs["swap_short_col"] = swap_short_col

    status = f"COT data: {full[_DATE_COL].min().date()} → {full[_DATE_COL].max().date()}"
    if errors:
        status += f"  |  Warnings: {'; '.join(errors)}"

    return full, status


# ── Analysis helpers ──────────────────────────────────────────────────────────

def compute_percentile_rank(series: pd.Series, window_years: int = 3) -> pd.Series:
    """
    Rolling percentile rank for a weekly COT series.

    For each observation, returns what percentile that value sits at
    relative to all observations in the prior N years.

    Parameters
    ----------
    series       : weekly pd.Series (DatetimeIndex)
    window_years : lookback window for percentile calculation (default 3)

    Returns
    -------
    pd.Series of percentile ranks (0–100), same index as input.
    """
    window_weeks = window_years * 52
    ranks        = pd.Series(index=series.index, dtype=float)

    for i in range(len(series)):
        start_i  = max(0, i - window_weeks)
        window   = series.iloc[start_i : i + 1].dropna()
        if len(window) < 4:
            continue
        ranks.iloc[i] = round((window < series.iloc[i]).sum() / len(window) * 100)

    return ranks


def get_commodity_timeseries(
    df:              pd.DataFrame,
    commodity_key:   str,
    pct_window_yrs:  int = 3,
) -> pd.DataFrame:
    """
    Return the full weekly time series for one commodity.

    Columns: MM_Net, MM_Long, MM_Short, MM_Spread, MM_Pct_OI, MM_Net_WoW,
             Prod_Net, Prod_Long, Prod_Short, Prod_Pct_OI,
             Open_Interest, MM_Percentile
    """
    sub = df[df["commodity_key"] == commodity_key].copy()
    if sub.empty:
        return pd.DataFrame()

    sub = sub.set_index(_DATE_COL).sort_index()

    out = pd.DataFrame(index=sub.index)
    out["MM_Long"]       = sub.get(_MM_LONG)
    out["MM_Short"]      = sub.get(_MM_SHORT)
    out["MM_Spread"]     = sub.get(_MM_SPREAD)
    out["MM_Net"]           = sub.get("MM_Net")
    out["MM_Pct_OI"]        = sub.get("MM_Pct_OI")
    out["MM_Net_WoW"]       = sub.get("MM_Net_WoW")
    out["Prod_Long"]        = sub.get(_PROD_LONG)
    out["Prod_Short"]       = sub.get(_PROD_SHORT)
    out["Prod_Net"]         = sub.get("Prod_Net")
    out["Prod_Pct_OI"]      = sub.get("Prod_Pct_OI")
    out["Open_Interest"]    = sub.get(_OI_COL)
    out["Traders_MM_Long"]  = sub.get("Traders_MM_Long")
    out["Traders_MM_Short"] = sub.get("Traders_MM_Short")
    out["Traders_MM_Total"] = sub.get("Traders_MM_Total")

    if "MM_Net" in out.columns and not out["MM_Net"].dropna().empty:
        out["MM_Percentile"] = compute_percentile_rank(out["MM_Net"], pct_window_yrs)

    return out.dropna(how="all")


def get_snapshot(df: pd.DataFrame, pct_window_yrs: int = 3) -> pd.DataFrame:
    """
    Build the cross-commodity snapshot table (most recent week per commodity).

    Returns a DataFrame with one row per commodity:
        Commodity, Category, As_Of, MM_Net, MM_Long, MM_Short,
        MM_Net_WoW, MM_Pct_OI, MM_Percentile, Prod_Net, Open_Interest
    """
    rows = []
    for key, meta in COT_COMMODITIES.items():
        ts = get_commodity_timeseries(df, key, pct_window_yrs)
        if ts.empty:
            continue

        def _int(col):
            v = ts[col].iloc[-1] if col in ts.columns else np.nan
            return int(v) if pd.notna(v) else None

        def _flt(col, decimals=1):
            v = ts[col].iloc[-1] if col in ts.columns else np.nan
            return round(float(v), decimals) if pd.notna(v) else None

        rows.append({
            "Commodity":     meta["display"],
            "Category":      meta["category"],
            "As_Of":         ts.index[-1].date(),
            "MM_Net":        _int("MM_Net"),
            "MM_Long":       _int("MM_Long"),
            "MM_Short":      _int("MM_Short"),
            "MM_Net_WoW":    _int("MM_Net_WoW"),
            "MM_Pct_OI":     _flt("MM_Pct_OI"),
            "MM_Percentile": _int("MM_Percentile"),
            "Prod_Net":      _int("Prod_Net"),
            "Open_Interest": _int("Open_Interest"),
        })

    return pd.DataFrame(rows)


# ── Price overlay helper ──────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_continuous_price(yahoo_ticker: str, start: str = "2018-01-01") -> tuple:
    """
    Fetch a continuous front-month price series from Yahoo Finance.

    Used for the price overlay on the Deep Dive dual-axis chart.

    Returns (pd.Series, status_message).
    """
    try:
        import yfinance as yf
        from datetime import date as _date
        t   = yf.Ticker(yahoo_ticker)
        df  = t.history(start=start, end=_date.today().strftime("%Y-%m-%d"), auto_adjust=True)
        if df.empty or "Close" not in df.columns:
            return pd.Series(dtype=float), f"No data from Yahoo for {yahoo_ticker}"
        prices = df["Close"].dropna()
        prices.index = prices.index.tz_localize(None)   # strip timezone for alignment
        return prices, f"OK — {len(prices)} days ({prices.index[0].date()} → {prices.index[-1].date()})"
    except Exception as e:
        return pd.Series(dtype=float), f"Yahoo error for {yahoo_ticker}: {e}"