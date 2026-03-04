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

        # ── Check that the Excel file loads ───────────────────────────────
        contract_data, load_msg = load_commodity_file(commodity)
        if not contract_data:
            st.error(f"❌ {load_msg}")
            st.divider()
            continue
        else:
            st.success(f"✅ {load_msg}")

        # ── Check each spread leg for each season year ────────────────────
        for spread_def in spreads:
            st.markdown(f"**{spread_def['name']}**")
            rows = []

            for year in season_years:
                for leg_i, leg in enumerate(spread_def["legs"]):
                    leg_year = year + leg.get("year_offset", 0)
                    symbol   = build_prophetx_symbol(prefix, leg["month"], leg_year)
                    series   = contract_data.get(symbol)

                    if series is not None:
                        date_range = f"{series.index[0].date()} → {series.index[-1].date()}"
                        rows.append({
                            "Season Year": year,
                            "Leg":         f"Leg {leg_i + 1}",
                            "Symbol":      symbol,
                            "Status":      "✅ OK",
                            "Days":        len(series),
                            "Date Range":  date_range,
                        })
                    else:
                        rows.append({
                            "Season Year": year,
                            "Leg":         f"Leg {leg_i + 1}",
                            "Symbol":      symbol,
                            "Status":      "❌ MISSING",
                            "Days":        0,
                            "Date Range":  f"Add {symbol} column to your Excel file",
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
