"""
iv.py
-----
Reads implied volatility data from Bloomberg Excel export files.

EXPECTED FILE FORMAT
---------------------
One Excel file per commodity, saved in the data/bloomberg/ folder.
Files must be named exactly:
    corn_iv.xlsx
    meal_iv.xlsx

Add more commodities later by adding entries to _IV_FILES below
and creating the corresponding Excel file.

EXPECTED SHEET LAYOUT (paste-as-values from Bloomberg terminal):
    Row 1:  Date  | SM 2M 50D VOL... | 2026  | 2025  | 2024  | 2023  | 2022  | 2021
    Row 2+: 31-Dec| (avg value)      | 22.19 | 16.96 | ...   | ...   | ...   | ...

    - Date column: text strings like "31-Dec", "30-Nov", "1-Jan" etc.
    - Year columns: plain decimal numbers (e.g. 22.197)
    - Missing values: blank cells (weekends/holidays)
    - The average column (Bloomberg pre-calc) is ignored — app computes its own

ADDING MORE COMMODITIES LATER
-------------------------------
1. Add an entry to _IV_FILES below
2. Add an entry to _IV_LABELS below (display name and unit)
3. Create the Excel file in data/bloomberg/ using the same format
4. Push to GitHub — it appears in the dropdown automatically
"""

import pandas as pd
import os
import streamlit as st

# ── File paths ────────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR     = os.path.join(_PROJECT_ROOT, "data", "bloomberg")

# ── Commodity registry ────────────────────────────────────────────────────────
# To add a new commodity: add one line to each dict below.
_IV_FILES = {
    "Corn":    "corn_iv.xlsx",
    "Meal":    "meal_iv.xlsx",
}

_IV_LABELS = {
    "Corn":    "Corn 2M 50D Implied Volatility",
    "Meal":    "Soy Meal 2M 50D Implied Volatility",
}


def get_iv_commodities() -> list:
    """Return list of commodity names that have IV data configured."""
    return list(_IV_FILES.keys())


def get_iv_label(commodity: str) -> str:
    """Return the display label for a commodity's IV chart title."""
    return _IV_LABELS.get(commodity, f"{commodity} Implied Volatility")


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_bloomberg_date(date_str: str) -> str | None:
    """
    Convert Bloomberg date string to MM-DD format.

    Bloomberg exports dates as "31-Dec", "1-Jan", "15-Mar" etc.

    Returns MM-DD string e.g. "12-31", "01-01", "03-15"
    or None if the string can't be parsed.
    """
    date_str = str(date_str).strip()
    if date_str in ("", "nan"):
        return None

    try:
        # pandas can parse "31-Dec", "1-Jan" etc. using a reference year
        ts = pd.to_datetime(date_str + "-2000", format="%d-%b-%Y")
        return ts.strftime("%m-%d")
    except Exception:
        pass

    # Fallback: try pandas generic parser
    try:
        ts = pd.to_datetime(date_str)
        return ts.strftime("%m-%d")
    except Exception:
        return None


# ── Full calendar year MM-DD index ────────────────────────────────────────────

def _build_calendar_index() -> list:
    """
    Build a full Jan–Dec ordered MM-DD index using a non-leap reference year.
    Used as the x-axis for IV charts.
    """
    idx = pd.date_range(start="2023-01-01", end="2023-12-31", freq="D")
    return [d.strftime("%m-%d") for d in idx]


