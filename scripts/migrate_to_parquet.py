"""
migrate_to_parquet.py
---------------------
ONE-TIME migration script.

Reads every Excel file in data/prophetx/, parses all contract columns,
and writes each contract's price history to a Parquet file in data/cache/.

After this script completes successfully, the Excel files become an archive
you never have to touch again. The Streamlit app will read from Parquet and
top up daily via yfinance going forward.

USAGE
-----
From the spread-dashboard project root:

    python scripts/migrate_to_parquet.py

You can safely re-run it — existing Parquet files are merged with (not
overwritten by) the Excel data, so no history is lost.

OUTPUT
------
  data/cache/@CN20.parquet
  data/cache/@CN21.parquet
  ...  (one file per contract symbol across all commodities)
"""

import sys
import os

# Allow imports from the project root (src package)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
from src.providers.excel          import load_commodity_file, _COMMODITY_FILES
from src.providers.parquet_cache  import save_to_cache, load_from_cache


def migrate_commodity(commodity: str, filename: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  Commodity : {commodity}")
    print(f"  File      : data/prophetx/{filename}")
    print(f"{'─' * 60}")

    # load_commodity_file already parses the Excel correctly
    # Pass ttl=None workaround: call without Streamlit cache wrapper
    contract_data, status = _load_excel_directly(commodity, filename)

    if not contract_data:
        print(f"  ⚠  Skipped — {status}")
        return

    saved = 0
    for symbol, excel_series in contract_data.items():
        existing = load_from_cache(symbol)

        if existing is not None:
            # Merge: prefer existing cache, fill gaps from Excel
            merged = excel_series.combine_first(existing).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]
        else:
            merged = excel_series

        save_to_cache(symbol, merged)

        first = merged.index[0].date()
        last  = merged.index[-1].date()
        rows  = len(merged)
        print(f"  ✓  {symbol:<14}  {rows:>5} rows   {first} → {last}")
        saved += 1

    print(f"\n  → {saved} contracts written to data/cache/")


def _load_excel_directly(commodity: str, filename: str) -> tuple:
    """
    Parse the Excel file without going through Streamlit's cache decorator,
    and without triggering the yfinance top-up (this is migration only).
    We replicate the core parsing logic from excel.py here.
    """
    import numpy as np
    from src.providers.excel import _DATA_DIR, _excel_serial_to_date

    filepath = os.path.join(_DATA_DIR, filename)
    if not os.path.exists(filepath):
        return {}, f"File not found: {filepath}"

    try:
        raw = pd.read_excel(filepath, header=None, dtype=str)
        if raw.shape[0] < 4:
            return {}, f"{filename}: fewer than 4 rows"

        ticker_row = raw.iloc[0].tolist()
        data_start = 3

        tickers, ticker_cols = [], []
        for col_idx, cell in enumerate(ticker_row):
            if col_idx == 0:
                continue
            cell_str = str(cell).strip()
            if cell_str not in ("", "nan", "DAILY", "Description"):
                tickers.append(cell_str)
                ticker_cols.append(col_idx)

        if not tickers:
            return {}, f"{filename}: no ticker symbols found in row 1"

        date_col_raw = raw.iloc[data_start:, 0].tolist()
        dates, valid_mask = [], []
        for val in date_col_raw:
            val_str = str(val).strip()
            if val_str in ("", "nan", "---"):
                valid_mask.append(False)
                dates.append(None)
                continue
            ts = _excel_serial_to_date(val_str)
            if ts is None:
                valid_mask.append(False)
                dates.append(None)
            else:
                valid_mask.append(True)
                dates.append(ts)

        contract_data = {}
        for ticker, col_idx in zip(tickers, ticker_cols):
            price_col_raw = raw.iloc[data_start:, col_idx].tolist()
            prices, price_dates = [], []
            for valid, dt, price_str in zip(valid_mask, dates, price_col_raw):
                if not valid:
                    continue
                price_str = str(price_str).strip()
                if price_str in ("", "nan", "---"):
                    continue
                try:
                    price = float(price_str)
                    prices.append(price)
                    price_dates.append(dt)
                except ValueError:
                    continue

            if prices:
                s = pd.Series(
                    data  = prices,
                    index = pd.DatetimeIndex(price_dates),
                    name  = ticker,
                ).sort_index()
                s = s[~s.index.duplicated(keep="last")]
                contract_data[ticker] = s

        if not contract_data:
            return {}, f"{filename}: no valid price data found"

        return contract_data, "OK"

    except Exception as e:
        return {}, f"Error reading {filename}: {e}"


def main():
    print("=" * 60)
    print("  Spread Dashboard — Excel → Parquet Migration")
    print("=" * 60)

    # Only migrate commodities that have an actual Excel file mapping
    to_migrate = {
        comm: fname
        for comm, fname in _COMMODITY_FILES.items()
        if fname is not None
    }

    print(f"\nFound {len(to_migrate)} commodities to migrate:")
    for comm, fname in to_migrate.items():
        print(f"  {comm:<25} → {fname}")

    total_contracts = 0
    for commodity, filename in to_migrate.items():
        migrate_commodity(commodity, filename)

    # Summary
    from src.providers.parquet_cache import _CACHE_DIR
    import glob
    parquet_files = glob.glob(os.path.join(_CACHE_DIR, "*.parquet"))
    print(f"\n{'=' * 60}")
    print(f"  Migration complete.")
    print(f"  {len(parquet_files)} Parquet files now in data/cache/")
    print(f"  The app will top up missing days from yfinance on next load.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
