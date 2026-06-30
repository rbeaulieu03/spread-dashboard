"""
parquet_cache.py
----------------
Persistent per-contract price cache stored as Parquet files.

HOW IT WORKS
------------
Each futures contract gets its own file under data/cache/:
    data/cache/@CN25.parquet   →  Corn July 2025
    data/cache/@LEZ25.parquet  →  Live Cattle December 2025

On every call to get_contract_prices():
  1. Load existing Parquet (all historical rows — originally seeded from Excel)
  2. Merge in any Excel series passed in (fills gaps in the historical record)
  3. If the last row is stale (older than yesterday) AND the contract is still
     within its active trading window, fetch the missing days from yfinance
     and append them
  4. Save the merged result back to Parquet
  5. Return the full Series

After the one-time migration (scripts/migrate_to_parquet.py), Excel files are
never needed again. yfinance keeps the cache current automatically.

SYMBOL MAPPING
--------------
ProphetX uses a different prefix convention from Yahoo Finance:

  ProphetX  │ Yahoo root │ Exchange
  ──────────┼────────────┼─────────
  @C        │ ZC         │ CBT      (Corn)
  @W        │ ZW         │ CBT      (Wheat)
  @SM       │ ZM         │ CBT      (Soy Meal)
  @BO       │ ZL         │ CBT      (Soy Oil)
  @LE       │ LE         │ CME      (Live Cattle)
  @HE       │ HE         │ CME      (Lean Hogs)
  QNG       │ NG         │ NYM      (Natural Gas)
  @KW       │ KE         │ CBT      (KC Wheat)
  @GF       │ GF         │ CME      (Feeder Cattle)

Index / cash symbols (IHX.X, ICX.X) have no Yahoo equivalent and are skipped
for the yfinance top-up step — those come only from Excel/manual files.
"""

import os
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
import streamlit as st

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CACHE_DIR    = os.path.join(_PROJECT_ROOT, "data", "cache")

# ── Symbol mapping ─────────────────────────────────────────────────────────────
# Each entry: ProphetX prefix → (Yahoo root symbol, Yahoo exchange suffix)
# Order matters: longer prefixes must come before shorter ones (e.g. @SM before @S)
_PREFIX_MAP = [
    ("@SM", "ZM",  "CBT"),   # Soy Meal
    ("@BO", "ZL",  "CBT"),   # Soy Oil
    ("@KW", "KE",  "CBT"),   # KC Wheat
    ("@GF", "GF",  "CME"),   # Feeder Cattle
    ("@LE", "LE",  "CME"),   # Live Cattle
    ("@HE", "HE",  "CME"),   # Lean Hogs
    ("@C",  "ZC",  "CBT"),   # Corn
    ("@W",  "ZW",  "CBT"),   # Wheat
    ("QNG", "NG",  "NYM"),   # Natural Gas (no @ prefix in ProphetX)
]

# Symbols containing these strings have no Yahoo equivalent — skip yfinance
_NO_YAHOO_PATTERNS = ("IHX", "ICX", ".X")


def prophetx_to_yahoo_ticker(prophetx_symbol: str) -> str | None:
    """
    Convert a ProphetX symbol to its Yahoo Finance equivalent.

    Examples
    --------
    "@CN25"   → "ZCN25.CBT"
    "@LEZ25"  → "LEZ25.CME"
    "@SMN25"  → "ZMN25.CBT"
    "QNGN25"  → "NGN25.NYM"
    "IHX.X"   → None  (cash index, no Yahoo ticker)
    """
    # Skip cash/index symbols
    if any(pat in prophetx_symbol for pat in _NO_YAHOO_PATTERNS):
        return None

    for px_prefix, yahoo_root, exchange in _PREFIX_MAP:
        if prophetx_symbol.startswith(px_prefix):
            remainder = prophetx_symbol[len(px_prefix):]   # e.g. "N25"
            return f"{yahoo_root}{remainder}.{exchange}"

    return None  # no mapping found


# ── Cache I/O ─────────────────────────────────────────────────────────────────

def _cache_path(symbol: str) -> str:
    # Sanitise the symbol so it's safe as a filename (replace / etc.)
    safe = symbol.replace("/", "_").replace("\\", "_")
    return os.path.join(_CACHE_DIR, f"{safe}.parquet")