# ── File loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_iv_data(commodity: str) -> tuple:
    """
    Load and parse a Bloomberg IV Excel file for one commodity.

    Returns
    -------
    (pivot, status_message)
        pivot          : pd.DataFrame with MM-DD index, year columns, Average column
                         Empty DataFrame if file could not be loaded.
        status_message : human-readable string for troubleshooting
    """
    filename = _IV_FILES.get(commodity)
    if filename is None:
        return pd.DataFrame(), f"No file mapping defined for '{commodity}'"

    filepath = os.path.join(_DATA_DIR, filename)
    if not os.path.exists(filepath):
        return pd.DataFrame(), (
            f"File not found: data/bloomberg/{filename}. "
            f"Please create this file from your Bloomberg pull "
            f"and place it in the data/bloomberg/ folder."
        )

    try:
        # Read raw — no header parsing yet
        raw = pd.read_excel(filepath, header=None, dtype=str)

        if raw.shape[0] < 2:
            return pd.DataFrame(), f"{filename}: file has fewer than 2 rows."

        # ── Find the header row and year columns ──────────────────────────────
        # Scan every row looking for one that contains 4-digit year values.
        # This handles files where row 1 is blank or has a title.
        header_row_idx = None
        year_col_map   = {}   # {year_int: col_index}

        for row_idx in range(min(5, raw.shape[0])):
            row = raw.iloc[row_idx].tolist()
            found_years = {}
            for col_idx, cell in enumerate(row):
                cell_str = str(cell).strip()
                try:
                    yr = int(float(cell_str))
                    if 2015 <= yr <= 2035:
                        found_years[yr] = col_idx
                except (ValueError, TypeError):
                    continue
            if found_years:
                header_row_idx = row_idx
                year_col_map   = found_years
                break

        if not year_col_map:
            return pd.DataFrame(), (
                f"{filename}: no year columns found in the first 5 rows. "
                f"Expected columns labelled 2021, 2022, 2023 etc."
            )

        # ── Find the date column ──────────────────────────────────────────────
        # Scan the first data row after the header to find which column
        # contains a parseable date string like "31-Dec" or "1-Jan".
        data_start_row = header_row_idx + 1
        date_col_idx   = None

        if data_start_row < raw.shape[0]:
            for col_idx in range(min(5, raw.shape[1])):
                cell_str = str(raw.iloc[data_start_row, col_idx]).strip()
                if _parse_bloomberg_date(cell_str) is not None:
                    date_col_idx = col_idx
                    break

        if date_col_idx is None:
            return pd.DataFrame(), (
                f"{filename}: could not find a date column. "
                f"Expected dates like '31-Dec', '1-Jan' in one of the first 5 columns."
            )

        # ── Build the full calendar MM-DD index ───────────────────────────────
        calendar_index = _build_calendar_index()
        pivot = pd.DataFrame(index=calendar_index)
        pivot.index.name = "MM-DD"

        # ── Parse data rows ───────────────────────────────────────────────────
        for row_idx in range(data_start_row, raw.shape[0]):
            date_cell = str(raw.iloc[row_idx, date_col_idx]).strip()
            mmdd = _parse_bloomberg_date(date_cell)

            if mmdd is None or mmdd not in pivot.index:
                continue

            for year, col_idx in year_col_map.items():
                val_str = str(raw.iloc[row_idx, col_idx]).strip()
                if val_str in ("", "nan", "---", "#N/A", "N/A"):
                    continue
                try:
                    pivot.loc[mmdd, year] = float(val_str)
                except ValueError:
                    continue

        # ── Validate we got something ─────────────────────────────────────────
        year_cols = [c for c in pivot.columns if isinstance(c, int)]
        if not year_cols:
            return pd.DataFrame(), f"{filename}: file was read but no valid IV data was found."

        # ── Forward-fill small gaps (weekends/holidays, max 3 days) ──────────
        pivot = pivot.ffill(limit=3)

        # ── Compute cross-year average and percentile band ────────────────────
        pivot["Average"] = pivot[year_cols].mean(axis=1)

        if len(year_cols) >= 4:
            pivot["p10"] = pivot[year_cols].quantile(0.10, axis=1)
            pivot["p90"] = pivot[year_cols].quantile(0.90, axis=1)

        years_found = sorted(year_cols)
        status = (
            f"OK — {filename} loaded. "
            f"Years found: {', '.join(str(y) for y in years_found)}"
        )
        return pivot, status

    except Exception as e:
        return pd.DataFrame(), f"Error reading {filename}: {e}"