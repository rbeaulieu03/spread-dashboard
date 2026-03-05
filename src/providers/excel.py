"""
excel.py
--------
Reads futures contract price data from ProphetX Excel export files.

EXPECTED FILE FORMAT
---------------------
One Excel file per commodity, saved in the data/prophetx/ folder.
Files must be named exactly:
    corn.xlsx
    wheat.xlsx
    soymeal.xlsx
    cattle.xlsx
    hogs.xlsx
    natgas.xlsx

EXPECTED SHEET LAYOUT (paste-as-values from ProphetX Add-In):
    Row 1:  DAILY    | @CN26  | @CU26  | @CZ26  | ...
    Row 2:  (blank or "Description" — skipped)
    Row 3:  Date     | Close  | Close  | Close  | ...
    Row 4+: 46085    | 451.50 | 402.00 | ---    | ...

    - Date column contains Excel serial date numbers (e.g. 46085)
    - Price columns contain decimal numbers (e.g. 451.5000)
    - Missing data shows as "---" or is blank

ADDING MORE YEARS LATER
------------------------
Simply add more contract columns to your Excel file (e.g. add @CN20 for
an older year), paste updated data, save, and push to GitHub.
The app will automatically pick up the new columns with no code changes.
"""

import pandas as pd
import numpy as np
import os
import streamlit as st

# Path to the ProphetX Excel data folder
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR     = os.path.join(_PROJECT_ROOT, "data", "prophetx")

# Map commodity names (as used in spreads.yaml) to Excel filenames
_COMMODITY_FILES = {
    "Corn":       "corn.xlsx",
    "Wheat":      "wheat.xlsx",
    "SoyMeal":    "soymeal.xlsx",
    "LiveCattle": "cattle.xlsx",
    "LeanHogs":   "hogs.xlsx",
    "NatGas":     "natgas.xlsx",
    "KCWheat":    "kcwheat.xlsx",
    "SoyOil":     "soyoil.xlsx",
}


# ── Excel serial date conversion ─────────────────────────────────────────────

def _excel_serial_to_date(serial) -> pd.Timestamp | None:
    """
    Convert an Excel serial date number to a pandas Timestamp.

    Excel counts days from 1900-01-01 (with a historical leap year bug
    that adds 1 extra day, which is why we subtract 2 instead of 1).

    Examples:
        46085 → 2026-03-04
        44927 → 2023-01-01
    """
    try:
        serial = int(float(serial))
        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=serial)
    except (ValueError, TypeError):
        return None


# ── File loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_commodity_file(commodity: str) -> tuple:
    """
    Load and parse a ProphetX Excel file for one commodity.

    Returns
    -------
    (contract_data, status_message)
        contract_data : dict mapping ProphetX symbol (e.g. "@CN24") →
                        pd.Series with DatetimeIndex and decimal close prices
        status_message: human-readable string for the Data Status page
    """
    filename = _COMMODITY_FILES.get(commodity)
    if filename is None:
        return {}, f"No file mapping defined for commodity '{commodity}'"

    filepath = os.path.join(_DATA_DIR, filename)
    if not os.path.exists(filepath):
        return {}, (
            f"File not found: data/prophetx/{filename}. "
            f"Please create this file using the ProphetX Excel Add-In "
            f"and place it in the data/prophetx/ folder."
        )

    try:
        # Read raw Excel — no headers yet, we'll parse manually
        raw = pd.read_excel(filepath, header=None, dtype=str)

        if raw.shape[0] < 4:
            return {}, f"{filename}: file has fewer than 4 rows — check the format."

        # ── Find the ticker row (row 0) and date/close row (row 2) ──────────
        # Row 0: "DAILY", "@CN26", "@CU26", ...
        # Row 2: "Date",  "Close", "Close", ...
        ticker_row = raw.iloc[0].tolist()   # ["DAILY", "@CN26", "@CU26", ...]
        data_start = 3                       # data begins on row index 3

        # Extract column headers — skip column 0 (the Date column label)
        tickers = []
        ticker_col_indices = []
        for col_idx, cell in enumerate(ticker_row):
            if col_idx == 0:
                continue
            cell_str = str(cell).strip()
            # Accept any non-empty header that is not a blank/nan/DAILY label
            if cell_str not in ("", "nan", "DAILY", "Description"):
                tickers.append(cell_str)
                ticker_col_indices.append(col_idx)

        if not tickers:
            return {}, f"{filename}: no ProphetX symbols (starting with @) found in row 1."

        # ── Parse date column ────────────────────────────────────────────────
        date_col_raw = raw.iloc[data_start:, 0].tolist()
        dates = []
        valid_row_mask = []

        for val in date_col_raw:
            val_str = str(val).strip()
            if val_str in ("", "nan", "---"):
                valid_row_mask.append(False)
                dates.append(None)
                continue
            ts = _excel_serial_to_date(val_str)
            if ts is None:
                valid_row_mask.append(False)
                dates.append(None)
            else:
                valid_row_mask.append(True)
                dates.append(ts)

        # ── Build one Series per contract ────────────────────────────────────
        contract_data = {}

        for ticker, col_idx in zip(tickers, ticker_col_indices):
            price_col_raw = raw.iloc[data_start:, col_idx].tolist()
            prices = []
            price_dates = []

            for i, (valid, date, price_str) in enumerate(
                zip(valid_row_mask, dates, price_col_raw)
            ):
                if not valid:
                    continue
                price_str = str(price_str).strip()
                if price_str in ("", "nan", "---"):
                    continue
                try:
                    price = float(price_str)
                    prices.append(price)
                    price_dates.append(date)
                except ValueError:
                    continue

            if prices:
                series = pd.Series(
                    data  = prices,
                    index = pd.DatetimeIndex(price_dates),
                    name  = ticker,
                ).sort_index()
                # Remove any duplicate dates (keep last)
                series = series[~series.index.duplicated(keep="last")]
                contract_data[ticker] = series

        if not contract_data:
            return {}, f"{filename}: file was read but no valid price data was found."

        status = (
            f"OK — {filename} loaded. "
            f"{len(contract_data)} contracts found: {', '.join(sorted(contract_data.keys()))}"
        )
        return contract_data, status

    except Exception as e:
        return {}, f"Error reading {filename}: {e}"


