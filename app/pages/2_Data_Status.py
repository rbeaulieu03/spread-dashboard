"""
2_Data_Status.py
----------------
Shows which Excel files are loaded and which contract symbols
are available vs missing. Use this to diagnose empty charts.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import date

from src.config          import load_spreads_config, get_commodity_names, get_commodity_info, get_spreads_for_commodity
from src.providers.excel import load_commodity_file, build_prophetx_symbol

st.set_page_config(
    page_title = "Data Status",
    page_icon  = "🔎",
    layout     = "wide",
)

st.title("🔎 Data Status")
st.markdown(
    "This page checks every Excel file in `data/prophetx/` and confirms "
    "which contract symbols are available. Use it to identify missing "
    "columns before they cause empty charts."
)
st.divider()

@st.cache_data(show_spinner=False)
def load_config():
    return load_spreads_config()

config      = load_config()
commodities = get_commodity_names(config)

current_year = date.today().year
season_years = list(range(current_year - 5, current_year + 1))

selected_commodity = st.selectbox(
    "Filter by Commodity",
    options = ["All"] + commodities,
)

check_list = commodities if selected_commodity == "All" else [selected_commodity]

if st.button("▶️ Run Status Check", type="primary"):

    for commodity in check_list:
        comm_info = get_commodity_info(config, commodity)
        spreads   = get_spreads_for_commodity(config, commodity)
        prefix    = comm_info.get("prophetx_prefix", "")

        st.subheader(commodity)

        # ── Detect intercommodity spread ──────────────────────────────────
        # If any leg specifies its own commodity key, this is an
        # intercommodity spread — load each leg's file separately.
        all_legs     = [leg for s in spreads for leg in s["legs"]]
        is_intercmdy = any("commodity" in leg for leg in all_legs)

        if is_intercmdy:
            # Collect unique source commodities from leg definitions
            source_commodities = list({
                leg.get("commodity", commodity)
                for leg in all_legs
            })
            all_ok = True
            for src in sorted(source_commodities):
                src_data, src_msg = load_commodity_file(src)
                if src_data:
                    st.success(f"✅ {src_msg}")
                else:
                    st.error(f"❌ {src_msg}")
                    all_ok = False
            if not all_ok:
                st.divider()
                continue
            # Build a combined lookup dict keyed by commodity
            multi_data = {}
            for src in source_commodities:
                multi_data[src], _ = load_commodity_file(src)
        else:
            # Standard same-commodity spread
            contract_data, load_msg = load_commodity_file(commodity)
            if not contract_data:
                st.error(f"❌ {load_msg}")
                st.divider()
                continue
            else:
                st.success(f"✅ {load_msg}")
            multi_data = {commodity: contract_data}

        # ── Check each spread leg for each season year ────────────────────
        for spread_def in spreads:
            st.markdown(f"**{spread_def['name']}**")
            rows = []

            for year in season_years:
                for leg_i, leg in enumerate(spread_def["legs"]):
                    leg_year      = year + leg.get("year_offset", 0)
                    leg_commodity = leg.get("commodity", commodity)

                    # Use the correct prefix for this leg's commodity
                    if leg_commodity != commodity:
                        leg_cfg    = get_commodity_info(config, leg_commodity)
                        leg_prefix = leg_cfg.get("prophetx_prefix", "") if leg_cfg else ""
                    else:
                        leg_prefix = prefix

                    symbol       = build_prophetx_symbol(leg_prefix, leg["month"], leg_year)
                    leg_data     = multi_data.get(leg_commodity, {})
                    series       = leg_data.get(symbol)

                    if series is not None:
                        date_range = f"{series.index[0].date()} → {series.index[-1].date()}"
                        rows.append({
                            "Season Year": year,
                            "Leg":         f"Leg {leg_i + 1} ({leg_commodity})",
                            "Symbol":      symbol,
                            "Status":      "✅ OK",
                            "Days":        len(series),
                            "Date Range":  date_range,
                        })
                    else:
                        rows.append({
                            "Season Year": year,
                            "Leg":         f"Leg {leg_i + 1} ({leg_commodity})",
                            "Symbol":      symbol,
                            "Status":      "❌ MISSING",
                            "Days":        0,
                            "Date Range":  f"Add {symbol} column to {leg_commodity.lower()}.xlsx",
                        })

            df = pd.DataFrame(rows)

            def _color(row):
                color = "background-color: #0d2b0d" if "OK" in row["Status"] else "background-color: #2b0d0d"
                return [color] * len(row)

            st.dataframe(
                df.style.apply(_color, axis=1),
                use_container_width=True,
                hide_index=True,
            )

        st.divider()

else:
    st.info("Click **▶️ Run Status Check** to check all data files.")
    st.markdown("""
    **What this page checks:**
    - That each commodity's Excel file exists in `data/prophetx/`
    - That each required contract symbol column is present in that file
    - The date range of available data for each contract

    **What to do when a symbol shows ❌ MISSING:**
    1. Open Excel with the ProphetX Add-In
    2. Add that contract symbol to your existing pull (e.g. add `@CN21` as a new column)
    3. Paste as values, save the file
    4. Replace the file in `data/prophetx/` and push to GitHub

    **To add more years of history later:**
    Simply add older contract columns to your Excel files and push.
    The app will automatically detect and use the new data with no code changes.
    """)