"""
seasonality.py
--------------
Transforms raw spread price data into a seasonality pivot table.

Each season year's data is aligned onto a common MM-DD x-axis so that
"March 15" of 2022 sits directly above "March 15" of 2023, allowing
visual comparison of where the current year sits relative to history.

OUTPUT FORMAT
-------------
A pandas DataFrame where:
  - index   = ordered MM-DD strings  (the x-axis)
  - columns = season year integers + "Average" + "p10" + "p90"

WINDOW LOGIC
-------------
start_mmdd > end_mmdd  → wrapping window (crosses a calendar year)
  e.g. "07-15" → "07-10"  spans Jul 15 of (year-1) through Jul 10 of year

start_mmdd <= end_mmdd → non-wrapping window (within one calendar year)
  e.g. "01-03" → "12-14"  spans Jan 3 through Dec 14 of (year-1)
"""

import pandas as pd
import numpy as np
from datetime import date, timedelta


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_mmdd(mmdd: str) -> tuple:
    """'07-15' → (7, 15)"""
    m, d = mmdd.split("-")
    return int(m), int(d)


def _is_wrapping(start_mmdd: str, end_mmdd: str) -> bool:
    """Return True if the window crosses a year boundary."""
    return _parse_mmdd(start_mmdd) > _parse_mmdd(end_mmdd)


# ── Public functions ──────────────────────────────────────────────────────────

def get_window_dates(season_year: int, start_mmdd: str, end_mmdd: str) -> tuple:
    """
    Return (start_date, end_date) for one season's data window.

    The "season year" label matches the year the front-leg contract expires
    or the year that contains the end of the window.

    Wrapping window (start > end, e.g. 07-15 → 07-10):
        data_start = (season_year - 1, start_mm, start_dd)
        data_end   = (season_year,     end_mm,   end_dd)

    Non-wrapping window (start <= end, e.g. 01-03 → 12-14):
        data_start = (season_year - 1, start_mm, start_dd)
        data_end   = (season_year - 1, end_mm,   end_dd)
    """
    sm, sd = _parse_mmdd(start_mmdd)
    em, ed = _parse_mmdd(end_mmdd)

    start_date = date(season_year - 1, sm, sd)

    if _is_wrapping(start_mmdd, end_mmdd):
        end_date = date(season_year, em, ed)
    else:
        end_date = date(season_year - 1, em, ed)

    return start_date, end_date


def build_mmdd_index(start_mmdd: str, end_mmdd: str) -> list:
    """
    Build an ordered list of MM-DD strings for the chart x-axis.

    Uses a fixed reference year to generate consistent dates.
    Handles year-wrapping windows correctly.

    Wrapping:  "07-15" → "07-10"  →  ["07-15", ..., "12-31", "01-01", ..., "07-10"]
    Non-wrap:  "01-03" → "12-14"  →  ["01-03", "01-04", ..., "12-14"]
    """
    sm, sd = _parse_mmdd(start_mmdd)
    em, ed = _parse_mmdd(end_mmdd)

    # Use a non-leap reference year so Feb-29 never appears
    ref_year = 2023

    start = date(ref_year, sm, sd)
    if _is_wrapping(start_mmdd, end_mmdd):
        end = date(ref_year + 1, em, ed)
    else:
        end = date(ref_year, em, ed)

    result  = []
    current = start
    while current <= end:
        result.append(current.strftime("%m-%d"))
        current += timedelta(days=1)

    return result


def compute_seasonality(
    spread_data:        dict,
    start_mmdd:         str,
    end_mmdd:           str,
    season_years:       list,
    display_start_mmdd: str = None,
) -> pd.DataFrame:
    """
    Build the seasonality pivot table from per-season spread data.

    Parameters
    ----------
    spread_data        : {season_year (int): pd.Series with DatetimeIndex} or None per year
    start_mmdd         : window start, e.g. "07-15"  (used for contract fetching)
    end_mmdd           : window end,   e.g. "07-10"
    season_years       : years to include, e.g. [2021, 2022, 2023, 2024, 2025, 2026]
    display_start_mmdd : optional MM-DD to trim the x-axis start for display purposes.
                         Must fall within the window. Useful when contracts don't have
                         data at the very start of the fetch window (e.g. "01-27").
                         Does not affect which contracts are fetched.

    Returns
    -------
    pd.DataFrame
        Rows  = MM-DD strings in window order.
        Cols  = season year ints + "Average" + "p10" + "p90".
        Empty if no data could be loaded at all.
    """
    mmdd_index = build_mmdd_index(start_mmdd, end_mmdd)

    # Build the pivot with the full ordered MM-DD index
    pivot = pd.DataFrame(index=mmdd_index)
    pivot.index.name = "MM-DD"

    for year in sorted(season_years):
        series = spread_data.get(year)
        if series is None or series.empty:
            continue

        # Filter the series to this season's window
        start_date, end_date = get_window_dates(year, start_mmdd, end_mmdd)

        # Cap end_date at today — don't try to show future data
        today = pd.Timestamp(date.today())
        end_date_ts = pd.Timestamp(end_date)
        effective_end = min(end_date_ts, today)

        mask = (
            (series.index >= pd.Timestamp(start_date)) &
            (series.index <= effective_end)
        )
        windowed = series[mask].copy()

        if windowed.empty:
            continue

        # Convert dates to MM-DD strings, preserving chronological order
        windowed.index = pd.Index(windowed.index.strftime("%m-%d"))

        # Remove any duplicates (edge case: leap year Feb-29 → Feb-28 collision)
        windowed = windowed[~windowed.index.duplicated(keep="last")]

        # Align to the pivot's ordered MM-DD index using reindex
        # This ensures the correct window-order is always maintained
        windowed = windowed.reindex(mmdd_index)

        pivot[year] = windowed

    if pivot.empty or not any(isinstance(c, int) for c in pivot.columns):
        return pd.DataFrame()

    # Forward-fill small gaps (weekends, holidays) — max 3 calendar days
    pivot = pivot.ffill(limit=3)

    # ── Cross-year statistics ─────────────────────────────────────────────────
    year_cols = [c for c in pivot.columns if isinstance(c, int)]

    # Count how many seasons actually have data at each MM-DD position.
    # Stats are only meaningful where enough seasons overlap — otherwise the
    # band and average reflect a small biased sample (e.g. the early part of
    # a long window where the back-leg contract doesn't exist yet).
    if year_cols:
        row_counts = pivot[year_cols].count(axis=1)
        min_years_for_avg  = max(3, len(year_cols) // 2)
        min_years_for_band = max(4, len(year_cols) // 2 + 1)

        pivot["Average"] = pivot[year_cols].mean(axis=1).where(
            row_counts >= min_years_for_avg
        )

    # Only compute percentile band when we have enough years overall AND
    # enough seasons have data at each individual row position.
    if len(year_cols) >= 4:
        pivot["p10"] = pivot[year_cols].quantile(0.10, axis=1).where(
            row_counts >= min_years_for_band
        )
        pivot["p90"] = pivot[year_cols].quantile(0.90, axis=1).where(
            row_counts >= min_years_for_band
        )

    # ── Optional display trimming ─────────────────────────────────────────────
    # Trim the x-axis start without affecting the underlying data fetch.
    # Used when contracts don't have data at the very start of the fetch window.
    if display_start_mmdd is not None and display_start_mmdd in pivot.index:
        start_pos = pivot.index.get_loc(display_start_mmdd)
        pivot = pivot.iloc[start_pos:]

    return pivot