# ── Symbol building ───────────────────────────────────────────────────────────

def build_prophetx_symbol(prophetx_prefix: str, month_code: str, year: int) -> str:
    """
    Build a ProphetX symbol string.

    Examples:
        build_prophetx_symbol("@C", "N", 2024)  →  "@CN24"
        build_prophetx_symbol("@SM", "Z", 2023) →  "@SMZ23"

    Parameters
    ----------
    prophetx_prefix : e.g. "@C" for Corn, "@SM" for Soy Meal
    month_code      : single letter, e.g. "N" for July
    year            : 4-digit year, e.g. 2024
    """
    year_2digit = str(year)[-2:]
    return f"{prophetx_prefix}{month_code}{year_2digit}"


# ── Spread fetching ───────────────────────────────────────────────────────────

def fetch_spread_for_season(season_year: int, commodity: str, commodity_info: dict, spread_def: dict) -> tuple:
    """
    Look up both contract legs from the loaded Excel data and compute
    the spread (leg1 price − leg2 price) for one season year.

    Parameters
    ----------
    season_year    : int  — e.g. 2024
    commodity      : str  — e.g. "Corn"
    commodity_info : dict — from spreads.yaml
    spread_def     : dict — from spreads.yaml

    Returns
    -------
    (spread_series, status_dict)
        spread_series : pd.Series with DatetimeIndex, or None if data missing
        status_dict   : details for the Data Status page
    """
    prefix = commodity_info.get("prophetx_prefix")
    legs   = spread_def["legs"]

    status = {
        "season_year":  season_year,
        "leg1_symbol":  None,
        "leg2_symbol":  None,
        "leg1_status":  None,
        "leg2_status":  None,
        "spread_status": None,
    }

    if not prefix:
        status["spread_status"] = f"FAILED — no prophetx_prefix defined for {commodity} in spreads.yaml"
        return None, status

    # Load the full commodity file (cached after first load)
    contract_data, load_msg = load_commodity_file(commodity)

    if not contract_data:
        status["spread_status"] = f"FAILED — {load_msg}"
        return None, status

    # Build symbol strings for each leg
    leg1_year   = season_year + legs[0].get("year_offset", 0)
    leg2_year   = season_year + legs[1].get("year_offset", 0)
    leg1_symbol = build_prophetx_symbol(prefix, legs[0]["month"], leg1_year)
    leg2_symbol = build_prophetx_symbol(prefix, legs[1]["month"], leg2_year)

    status["leg1_symbol"] = leg1_symbol
    status["leg2_symbol"] = leg2_symbol

    # Look up each leg in the loaded contract data
    leg1_prices = contract_data.get(leg1_symbol)
    leg2_prices = contract_data.get(leg2_symbol)

    status["leg1_status"] = (
        f"OK — {len(leg1_prices)} days" if leg1_prices is not None
        else f"NOT FOUND in Excel file — add {leg1_symbol} column to the spreadsheet"
    )
    status["leg2_status"] = (
        f"OK — {len(leg2_prices)} days" if leg2_prices is not None
        else f"NOT FOUND in Excel file — add {leg2_symbol} column to the spreadsheet"
    )

    if leg1_prices is None or leg2_prices is None:
        status["spread_status"] = "FAILED — one or both legs missing from Excel file"
        return None, status

    # Align on shared trading days and compute spread
    combined = pd.DataFrame({
        "leg1": leg1_prices,
        "leg2": leg2_prices,
    }).dropna()

    if combined.empty:
        status["spread_status"] = "FAILED — no overlapping dates between the two legs"
        return None, status

    spread_series = combined["leg1"] - combined["leg2"]
    spread_series.name = season_year
    status["spread_status"] = f"OK — {len(spread_series)} data points"

    return spread_series, status