"""
futures.py
----------
Provider for futures contract price data and spread computation.

Reads exclusively from the Parquet cache (data/cache/).
Excel files are never touched here — they are only used by the
one-time migration script (scripts/migrate_to_parquet.py).

PUBLIC API
----------
  build_symbol(prefix, month, year)               → str
  get_contract(symbol)                             → (Series | None, str)
  get_commodity_contracts(commodity, comm_info)    → dict[str, Series]
  fetch_spread_for_season(year, comm, info, spread)→ (Series | None, dict)

STATUS DICT FORMAT  (returned by fetch_spread_for_season)
-----------------
  {
    "season_year":   int,
    "leg1_symbol":   str | None,
    "leg2_symbol":   str | None,
    "leg1_status":   str,
    "leg2_status":   str,
    "spread_status": str,
  }
"""

import os
import glob
import pandas as pd

from src.providers.parquet_cache import get_contract_prices, _CACHE_DIR


# ── Symbol helpers ─────────────────────────────────────────────────────────────

def build_symbol(prophetx_prefix: str, month_code: str, year: int) -> str:
    """
    Build a ProphetX symbol from its parts.

    Examples
    --------
    build_symbol("@C",  "N", 2026)  →  "@CN26"
    build_symbol("@SM", "Z", 2025)  →  "@SMZ25"
    build_symbol("QNG", "N", 2025)  →  "QNGN25"
    """
    return f"{prophetx_prefix}{month_code}{str(year)[-2:]}"


# ── Single-contract access ─────────────────────────────────────────────────────

def get_contract(symbol: str) -> tuple[pd.Series | None, str]:
    """
    Load a single contract's price history from the Parquet cache.

    Automatically tops up missing recent days from yfinance if the
    contract is still within its active trading window.

    Returns
    -------
    (series, status_message)
        series  : pd.Series with DatetimeIndex, or None if not found
        message : human-readable status string
    """
    return get_contract_prices(symbol)


# ── All contracts for one commodity ───────────────────────────────────────────

def get_commodity_contracts(
    commodity:  str,
    comm_info:  dict,
) -> dict[str, pd.Series]:
    """
    Return all cached contracts for one commodity, keyed by ProphetX symbol.

    Filters the cache directory by the commodity's prophetx_prefix so only
    relevant contracts are returned (e.g. "@C*" for Corn).

    Parameters
    ----------
    commodity  : commodity name, e.g. "Corn"
    comm_info  : commodity config dict from spreads.yaml

    Returns
    -------
    dict mapping symbol → pd.Series (empty dict if nothing found)
    """
    prefix = comm_info.get("prophetx_prefix")

    # Commodities with no prefix (WheatCorn, indexes) have no own cache files
    if not prefix:
        return {}

    # Sanitise prefix for glob matching (@ is fine in filenames, not glob)
    safe_prefix = prefix.replace("@", "@")   # no-op, kept for clarity
    contracts = {}

    for cache_file in glob.glob(os.path.join(_CACHE_DIR, "*.parquet")):
        fname  = os.path.splitext(os.path.basename(cache_file))[0]
        if fname.startswith(prefix):
            series, _ = get_contract_prices(fname)
            if series is not None:
                contracts[fname] = series

    return contracts


# ── Excel fallback / auto-seeder ──────────────────────────────────────────────

def _seed_from_excel(symbol: str, commodity: str) -> pd.Series | None:
    """
    On a Parquet cache miss, load the commodity's Excel file via excel.py.
    excel.py automatically seeds the Parquet cache for every contract it
    parses, so after this call subsequent lookups hit Parquet directly.

    Returns the price Series for `symbol`, or None if not found.
    """
    try:
        from src.providers.excel import load_commodity_file
        contract_data, _ = load_commodity_file(commodity)
        return contract_data.get(symbol)
    except Exception:
        return None


# ── Spread leg resolution ──────────────────────────────────────────────────────

