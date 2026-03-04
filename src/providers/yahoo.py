"""
yahoo.py
--------
Fetches historical futures prices from Yahoo Finance using the yfinance library.

HOW CONTRACT TICKERS WORK ON YAHOO FINANCE
-------------------------------------------
Each specific futures contract has a ticker like:
    ZCN25.CBT  →  Corn (ZC) July (N) 2025, traded on CBOT (CBT)
    ZWZ25.CBT  →  Wheat (ZW) December (Z) 2025
    HEQ25.CME  →  Lean Hogs (HE) August (Q) 2025, traded on CME
    NGN25.NYM  →  Nat Gas (NG) July (N) 2025, traded on NYMEX

Month letter codes:
    F=Jan  G=Feb  H=Mar  J=Apr  K=May  M=Jun
    N=Jul  Q=Aug  U=Sep  V=Oct  X=Nov  Z=Dec

IMPORTANT LIMITATION
---------------------
Yahoo Finance does not guarantee coverage of all historical contracts.
If a ticker returns empty data it will be reported on the Data Status page.
For contracts where Yahoo data is missing, you can place a CSV file in
data/manual/ with the filename  {TICKER}.csv  and two columns: Date, Close.
The app will automatically prefer manual files over Yahoo fetches.
"""

import yfinance as yf
import pandas as pd
import os
import streamlit as st
from datetime import date

# Path to the manual overrides folder
_PROJECT_ROOT  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MANUAL_DIR    = os.path.join(_PROJECT_ROOT, "data", "manual")


# ── Ticker construction ──────────────────────────────────────────────────────

def build_ticker(yahoo_symbol: str, month_code: str, year: int, exchange: str) -> str:
    """
    Build a Yahoo Finance futures contract ticker string.

    Example:
        build_ticker("ZC", "N", 2025, "CBT")  →  "ZCN25.CBT"

    Parameters
    ----------
    yahoo_symbol : e.g. "ZC" for Corn
    month_code   : single letter, e.g. "N" for July
    year         : 4-digit year, e.g. 2025
    exchange     : Yahoo exchange suffix, e.g. "CBT"
    """
    year_2digit = str(year)[-2:]
    return f"{yahoo_symbol}{month_code}{year_2digit}.{exchange}"


# ── Price fetching ───────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_contract_prices(ticker: str) -> tuple:
    """
    Fetch daily closing prices for a futures contract.

    Strategy:
      1. Check data/manual/{ticker}.csv for a manual override file.
      2. If not found, try Yahoo Finance with the full ticker (e.g. ZCN25.CBT).
      3. If Yahoo returns nothing, try the ticker without the exchange suffix.

    Returns
    -------
    (prices, status_message)
      prices         : pd.Series with DatetimeIndex, or None if failed
      status_message : human-readable string for the Data Status page
    """

    # --- Step 1: Check for a manual CSV override ----------------------------
    manual_path = os.path.join(_MANUAL_DIR, f"{ticker}.csv")
    if os.path.exists(manual_path):
        try:
            df = pd.read_csv(manual_path, parse_dates=["Date"], index_col="Date")
            prices = df["Close"].dropna()
            prices.name = ticker
            return prices, f"MANUAL FILE: {len(prices)} days ({prices.index[0].date()} → {prices.index[-1].date()})"
        except Exception as e:
            return None, f"Manual file error for {ticker}: {e}"

    # --- Step 2: Try Yahoo Finance with the full exchange-suffixed ticker ---
    prices, msg = _yahoo_fetch(ticker)
    if prices is not None:
        return prices, msg

    # --- Step 3: Fallback — try without the exchange suffix -----------------
    base_ticker = ticker.split(".")[0]
    prices, msg = _yahoo_fetch(base_ticker)
    if prices is not None:
        return prices, f"(via {base_ticker}) {msg}"

    return None, f"No data found for {ticker}. Try placing {ticker}.csv in data/manual/."


def _yahoo_fetch(ticker: str) -> tuple:
    """
    Internal helper: download prices from Yahoo Finance for a single ticker.
    Returns (pd.Series, message) or (None, error_message).
    """
    try:
        t = yf.Ticker(ticker)
        df = t.history(start="2018-01-01", end=date.today().strftime("%Y-%m-%d"), auto_adjust=True)

        if df is None or df.empty:
            return None, f"Yahoo returned no data for {ticker}"

        if "Close" not in df.columns:
            return None, f"No 'Close' column in Yahoo data for {ticker}"

        prices = df["Close"].dropna()
        if prices.empty:
            return None, f"All Close values are NaN for {ticker}"

        prices.name = ticker
        return prices, f"YAHOO OK: {len(prices)} days ({prices.index[0].date()} → {prices.index[-1].date()})"

    except Exception as e:
        return None, f"Yahoo error for {ticker}: {e}"


# ── Spread computation ───────────────────────────────────────────────────────

def fetch_spread_for_season(season_year: int, commodity_info: dict, spread_def: dict) -> tuple:
    """
    Fetch both contract legs and compute the spread (leg1 price − leg2 price)
    for a single season year.

    Parameters
    ----------
    season_year    : int  — e.g. 2025
    commodity_info : dict — from spreads.yaml (yahoo_symbol, exchange, unit)
    spread_def     : dict — from spreads.yaml (legs with month and year_offset)

    Returns
    -------
    (spread_series, status_dict)
      spread_series : pd.Series with DatetimeIndex (leg1 − leg2), or None
      status_dict   : details for the Data Status page
    """
    symbol   = commodity_info["yahoo_symbol"]
    exchange = commodity_info["exchange"]
    legs     = spread_def["legs"]

    status = {
        "season_year": season_year,
        "leg1_ticker": None,
        "leg2_ticker": None,
        "leg1_status": None,
        "leg2_status": None,
        "spread_status": None,
    }

    # Build tickers for each leg
    leg1_year   = season_year + legs[0].get("year_offset", 0)
    leg2_year   = season_year + legs[1].get("year_offset", 0)
    leg1_ticker = build_ticker(symbol, legs[0]["month"], leg1_year, exchange)
    leg2_ticker = build_ticker(symbol, legs[1]["month"], leg2_year, exchange)

    status["leg1_ticker"] = leg1_ticker
    status["leg2_ticker"] = leg2_ticker

    # Fetch each leg
    leg1_prices, status["leg1_status"] = fetch_contract_prices(leg1_ticker)
    leg2_prices, status["leg2_status"] = fetch_contract_prices(leg2_ticker)

    if leg1_prices is None or leg2_prices is None:
        status["spread_status"] = "FAILED — one or both legs missing"
        return None, status

    # Align on shared trading days, then compute spread
    combined = pd.DataFrame({"leg1": leg1_prices, "leg2": leg2_prices}).dropna()

    if combined.empty:
        status["spread_status"] = "FAILED — no overlapping dates between legs"
        return None, status

    spread_series = combined["leg1"] - combined["leg2"]
    spread_series.name = season_year
    status["spread_status"] = f"OK — {len(spread_series)} data points"

    return spread_series, status
