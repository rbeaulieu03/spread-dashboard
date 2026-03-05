"""
1_Seasonality.py
----------------
Main chart page. Traders use the sidebar to select a commodity,
a spread, which years to overlay, and optional display toggles.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import date

from src.config            import load_spreads_config, get_commodity_names, get_commodity_info, get_spreads_for_commodity
from src.providers.excel   import fetch_spread_for_season
from src.seasonality       import compute_seasonality
from src.plotting          import build_seasonality_chart

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "Spread Seasonality Chart",
    page_icon  = "📈",
    layout     = "wide",
)

# ── Load config ───────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_config():
    return load_spreads_config()

config      = load_config()
commodities = get_commodity_names(config)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    st.divider()

    # 1 ── Commodity
    commodity = st.selectbox("Commodity", commodities)

    # 2 ── Spread
    comm_info    = get_commodity_info(config, commodity)
    spreads_list = get_spreads_for_commodity(config, commodity)
    spread_names = [s["name"] for s in spreads_list]

    spread_name = st.selectbox("Spread", spread_names)
    spread_def  = next(s for s in spreads_list if s["name"] == spread_name)

    # 3 ── Season years
    current_year    = date.today().year
    available_years = list(range(current_year - 5, current_year + 1))

    selected_years = st.multiselect(
        "Season Years",
        options = available_years,
        default = available_years,
        help    = "Select which historical seasons to display on the chart.",
    )

    st.divider()

    # 4 ── Display toggles
    st.subheader("Display Options")
    show_average    = st.toggle("Show Average",          value=True)
    show_percentile = st.toggle("Show 10th–90th % Band", value=True)

    st.divider()
    st.caption("Data source: ProphetX (via Excel)")
    st.caption("To update data: add rows to the Excel file and push to GitHub.")

# ── Guard ─────────────────────────────────────────────────────────────────────
if not selected_years:
    st.warning("⚠️ Select at least one season year in the sidebar.")
    st.stop()

unit = comm_info["unit"]

# ── Fetch spread data ─────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_spread_data(commodity_name: str, spread_id: str, years: tuple) -> tuple:
    cfg       = load_spreads_config()
    c_info    = get_commodity_info(cfg, commodity_name)
    s_list    = get_spreads_for_commodity(cfg, commodity_name)
    s_def     = next(s for s in s_list if s["id"] == spread_id)

    spread_data = {}
    all_status  = {}

    for yr in years:
        series, status = fetch_spread_for_season(yr, commodity_name, c_info, s_def)
        spread_data[yr] = series
        all_status[yr]  = status

    return spread_data, all_status


with st.spinner(f"Loading {commodity} {spread_name} data…"):
    spread_data, fetch_status = load_spread_data(
        commodity,
        spread_def["id"],
        tuple(sorted(selected_years)),
    )

# ── Compute seasonality pivot ─────────────────────────────────────────────────
start_mmdd = spread_def["window"]["start_mmdd"]
end_mmdd   = spread_def["window"]["end_mmdd"]

pivot = compute_seasonality(spread_data, start_mmdd, end_mmdd, selected_years)

# ── Render chart ──────────────────────────────────────────────────────────────
highlight_year = max(selected_years)

st.title(f"{commodity}  ·  {spread_name} Spread")

if pivot.empty:
    st.error(
        "No data could be loaded for this spread. "
        "Make sure the correct Excel file is in the data/prophetx/ folder "
        "and that it contains all the required contract columns. "
        "Open the **Data Status** page for details."
    )
else:
    fig = build_seasonality_chart(
        pivot                = pivot,
        commodity            = commodity,
        spread_name          = spread_name,
        unit                 = unit,
        highlight_year       = highlight_year,
        show_average         = show_average,
        show_percentile_band = show_percentile,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Quick stats ───────────────────────────────────────────────────────
    year_cols = [c for c in pivot.columns if isinstance(c, int)]

    if highlight_year in pivot.columns:
        hy_series = pivot[highlight_year].dropna()

        if not hy_series.empty:
            last_mmdd = hy_series.index[-1]
            last_val  = hy_series.iloc[-1]

            at_date = pivot.loc[last_mmdd, year_cols].dropna() if last_mmdd in pivot.index else pd.Series(dtype=float)
            pctile  = None
            if len(at_date) > 1:
                rank   = int((at_date < last_val).sum())
                pctile = round(rank / len(at_date) * 100)

            avg_val = pivot.loc[last_mmdd, "Average"] if "Average" in pivot.columns and last_mmdd in pivot.index else None

            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric(
                    label = f"{highlight_year} — latest value  (as of {last_mmdd})",
                    value = f"{last_val:.2f} {unit}",
                )
            with col2:
                if pctile is not None:
                    st.metric(
                        label = "Historical Percentile",
                        value = f"{pctile}th",
                        help  = "Where the current year sits vs all other years at this point in the season.",
                    )
            with col3:
                if avg_val is not None and not pd.isna(avg_val):
                    diff = last_val - avg_val
                    st.metric(
                        label = "vs. Average",
                        value = f"{diff:+.2f} {unit}",
                        help  = "Current year minus the historical average at this MM-DD.",
                    )

    # ── Download ──────────────────────────────────────────────────────────
    st.divider()
    st.download_button(
        label     = "⬇️ Download data as CSV",
        data      = pivot.to_csv(),
        file_name = f"{commodity}_{spread_name}_seasonality.csv",
        mime      = "text/csv",
    )

# ── Fetch details expander ────────────────────────────────────────────────────
with st.expander("🔍 Data fetch details (expand to troubleshoot)"):
    for yr, status in sorted(fetch_status.items()):
        ok = "✅" if status.get("spread_status", "").startswith("OK") else "❌"
        st.markdown(f"**{ok} Season {yr}**")
        st.caption(f"  Leg 1: {status.get('leg1_symbol')} — {status.get('leg1_status')}")
        st.caption(f"  Leg 2: {status.get('leg2_symbol')} — {status.get('leg2_status')}")
        st.caption(f"  Spread: {status.get('spread_status')}")