def _resolve_leg(
    leg:               dict,
    default_commodity: str,
    default_prefix:    str,
    season_year:       int,
) -> tuple[str | None, pd.Series | None, str]:
    """
    Resolve one spread leg definition to a (symbol, price_series, status) tuple.

    Handles three leg types defined in spreads.yaml:

    Type 1 — Standard contract leg
        { month: "N", year_offset: 0 }
        Builds symbol from default commodity's prefix.

    Type 2 — Intercommodity leg
        { month: "N", year_offset: 0, commodity: "Corn" }
        Looks up the named commodity's prefix from config.

    Type 3 — Continuous / cash index leg
        { type: "continuous", symbol: "IHX.X", commodity: "LeanHogIndex" }
        Fetches by literal symbol, no month/year construction.
    """
    # ── Type 3: continuous / cash index ───────────────────────────────────────
    if leg.get("type") == "continuous":
        symbol       = leg["symbol"]
        leg_commodity = leg.get("commodity", default_commodity)
        series, _    = get_contract_prices(symbol)

        if series is None:
            # Cache miss — seed from the commodity's Excel file
            series = _seed_from_excel(symbol, leg_commodity)

        if series is None:
            return symbol, None, f"NOT FOUND — {symbol} missing from cache and Excel file."
        return symbol, series, f"OK — {len(series)} days through {series.index[-1].date()}"

    # ── Types 1 & 2: specific contract month ──────────────────────────────────
    leg_commodity = leg.get("commodity", default_commodity)
    leg_year      = season_year + leg.get("year_offset", 0)

    # Determine prefix — use default unless the leg specifies another commodity
    if leg_commodity != default_commodity:
        from src.config import load_spreads_config, get_commodity_info as _get_info
        cfg      = load_spreads_config()
        leg_info = _get_info(cfg, leg_commodity)
        prefix   = leg_info.get("prophetx_prefix", "") if leg_info else ""
    else:
        prefix = default_prefix

    if not prefix:
        return None, None, f"FAILED — no prophetx_prefix defined for {leg_commodity}"

    symbol = build_symbol(prefix, leg["month"], leg_year)
    series, _ = get_contract_prices(symbol)

    if series is None:
        # Cache miss — seed the entire commodity's Excel file into the cache,
        # then try again. After this first load the Parquet files exist and
        # subsequent loads bypass Excel entirely.
        series = _seed_from_excel(symbol, leg_commodity)

    if series is None:
        return (
            symbol, None,
            f"NOT FOUND — {symbol} missing from cache and Excel file. "
            f"Check that the contract column exists in data/prophetx/."
        )

    return symbol, series, f"OK — {len(series)} days through {series.index[-1].date()}"


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_spread_for_season(
    season_year:    int,
    commodity:      str,
    commodity_info: dict,
    spread_def:     dict,
) -> tuple[pd.Series | None, dict]:
    """
    Fetch both contract legs and compute the spread (leg1 − leg2) for one
    season year.

    Supports same-commodity, intercommodity, and cash-index legs.

    Parameters
    ----------
    season_year    : e.g. 2026
    commodity      : e.g. "Corn"
    commodity_info : commodity config block from spreads.yaml
    spread_def     : spread config block from spreads.yaml

    Returns
    -------
    (spread_series, status_dict)
        spread_series : pd.Series with DatetimeIndex (leg1 − leg2), or None
        status_dict   : keys season_year, leg1_symbol, leg2_symbol,
                        leg1_status, leg2_status, spread_status
    """
    prefix = commodity_info.get("prophetx_prefix") or ""
    legs   = spread_def["legs"]

    status = {
        "season_year":   season_year,
        "leg1_symbol":   None,
        "leg2_symbol":   None,
        "leg1_status":   None,
        "leg2_status":   None,
        "spread_status": None,
    }

    leg1_symbol, leg1_prices, leg1_status = _resolve_leg(legs[0], commodity, prefix, season_year)
    leg2_symbol, leg2_prices, leg2_status = _resolve_leg(legs[1], commodity, prefix, season_year)

    status["leg1_symbol"] = leg1_symbol
    status["leg2_symbol"] = leg2_symbol
    status["leg1_status"] = leg1_status
    status["leg2_status"] = leg2_status

    if leg1_prices is None or leg2_prices is None:
        status["spread_status"] = "FAILED — one or both legs missing from cache"
        return None, status

    # Align on shared trading days and compute spread
    combined = pd.DataFrame({"leg1": leg1_prices, "leg2": leg2_prices}).dropna()

    if combined.empty:
        status["spread_status"] = "FAILED — no overlapping dates between the two legs"
        return None, status

    spread_series              = combined["leg1"] - combined["leg2"]
    spread_series.name         = season_year
    status["spread_status"]    = f"OK — {len(spread_series)} data points"

    return spread_series, status
