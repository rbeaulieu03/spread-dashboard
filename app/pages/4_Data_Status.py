"""
4_Data_Status.py
----------------
Unified data status and diagnostics page covering all three data sources:

  1. ProphetX Excel   — per-commodity contract files in data/prophetx/
  2. Bloomberg Excel  — implied volatility files in data/bloomberg/
  3. CFTC COT         — auto-fetched from CFTC public website

Run this page any time a chart shows no data or unexpected gaps.
Each section tells you exactly what is loaded, what is missing,
and what to do to fix it.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import date

from src.config            import load_spreads_config, get_commodity_names, get_commodity_info, get_spreads_for_commodity
from src.providers.excel   import load_commodity_file, build_prophetx_symbol
from src.providers.iv      import load_iv_data, get_iv_commodities, get_iv_label
from src.providers.cot     import fetch_cot_data, get_commodity_timeseries, COT_COMMODITIES

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "Data Status",
    page_icon  = "🔎",
    layout     = "wide",
)

st.title("🔎 Data Status & Diagnostics")
st.markdown(
    "Check the health of every data source powering the dashboard. "
    "Expand each section for full detail. "
    "**Green = OK · Red = action required · Yellow = partial / warning.**"
)
st.divider()

# ── Shared helpers ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_config():
    return load_spreads_config()

def _fmt_int(v):
    return f"{int(v):,}" if pd.notna(v) else "—"

def _color_status(row):
    s = row.get("Status", "")
    if "✅" in str(s):
        return ["background-color: #0d2b0d"] * len(row)
    if "❌" in str(s):
        return ["background-color: #2b0d0d"] * len(row)
    if "⚠️" in str(s):
        return ["background-color: #2b2200"] * len(row)
    return [""] * len(row)

current_year = date.today().year
season_years = list(range(current_year - 5, current_year + 1))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — ProphetX Excel
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("📂 ProphetX Excel Files  —  Spread Seasonality Data", expanded=True):

    st.markdown(
        "Checks every `data/prophetx/*.xlsx` file and confirms that each "
        "contract symbol column required by `spreads.yaml` is present."
    )

    config      = load_config()
    commodities = get_commodity_names(config)

    px_filter = st.selectbox(
        "Filter by Commodity",
        options = ["All"] + commodities,
        key     = "px_filter",
    )
    check_list = commodities if px_filter == "All" else [px_filter]

    if st.button("▶️ Run ProphetX Check", type="primary", key="run_px"):
        for commodity in check_list:
            comm_info = get_commodity_info(config, commodity)
            spreads   = get_spreads_for_commodity(config, commodity)
            prefix    = comm_info.get("prophetx_prefix", "")

            st.subheader(commodity)

            all_legs     = [leg for s in spreads for leg in s["legs"]]
            is_intercmdy = any("commodity" in leg for leg in all_legs)

            if is_intercmdy:
                source_commodities = list({leg.get("commodity", commodity) for leg in all_legs})
                all_ok   = True
                multi_data = {}
                for src in sorted(source_commodities):
                    src_data, src_msg = load_commodity_file(src)
                    if src_data:
                        st.success(f"✅ {src_msg}")
                    else:
                        st.error(f"❌ {src_msg}")
                        all_ok = False
                    multi_data[src] = src_data
                if not all_ok:
                    st.divider()
                    continue
            else:
                contract_data, load_msg = load_commodity_file(commodity)
                if not contract_data:
                    st.error(f"❌ {load_msg}")
                    st.divider()
                    continue
                st.success(f"✅ {load_msg}")
                multi_data = {commodity: contract_data}

            # Check each spread leg for each season year
            for spread_def in spreads:
                st.markdown(f"**{spread_def['name']}**")
                rows = []

                for year in season_years:
                    for leg_i, leg in enumerate(spread_def["legs"]):
                        leg_commodity = leg.get("commodity", commodity)

                        if leg.get("type") == "continuous":
                            symbol   = leg["symbol"]
                            leg_data = multi_data.get(leg_commodity, {})
                            series   = leg_data.get(symbol)
                            label    = f"Index ({leg_commodity})"
                            yr_label = "—"
                        else:
                            leg_year  = year + leg.get("year_offset", 0)
                            if leg_commodity != commodity:
                                leg_cfg    = get_commodity_info(config, leg_commodity)
                                leg_prefix = leg_cfg.get("prophetx_prefix", "") if leg_cfg else ""
                            else:
                                leg_prefix = prefix
                            symbol   = build_prophetx_symbol(leg_prefix, leg["month"], leg_year)
                            leg_data = multi_data.get(leg_commodity, {})
                            series   = leg_data.get(symbol)
                            label    = f"Leg {leg_i + 1} ({leg_commodity})"
                            yr_label = str(year)

                        if series is not None:
                            date_range = f"{series.index[0].date()} → {series.index[-1].date()}"
                            rows.append({
                                "Season Year": yr_label,
                                "Leg":         label,
                                "Symbol":      symbol,
                                "Status":      "✅ OK",
                                "Days":        len(series),
                                "Date Range":  date_range,
                            })
                        else:
                            rows.append({
                                "Season Year": yr_label,
                                "Leg":         label,
                                "Symbol":      symbol,
                                "Status":      "❌ MISSING",
                                "Days":        0,
                                "Date Range":  f"Add {symbol} column to the Excel file",
                            })

                df = pd.DataFrame(rows)
                st.dataframe(
                    df.style.apply(_color_status, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )

            st.divider()

    else:
        st.info("Click **▶️ Run ProphetX Check** to validate all ProphetX files.")

    with st.container():
        st.markdown("""
        **How to fix a ❌ MISSING symbol:**
        1. Open Excel with the ProphetX Add-In
        2. Add the missing contract symbol as a new column to your existing pull
        3. Paste as values, save the file
        4. Replace the file in `data/prophetx/` and restart the app

        **To add more years of history:** add older contract columns and restart.
        The app detects new columns automatically.
        """)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Bloomberg IV Excel
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("📊 Bloomberg Excel Files  —  Implied Volatility Data", expanded=True):

    st.markdown(
        "Checks every `data/bloomberg/*_iv.xlsx` file configured in "
        "`src/providers/iv.py`. Validates years found, date coverage, "
        "and forward-fill gap size."
    )

    iv_commodities = get_iv_commodities()

    if st.button("▶️ Run Bloomberg IV Check", type="primary", key="run_iv"):
        summary_rows = []

        for comm in iv_commodities:
            pivot, status_msg = load_iv_data(comm)
            label = get_iv_label(comm)

            if pivot.empty:
                summary_rows.append({
                    "Commodity":   comm,
                    "Label":       label,
                    "Status":      "❌ FAILED",
                    "Years Found": "—",
                    "Date Range":  "—",
                    "Detail":      status_msg,
                })
                continue

            year_cols = sorted([c for c in pivot.columns if isinstance(c, int)])

            # Check for large gaps (rows where ALL years are NaN = uncovered date)
            gap_rows = pivot[year_cols].isna().all(axis=1).sum()
            gap_warn = f"  ⚠️ {gap_rows} dates fully missing across all years" if gap_rows > 10 else ""

            summary_rows.append({
                "Commodity":   comm,
                "Label":       label,
                "Status":      "✅ OK" if not gap_warn else "⚠️ Partial",
                "Years Found": ", ".join(str(y) for y in year_cols),
                "Date Range":  "Jan-01 → Dec-31 (calendar year)",
                "Detail":      status_msg + gap_warn,
            })

        df_iv = pd.DataFrame(summary_rows)
        st.dataframe(
            df_iv.style.apply(_color_status, axis=1),
            use_container_width=True,
            hide_index=True,
        )

        # Per-commodity year coverage detail
        st.markdown("##### Year Coverage Detail")
        for comm in iv_commodities:
            pivot, _ = load_iv_data(comm)
            if pivot.empty:
                continue
            year_cols = sorted([c for c in pivot.columns if isinstance(c, int)])
            st.markdown(f"**{comm}**")
            year_rows = []
            for yr in year_cols:
                col_data  = pivot[yr].dropna()
                pct_cover = round(len(col_data) / 365 * 100, 1)
                year_rows.append({
                    "Year":          yr,
                    "Non-null Days": len(col_data),
                    "Coverage":      f"{pct_cover}%",
                    "First Value":   col_data.index[0]  if not col_data.empty else "—",
                    "Last Value":    col_data.index[-1] if not col_data.empty else "—",
                    "Status":        "✅ OK" if pct_cover >= 90 else ("⚠️ Partial" if pct_cover >= 50 else "❌ Sparse"),
                })
            df_yr = pd.DataFrame(year_rows)
            st.dataframe(
                df_yr.style.apply(_color_status, axis=1),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("Click **▶️ Run Bloomberg IV Check** to validate all IV files.")

    with st.container():
        st.markdown("""
        **How to fix a ❌ FAILED file:**
        1. Open the Bloomberg terminal
        2. Re-run your IV pull and paste-as-values into the correct `data/bloomberg/` file
        3. Save and restart the app

        **To add a new commodity:** add entries to `_IV_FILES` and `_IV_LABELS`
        in `src/providers/iv.py` and create the corresponding Excel file.
        """)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CFTC COT Auto-Fetch
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🌾 CFTC COT Data  —  Auto-Fetched from CFTC Website", expanded=True):

    st.markdown(
        "The COT data is downloaded automatically from the CFTC public website "
        "and cached for 6 hours. This section validates connectivity, commodity "
        "name matching, data freshness, and column completeness."
    )

    cot_lookback = st.selectbox(
        "Lookback window to check",
        options     = [3, 5, 7],
        index       = 1,
        format_func = lambda x: f"{x} years",
        key         = "cot_status_lookback",
    )

    if st.button("▶️ Run COT Check", type="primary", key="run_cot"):

        with st.spinner("Fetching COT data from CFTC…"):
            cot_df, cot_status_msg = fetch_cot_data(lookback_years=cot_lookback)

        # ── Top-level fetch result ─────────────────────────────────────────
        if cot_df.empty:
            st.error(f"❌ COT fetch failed entirely. Detail: {cot_status_msg}")
        else:
            st.success(f"✅ {cot_status_msg}")

            latest_date = cot_df["Report_Date_as_YYYY-MM-DD"].max()
            oldest_date = cot_df["Report_Date_as_YYYY-MM-DD"].min()
            days_since  = (pd.Timestamp(date.today()) - latest_date).days

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Latest Report Date",  latest_date.strftime("%b %d, %Y"))
            c2.metric("Oldest Report Date",  oldest_date.strftime("%b %d, %Y"))
            c3.metric("Days Since Last Pull", str(days_since),
                      delta="On time" if days_since <= 8 else "Overdue",
                      delta_color="normal" if days_since <= 8 else "inverse")
            c4.metric("Total Rows Loaded",   f"{len(cot_df):,}")

            if days_since > 8:
                st.warning(
                    f"⚠️ Latest data is {days_since} days old. "
                    "Expected a Friday release within the last 7 days. "
                    "Check your network connection or the CFTC website."
                )

            st.divider()

            # ── Commodity match table ──────────────────────────────────────
            st.markdown("##### Commodity Match Status")
            st.caption(
                "Each commodity in `COT_COMMODITIES` is matched against the "
                "`Market_and_Exchange_Names` column in the CFTC file. "
                "If a commodity shows ❌, the `cftc_name` string needs to be corrected."
            )

            matched_keys = cot_df["commodity_key"].dropna().unique()
            comm_rows    = []

            for key, meta in COT_COMMODITIES.items():
                if key not in matched_keys:
                    comm_rows.append({
                        "Commodity":       meta["display"],
                        "Category":        meta["category"],
                        "CFTC Name Used":  meta["cftc_name"],
                        "Status":          "❌ NOT MATCHED",
                        "Weeks of Data":   "—",
                        "Latest Date":     "—",
                        "Oldest Date":     "—",
                    })
                    continue

                ts = get_commodity_timeseries(cot_df, key)
                comm_rows.append({
                    "Commodity":      meta["display"],
                    "Category":       meta["category"],
                    "CFTC Name Used": meta["cftc_name"],
                    "Status":         "✅ OK",
                    "Weeks of Data":  len(ts),
                    "Latest Date":    ts.index[-1].strftime("%b %d, %Y") if not ts.empty else "—",
                    "Oldest Date":    ts.index[0].strftime("%b %d, %Y")  if not ts.empty else "—",
                })

            df_comm = pd.DataFrame(comm_rows)
            st.dataframe(
                df_comm.style.apply(_color_status, axis=1),
                use_container_width=True,
                hide_index=True,
            )

            # ── Column completeness ────────────────────────────────────────
            st.divider()
            st.markdown("##### Column Completeness")
            st.caption(
                "Checks that all expected CFTC columns are present in the downloaded file. "
                "Missing columns appear when the CFTC changes their file format."
            )

            expected_cols = [
                "Report_Date_as_YYYY-MM-DD",
                "Market_and_Exchange_Names",
                "Open_Interest_All",
                "M_Money_Positions_Long_All",
                "M_Money_Positions_Short_All",
                "M_Money_Positions_Spreading_All",
                "Prod_Merc_Positions_Long_All",
                "Prod_Merc_Positions_Short_All",
                "Traders_M_Money_Long_All",
                "Traders_M_Money_Short_All",
                "Traders_M_Money_Spread_All",
            ]

            col_rows = []
            for col in expected_cols:
                present  = col in cot_df.columns
                null_pct = round(cot_df[col].isna().mean() * 100, 1) if present else None
                col_rows.append({
                    "Column":       col,
                    "Status":       "✅ Present" if present else "❌ MISSING",
                    "Null %":       f"{null_pct}%" if null_pct is not None else "—",
                })

            # Also flag the Swap short double-underscore variant
            swap_v1 = "Swap__Positions_Short_All"
            swap_v2 = "Swap_Positions_Short_All"
            swap_found = swap_v1 if swap_v1 in cot_df.columns else (swap_v2 if swap_v2 in cot_df.columns else None)
            col_rows.append({
                "Column":  f"Swap Short ({swap_v1} or {swap_v2})",
                "Status":  f"✅ Found as: {swap_found}" if swap_found else "❌ MISSING",
                "Null %":  f"{round(cot_df[swap_found].isna().mean()*100,1)}%" if swap_found else "—",
            })

            df_cols = pd.DataFrame(col_rows)
            st.dataframe(
                df_cols.style.apply(_color_status, axis=1),
                use_container_width=True,
                hide_index=True,
            )

            # ── Data freshness per commodity ───────────────────────────────
            st.divider()
            st.markdown("##### Per-Commodity Data Freshness")

            fresh_rows = []
            for key, meta in COT_COMMODITIES.items():
                if key not in matched_keys:
                    continue
                ts = get_commodity_timeseries(cot_df, key)
                if ts.empty:
                    continue
                gap = (pd.Timestamp(date.today()) - ts.index[-1]).days
                fresh_rows.append({
                    "Commodity":    meta["display"],
                    "Latest Week":  ts.index[-1].strftime("%b %d, %Y"),
                    "Days Stale":   gap,
                    "Weeks Loaded": len(ts),
                    "Status":       "✅ Current" if gap <= 8 else "⚠️ Stale",
                })

            df_fresh = pd.DataFrame(fresh_rows)
            st.dataframe(
                df_fresh.style.apply(_color_status, axis=1),
                use_container_width=True,
                hide_index=True,
            )

    else:
        st.info("Click **▶️ Run COT Check** to validate the CFTC data fetch.")

    with st.container():
        st.markdown("""
        **If a commodity shows ❌ NOT MATCHED:**
        1. Download the current year's zip manually from:
           `https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip`
        2. Open the CSV and search the `Market_and_Exchange_Names` column
        3. Copy the exact string and paste it into the `cftc_name` field
           for that commodity in `src/providers/cot.py`

        **If the fetch is stale (> 8 days):**
        - Check your internet connection
        - The CFTC occasionally delays releases around holidays
        - Visit `https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm`
          to confirm the latest release date

        **Cache note:** COT data is cached for 6 hours. To force a refresh,
        restart the Streamlit app.
        """)