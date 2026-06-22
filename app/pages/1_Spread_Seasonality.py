"""
1_Spread_Seasonality.py
-----------------------
Spread seasonality chart page.

Data flow:
  spreads.yaml → config.py → futures.py → parquet_cache.py → data/cache/
  spread series → seasonality.py (pivot) → plotting.py (Plotly chart)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import date

from src.config              import load_spreads_config, get_commodity_names, get_commodity_info, get_spreads_for_commodity
from src.providers.futures   import fetch_spread_for_season
from src.seasonality         import compute_seasonality
from src.plotting            import build_seasonality_chart

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "Spread Seasonality",
    page_icon  = "📈",
    layout     = "wide",
)

# ── Config ────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_config():
    return load_spreads_config()

config      = _load_config()
commodities = get_commodity_names(config)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    st.divider()

    commodity    = st.selectbox("Commodity", commodities)
    comm_info    = get_commodity_info(config, commodity)
    spreads_list = get_spreads_for_commodity(config, commodity)

    spread_name = st.selectbox("Spread", [s["name"] for s in spreads_list])
    spread_def  = next(s for s in spreads_list if s["name"] == spread_name)

    current_year    = date.today().year
    available_years = list(range(current_year - 5, current_year + 1))

    selected_years = st.multiselect(
        "Season Years",
        options = available_years,
        default = available_years,
    )

    st.divider()
    st.subheader("Display Options")
    show_average    = st.toggle("Show Average",           value=True)
    show_percentile = st.toggle("Show 10th–90th % Band",  value=True)
    st.divider()
    st.caption("Data: Parquet cache + yfinance (auto-updated daily)")

# ── Guard ─────────────────────────────────────────────────────────────────────
if not selected_years:
    st.warning("Select at least one season year in the sidebar.")
    st.stop()

# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_spreads(commodity_name: str, spread_id: str, years: tuple) -> tuple:
    cfg        = load_spreads_config()
    c_info     = get_commodity_info(cfg, commodity_name)
    s_def      = next(s for s in get_spreads_for_commodity(cfg, commodity_name) if s["id"] == spread_id)
    spread_data, all_status = {}, {}
    for yr in years:
        series, status       = fetch_spread_for_season(yr, commodity_name, c_info, s_def)
        spread_data[yr]      = series
        all_status[yr]       = status
    return spread_data, all_status

with st.spinner(f"Loading {commodity} — {spread_name}…"):
    spread_data, fetch_status = _load_spreads(
        commodity,
        spread_def["id"],
        tuple(sorted(selected_years)),
    )

# ── Seasonality pivot ─────────────────────────────────────────────────────────
pivot = compute_seasonality(
    spread_data,
    spread_def["window"]["start_mmdd"],
    spread_def["window"]["end_mmdd"],
    selected_years,
    spread_def["window"].get("display_start_mmdd"),
)

# ── Render ────────────────────────────────────────────────────────────────────
st.title(f"{commodity}  ·  {spread_name} Spread")

if pivot.empty:
    # Surface exactly what failed so the user knows how to fix it
    failed = [
        f"**{yr}** — {st['spread_status']} "
        f"(leg 1: {st['leg1_symbol']} {st['leg1_status'] or ''} / "
        f"leg 2: {st['leg2_symbol']} {st['leg2_status'] or ''})"
        for yr, st in fetch_status.items()
        if not (st.get("spread_status") or "").startswith("OK")
    ]
    st.error(
        "No data could be loaded for this spread. "
        "Check the **Data Status** page, or re-run `scripts/migrate_to_parquet.py` "
        "if the cache is missing."
    )
    if failed:
        with st.expander("Which years failed and why"):
            for line in failed:
                st.markdown(line)
else:
    fig = build_seasonality_chart(
        pivot                = pivot,
        commodity            = commodity,
        spread_name          = spread_name,
        unit                 = comm_info["unit"],
        highlight_year       = max(selected_years),
        show_average         = show_average,
        show_percentile_band = show_percentile,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Quick stats ───────────────────────────────────────────────────────────
    highlight_year = max(selected_years)
    year_cols      = [c for c in pivot.columns if isinstance(c, int)]

    if highlight_year in pivot.columns:
        hy = pivot[highlight_year].dropna()
        if not hy.empty:
            last_mmdd = hy.index[-1]
            last_val  = hy.iloc[-1]
            unit      = comm_info["unit"]

            at_date = pivot.loc[last_mmdd, year_cols].dropna() if last_mmdd in pivot.index else pd.Series(dtype=float)
            pctile  = round(int((at_date < last_val).sum()) / len(at_date) * 100) if len(at_date) > 1 else None
            avg_val = pivot.loc[last_mmdd, "Average"] if "Average" in pivot.columns and last_mmdd in pivot.index else None

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric(f"{highlight_year} — latest  (as of {last_mmdd})", f"{last_val:.2f} {unit}")
            with c2:
                if pctile is not None:
                    st.metric("Historical Percentile", f"{pctile}th",
                              help="Where the current year sits vs all other years at this point in the season.")
            with c3:
                if avg_val is not None and not pd.isna(avg_val):
                    st.metric("vs. Average", f"{last_val - avg_val:+.2f} {unit}",
                              help="Current year minus the historical average at this MM-DD.")

    st.divider()
    st.download_button(
        label     = "⬇️ Download data as CSV",
        data      = pivot.to_csv(),
        file_name = f"{commodity}_{spread_name}_seasonality.csv",
        mime      = "text/csv",
    )

# ── Fetch detail expander ──────────────────────────────────────────────────────
with st.expander("🔍 Data fetch details"):
    for yr, status in sorted(fetch_status.items()):
        ok = "✅" if (status.get("spread_status") or "").startswith("OK") else "❌"
        st.markdown(f"**{ok} Season {yr}**")
        st.caption(f"  Leg 1: {status.get('leg1_symbol')} — {status.get('leg1_status')}")
        st.caption(f"  Leg 2: {status.get('leg2_symbol')} — {status.get('leg2_status')}")
        st.caption(f"  Spread: {status.get('spread_status')}")
