"""
Home.py
-------
Landing page for the Spread Seasonality Dashboard.
Traders see a brief description and click through to the Seasonality page.
"""

import sys
import os

# Make sure Python can find the 'src' package.
# Home.py lives at:  spread-dashboard/app/Home.py
# We need to add:    spread-dashboard/  to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(
    page_title  = "Spread Dashboard",
    page_icon   = "📊",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📊 Spread Seasonality Dashboard")
st.markdown("---")

# ── Description ───────────────────────────────────────────────────────────────
st.markdown("""
### Welcome

This dashboard shows **spread seasonality** for key commodity futures markets.

Use it to see how a spread (the price difference between two contract months)
has behaved historically at this time of year, and where the current year
sits relative to prior seasons.

---

### How to use it

1. Click **Seasonality** in the left sidebar to open the chart page.
2. In the sidebar controls, pick your **Commodity** and **Spread**.
3. Toggle years, the average line, and the percentile band on or off.
4. Hover over the chart to see exact values for each year.
5. Use the **Download CSV** button to pull the underlying data into Excel.

---

### Commodities & spreads available
""")

# ── Dynamic commodity/spread table ────────────────────────────────────────────
from src.config import load_spreads_config, get_commodity_names, get_spreads_for_commodity

config      = load_spreads_config()
commodities = get_commodity_names(config)

cols = st.columns(3)
for i, comm in enumerate(commodities):
    spreads = get_spreads_for_commodity(config, comm)
    spread_list = ", ".join(s["name"] for s in spreads)
    with cols[i % 3]:
        st.markdown(f"**{comm}**")
        st.caption(spread_list)

st.markdown("---")
st.caption("Data source: Yahoo Finance  |  Refresh: hourly  |  For internal use only.")
