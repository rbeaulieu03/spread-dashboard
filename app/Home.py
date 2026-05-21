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
    page_title  = "Trader Insight Dashboard",
    page_icon   = "📊",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📊 Trader Insight Dashboard")
st.markdown("---")

# ── Description ───────────────────────────────────────────────────────────────
st.markdown("""
### Welcome

This dashboard shows **trader insights** for key commodity futures markets.

Use it to see different data points to do with commodity derivatives and fundamentals.

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
st.caption("Data source: DTN ProphetX (Bloomberg integration planned)  |  For internal use only.")