def load_from_cache(symbol: str) -> pd.Series | None:
    """Return cached price Series, or None if no cache file exists."""
    path = _cache_path(symbol)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        s  = df["close"].rename(symbol)
        s.index = pd.DatetimeIndex(s.index)
        return s.sort_index()
    except Exception:
        return None


def save_to_cache(symbol: str, series: pd.Series) -> None:
    """Persist a price Series to Parquet, creating the directory if needed."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    df = pd.DataFrame({"close": series.values}, index=series.index)
    df.index.name = "date"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_parquet(_cache_path(symbol))


# ── yfinance top-up ───────────────────────────────────────────────────────────

def _yfinance_fetch(yahoo_ticker: str, start: date) -> pd.Series | None:
    """
    Fetch closing prices from yfinance starting at `start`.

    Tries the full ticker first (e.g. ZCN25.CBT), then falls back to the
    bare root (e.g. ZCN25) in case the exchange suffix isn't recognised.

    Returns a DatetimeIndex Series or None on failure.
    """
    tickers_to_try = [yahoo_ticker, yahoo_ticker.split(".")[0]]

    for ticker in tickers_to_try:
        try:
            t  = yf.Ticker(ticker)
            df = t.history(
                start      = start.strftime("%Y-%m-%d"),
                end        = date.today().strftime("%Y-%m-%d"),
                auto_adjust = True,
            )
            if df is None or df.empty or "Close" not in df.columns:
                continue

            prices = df["Close"].dropna()
            if prices.empty:
                continue

            prices.index = pd.DatetimeIndex(prices.index).normalize()
            # Strip timezone so comparisons with tz-naive cache don't raise
            if prices.index.tz is not None:
                prices.index = prices.index.tz_convert(None)
            return prices

        except Exception:
            continue

    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def get_contract_prices(
    prophetx_symbol:  str,
    excel_series:     pd.Series | None = None,
    force_refresh:    bool = False,
) -> tuple[pd.Series | None, str]:
    """
    Return the full price history for one futures contract.

    Parameters
    ----------
    prophetx_symbol : str
        The ProphetX symbol, e.g. "@CN25" or "QNGN25".
    excel_series : pd.Series | None
        Price series loaded directly from the Excel file (used to seed / fill
        gaps in the cache on first call). Pass None once the cache is seeded.
    force_refresh : bool
        If True, skip the staleness check and always attempt a yfinance fetch.

    Returns
    -------
    (series, status_message)
        series         : pd.Series with DatetimeIndex, or None on failure
        status_message : human-readable string for the Data Status page
    """
    # 1 ── Load existing Parquet cache
    cached = load_from_cache(prophetx_symbol)

    # 2 ── Merge Excel data (fills historical gaps / seeds on first run)
    if excel_series is not None and not excel_series.empty:
        if cached is None:
            cached = excel_series.copy()
        else:
            # combine_first: prefer cached, fill missing dates from Excel
            merged = excel_series.combine_first(cached)
            cached = merged.sort_index()

    if cached is None or cached.empty:
        return None, f"No data (cache empty, no Excel series) for {prophetx_symbol}"

    # 3 ── yfinance top-up for stale / active contracts
    yahoo_ticker = prophetx_to_yahoo_ticker(prophetx_symbol)

    if yahoo_ticker:
        today     = date.today()
        last_date = cached.index[-1].date()
        days_old  = (today - last_date).days

        # Top up only if the last known data is within 45 days.
        # Contracts with data older than 45 days have almost certainly
        # expired — attempting yfinance on them produces noisy failures.
        contract_likely_active = days_old < 45

        if contract_likely_active and (days_old >= 1 or force_refresh):
            fetch_from = last_date + timedelta(days=1)
            new_prices = _yfinance_fetch(yahoo_ticker, fetch_from)

            if new_prices is not None and not new_prices.empty:
                new_prices.name = prophetx_symbol
                # Only keep rows newer than what we already have
                new_prices = new_prices[new_prices.index > cached.index[-1]]
                if not new_prices.empty:
                    cached = pd.concat([cached, new_prices]).sort_index()
                    cached = cached[~cached.index.duplicated(keep="last")]

    # 4 ── Persist updated cache
    save_to_cache(prophetx_symbol, cached)

    last = cached.index[-1].date()
    return cached, f"OK — {len(cached)} days through {last}"
