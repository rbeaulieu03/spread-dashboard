"""
3_COT_Dashboard.py
------------------
CFTC Disaggregated Commitments of Traders dashboard.

Three tabs:
  📊 Snapshot    — Cross-commodity positioning table with percentile ranks.
  📈 Deep Dive   — Single-commodity dual-axis chart (price + MM net position)
                   plus gross long/short breakdown and commercial positioning.
  🔄 Flow Monitor — Week-over-week flow ranking across all commodities.
  🔵 Trader Positioning — Scatter: # of contracts vs # of traders, date gradient.

Data is fetched automatically from the CFTC public website — no manual
Excel export required. Cache refreshes every 6 hours.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date

from src.providers.cot import (
    fetch_cot_data,
    get_commodity_timeseries,
    get_snapshot,
    fetch_continuous_price,
    COT_COMMODITIES,
)

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "COT Dashboard",
    page_icon  = "🌾",
    layout     = "wide",
)

# ── Dark theme constants ──────────────────────────────────────────────────────
_BG         = "#000000"
_PLOT_BG    = "#000000"
_GRID       = "#1A1A1A"
_LINE       = "#333333"
_FONT_COLOR = "#BBBBBB"
_TICK_COLOR = "#AAAAAA"
_LEGEND_BG  = "rgba(0,0,0,0.75)"
_HOVER_BG   = "rgba(0,0,0,0.85)"

_MM_COLOR    = "#00FFFF"
_PROD_COLOR  = "#FF8C00"
_PRICE_COLOR = "#FFFFFF"
_LONG_COLOR  = "#4CAF7D"
_SHORT_COLOR = "#DC143C"

# NOTE: hovermode and margin are intentionally excluded from _LAYOUT_BASE
# so each chart can set its own without keyword conflicts.
_LAYOUT_BASE = dict(
    paper_bgcolor = _BG,
    plot_bgcolor  = _PLOT_BG,
    font          = dict(color=_FONT_COLOR, size=11, family="Arial"),
    legend        = dict(
        x=1.01, y=1.0, xanchor="left", yanchor="top",
        bgcolor=_LEGEND_BG, bordercolor=_LINE, borderwidth=1,
        font=dict(size=12, color="#CCCCCC"),
    ),
    hoverlabel = dict(bgcolor=_HOVER_BG, bordercolor="#444444", font=dict(size=11, color="#FFFFFF")),
)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    st.divider()

    lookback_years = st.selectbox(
        "Data Lookback",
        options     = [3, 5, 7],
        index       = 1,
        format_func = lambda x: f"{x} years",
    )

    pct_window = st.selectbox(
        "Percentile Window",
        options     = [1, 3, 5],
        index       = 1,
        format_func = lambda x: f"{x} yr rolling",
    )

    categories = ["All"] + sorted({v["category"] for v in COT_COMMODITIES.values()})
    cat_filter = st.selectbox("Category Filter", options=categories)

    st.divider()
    st.caption("Source: CFTC Disaggregated Futures-Only Report")
    st.caption("Released: Fridays 3:30 PM ET (as of prior Tuesday)")
    st.caption("Auto-refreshes every 6 hours — no manual export needed.")


# ── Load COT data ─────────────────────────────────────────────────────────────
with st.spinner("Fetching CFTC COT data…"):
    cot_df, cot_status = fetch_cot_data(lookback_years=lookback_years)

st.title("🌾 COT Dashboard — Disaggregated Futures")

if cot_df.empty:
    st.error(f"Could not load COT data. Detail: {cot_status}")
    st.stop()

latest_date = cot_df["Report_Date_as_YYYY-MM-DD"].max()
st.caption(f"**Data as of: {latest_date.strftime('%A, %B %d, %Y')}**  (CFTC Tuesday snapshot)")
st.divider()

filtered_keys = [
    k for k, v in COT_COMMODITIES.items()
    if cat_filter == "All" or v["category"] == cat_filter
]


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_snap, tab_deep, tab_flow, tab_scatter = st.tabs([
    "📊 Snapshot", "📈 Deep Dive", "🔄 Flow Monitor", "🔵 Trader Positioning"
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
with tab_snap:
    st.subheader("Cross-Commodity Positioning Snapshot")
    st.markdown(
        "Managed Money net positioning for each commodity. "
        "**Percentile** is computed over a rolling window vs. the selected lookback. "
        "🟢 ≥ 90th or 🔴 ≤ 10th percentile flags positioning extremes."
    )

    snap_df = get_snapshot(cot_df, pct_window_yrs=pct_window)

    if snap_df.empty:
        st.warning("No snapshot data available.")
    else:
        snap_filtered = snap_df[snap_df["Commodity"].isin(
            [COT_COMMODITIES[k]["display"] for k in filtered_keys]
        )].copy()

        n_extreme_long  = (snap_filtered["MM_Percentile"] >= 90).sum()
        n_extreme_short = (snap_filtered["MM_Percentile"] <= 10).sum()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Commodities Shown", len(snap_filtered))
        m2.metric("Extreme Long (≥90th)", int(n_extreme_long))
        m3.metric("Extreme Short (≤10th)", int(n_extreme_short))
        m4.metric("Percentile Window", f"{pct_window} yr")

        st.divider()

        display_cols = {
            "Commodity":           "Commodity",
            "Category":            "Category",
            "As_Of":               "As Of",
            "MM_Net":              "MM Net (contracts)",
            "MM_Net_WoW":          "WoW Change",
            "MM_Pct_OI":           "MM % of OI",
            "MM_Percentile":       f"Percentile ({pct_window}yr)",
            "Prod_Net":            "Commercial Net",
            "Open_Interest":       "Open Interest",
            "OI_AllTime_Max":      "OI All-Time High",
            "OI_AllTime_Max_Date": "ATH Date",
            "OI_AllTime_Min":      "OI All-Time Low",
            "OI_AllTime_Min_Date": "ATL Date",
        }
        table = snap_filtered[list(display_cols.keys())].rename(columns=display_cols).copy()

        def _color_row(row):
            pct = row.get(f"Percentile ({pct_window}yr)", None)
            if pct is None:
                return [""] * len(row)
            if pct >= 90:
                bg = "background-color: #0d2b0d"
            elif pct >= 75:
                bg = "background-color: #0a200a"
            elif pct <= 10:
                bg = "background-color: #2b0d0d"
            elif pct <= 25:
                bg = "background-color: #200a0a"
            else:
                bg = ""
            return [bg] * len(row)

        def _fmt_int(val):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return "—"
            return f"{int(val):,}"

        styled = table.style.apply(_color_row, axis=1).format(
            {
                "MM Net (contracts)":           _fmt_int,
                "WoW Change":                   _fmt_int,
                f"Percentile ({pct_window}yr)": lambda v: f"{int(v)}th" if pd.notna(v) else "—",
                "MM % of OI":                   lambda v: f"{v:.1f}%" if pd.notna(v) else "—",
                "Commercial Net":               _fmt_int,
                "Open Interest":                _fmt_int,
                "OI All-Time High":             _fmt_int,
                "OI All-Time Low":              _fmt_int,
            },
            na_rep="—",
        )

        st.dataframe(styled, use_container_width=True, hide_index=True, height=420)
        st.caption(
            "🟢 ≥90th = historically extreme long  |  🔴 ≤10th = historically extreme short  "
            "|  WoW Change = contracts vs prior week"
        )
        st.divider()
        st.download_button(
            label     = "⬇️ Download Snapshot as CSV",
            data      = table.to_csv(index=False),
            file_name = f"cot_snapshot_{latest_date.date()}.csv",
            mime      = "text/csv",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — DEEP DIVE
# ─────────────────────────────────────────────────────────────────────────────
with tab_deep:
    st.subheader("Single-Commodity Deep Dive")

    dd_col1, dd_col2, dd_col3 = st.columns([2, 1, 1])
    with dd_col1:
        dd_commodity = st.selectbox(
            "Commodity",
            options     = filtered_keys,
            format_func = lambda k: COT_COMMODITIES[k]["display"],
            key         = "dd_commodity",
        )
    with dd_col2:
        dd_lookback = st.selectbox(
            "Chart Lookback",
            options     = [1, 2, 3, 5],
            index       = 1,
            format_func = lambda x: f"{x} year{'s' if x > 1 else ''}",
            key         = "dd_lookback",
        )
    with dd_col3:
        show_price      = st.toggle("Show Price Overlay", value=True, key="dd_price")
        show_commercial = st.toggle("Show Commercial",    value=True, key="dd_comm")

    meta = COT_COMMODITIES[dd_commodity]
    ts   = get_commodity_timeseries(cot_df, dd_commodity, pct_window)

    if ts.empty:
        st.warning(f"No COT time series data for {meta['display']}.")
    else:
        cutoff  = pd.Timestamp(date.today()) - pd.DateOffset(years=dd_lookback)
        ts_plot = ts[ts.index >= cutoff]

        latest = ts.iloc[-1]
        s1, s2, s3, s4 = st.columns(4)
        s1.metric(
            f"MM Net  ({ts.index[-1].strftime('%b %d')})",
            f"{int(latest['MM_Net']):,}" if pd.notna(latest.get("MM_Net")) else "—",
        )
        s2.metric(
            "WoW Change",
            f"{int(latest['MM_Net_WoW']):+,}" if pd.notna(latest.get("MM_Net_WoW")) else "—",
        )
        s3.metric(
            f"Percentile ({pct_window}yr)",
            f"{int(latest['MM_Percentile'])}th" if pd.notna(latest.get("MM_Percentile")) else "—",
        )
        s4.metric(
            "MM % of OI",
            f"{latest['MM_Pct_OI']:.1f}%" if pd.notna(latest.get("MM_Pct_OI")) else "—",
        )

        # ── Chart 1: Price + MM Net ───────────────────────────────────────
        st.markdown(f"##### {meta['display']} — Price vs. Managed Money Net Position")

        n_rows      = 2 if show_commercial else 1
        row_heights = [0.6, 0.4] if show_commercial else [1.0]

        if show_price:
            price_series, price_status = fetch_continuous_price(meta["yahoo_continuous"])
            price_plot = price_series[price_series.index >= cutoff] if not price_series.empty else pd.Series(dtype=float)
        else:
            price_plot   = pd.Series(dtype=float)
            price_status = "Price overlay disabled."

        specs = [[{"secondary_y": show_price}]] + ([[{"secondary_y": False}]] if show_commercial else [])
        fig1  = make_subplots(
            rows=n_rows, cols=1,
            shared_xaxes     = True,
            row_heights      = row_heights,
            specs            = specs,
            vertical_spacing = 0.06,
        )

        mm_net     = ts_plot["MM_Net"].dropna()
        bar_colors = [_LONG_COLOR if v >= 0 else _SHORT_COLOR for v in mm_net.values]
        fig1.add_trace(
            go.Bar(
                x             = mm_net.index,
                y             = mm_net.values,
                name          = "MM Net Position",
                marker_color  = bar_colors,
                opacity       = 0.75,
                hovertemplate = "<b>MM Net</b>: %{y:,.0f}<extra></extra>",
            ),
            row=1, col=1, secondary_y=False,
        )

        if show_price and not price_plot.empty:
            fig1.add_trace(
                go.Scatter(
                    x             = price_plot.index,
                    y             = price_plot.values,
                    name          = f"{meta['display']} Price ({meta['unit']})",
                    mode          = "lines",
                    line          = dict(color=_PRICE_COLOR, width=1.5),
                    hovertemplate = "<b>Price</b>: %{y:.2f}<extra></extra>",
                ),
                row=1, col=1, secondary_y=True,
            )

        if show_commercial and n_rows == 2:
            prod_net    = ts_plot["Prod_Net"].dropna()
            prod_colors = [_SHORT_COLOR if v >= 0 else _LONG_COLOR for v in prod_net.values]
            fig1.add_trace(
                go.Bar(
                    x             = prod_net.index,
                    y             = prod_net.values,
                    name          = "Commercial Net",
                    marker_color  = prod_colors,
                    opacity       = 0.75,
                    hovertemplate = "<b>Commercial Net</b>: %{y:,.0f}<extra></extra>",
                ),
                row=2, col=1,
            )

        fig1.update_layout(
            **_LAYOUT_BASE,
            hovermode  = "x unified",
            height     = 560 if show_commercial else 420,
            margin     = dict(l=70, r=150, t=55, b=70),
            barmode    = "relative",
            showlegend = True,
            title      = dict(
                text = f"{meta['display']} — Managed Money Positioning",
                font = dict(size=14, color="#FFFFFF", family="Arial"),
                x=0.5, y=0.98,
            ),
        )
        fig1.update_xaxes(gridcolor=_GRID, linecolor=_LINE, tickfont=dict(color=_TICK_COLOR))
        fig1.update_yaxes(
            title_text    = "Net Contracts",
            title_font    = dict(size=12, color=_TICK_COLOR),
            tickfont      = dict(size=11, color=_TICK_COLOR),
            gridcolor     = _GRID,
            linecolor     = _LINE,
            zerolinecolor = "#2A2A2A",
            secondary_y   = False,
            row=1, col=1,
        )
        if show_price:
            fig1.update_yaxes(
                title_text  = f"Price ({meta['unit']})",
                title_font  = dict(size=12, color=_TICK_COLOR),
                tickfont    = dict(size=11, color=_TICK_COLOR),
                showgrid    = False,
                secondary_y = True,
                row=1, col=1,
            )
        if show_commercial and n_rows == 2:
            fig1.update_yaxes(
                title_text    = "Commercial Net",
                title_font    = dict(size=12, color=_TICK_COLOR),
                tickfont      = dict(size=11, color=_TICK_COLOR),
                gridcolor     = _GRID,
                linecolor     = _LINE,
                zerolinecolor = "#2A2A2A",
                row=2, col=1,
            )

        st.plotly_chart(fig1, use_container_width=True)

        # ── Chart 2: Gross Longs vs Shorts ────────────────────────────────
        st.markdown(f"##### {meta['display']} — MM Gross Longs vs. Shorts")
        st.caption("Net position can be misleading when both sides grow simultaneously.")

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x             = ts_plot.index,
            y             = ts_plot["MM_Long"].values,
            name          = "MM Gross Longs",
            mode          = "lines",
            line          = dict(color=_LONG_COLOR, width=1.8),
            fill          = "tozeroy",
            fillcolor     = "rgba(76,175,125,0.15)",
            hovertemplate = "<b>MM Longs</b>: %{y:,.0f}<extra></extra>",
        ))
        fig2.add_trace(go.Scatter(
            x             = ts_plot.index,
            y             = ts_plot["MM_Short"].values,
            name          = "MM Gross Shorts",
            mode          = "lines",
            line          = dict(color=_SHORT_COLOR, width=1.8),
            fill          = "tozeroy",
            fillcolor     = "rgba(220,20,60,0.15)",
            hovertemplate = "<b>MM Shorts</b>: %{y:,.0f}<extra></extra>",
        ))
        fig2.update_layout(
            **_LAYOUT_BASE,
            hovermode = "x unified",
            height    = 420,
            margin    = dict(l=70, r=150, t=55, b=70),
            title     = dict(
                text = f"{meta['display']} — Managed Money Gross Positions",
                font = dict(size=14, color="#FFFFFF", family="Arial"),
                x=0.5, y=0.98,
            ),
            yaxis = dict(
                title     = dict(text="Contracts (gross)", font=dict(size=13, color=_TICK_COLOR)),
                tickfont  = dict(size=11, color=_TICK_COLOR),
                gridcolor = _GRID,
                linecolor = _LINE,
                zeroline  = True,
                zerolinecolor = "#2A2A2A",
            ),
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.divider()
        st.download_button(
            label     = f"⬇️ Download {meta['display']} COT history as CSV",
            data      = ts.to_csv(),
            file_name = f"cot_{dd_commodity.replace(' ','_').lower()}_{date.today()}.csv",
            mime      = "text/csv",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — FLOW MONITOR
# ─────────────────────────────────────────────────────────────────────────────
with tab_flow:
    st.subheader("Week-over-Week Flow Monitor")
    st.markdown(
        "Ranked by **magnitude of change** in Managed Money net position. "
        "Flags zero-crossings (net long ↔ short flips)."
    )

    flow_rows = []
    for key in filtered_keys:
        meta = COT_COMMODITIES[key]
        ts   = get_commodity_timeseries(cot_df, key, pct_window)
        if ts.empty or "MM_Net_WoW" not in ts.columns:
            continue

        last    = ts.iloc[-1]
        prev    = ts.iloc[-2] if len(ts) >= 2 else None
        wow     = last.get("MM_Net_WoW", np.nan)
        mm_net  = last.get("MM_Net",     np.nan)
        mm_prev = prev["MM_Net"] if prev is not None else np.nan

        crossed = (
            pd.notna(mm_net) and pd.notna(mm_prev) and
            ((mm_prev >= 0 and mm_net < 0) or (mm_prev < 0 and mm_net >= 0))
        )

        flow_rows.append({
            "Commodity":     meta["display"],
            "Category":      meta["category"],
            "As_Of":         ts.index[-1].date(),
            "MM_Net":        int(mm_net)  if pd.notna(mm_net) else None,
            "MM_Net_WoW":    int(wow)     if pd.notna(wow)    else None,
            "MM_Abs_WoW":    abs(wow)     if pd.notna(wow)    else 0,
            "MM_Percentile": int(last["MM_Percentile"]) if pd.notna(last.get("MM_Percentile")) else None,
            "Zero_Cross":    "⚡ FLIP" if crossed else "",
        })

    if not flow_rows:
        st.warning("No flow data available.")
    else:
        flow_df = pd.DataFrame(flow_rows).sort_values("MM_Abs_WoW", ascending=False)

        flow_display = flow_df[[
            "Commodity", "Category", "As_Of",
            "MM_Net", "MM_Net_WoW", "MM_Percentile", "Zero_Cross"
        ]].rename(columns={
            "MM_Net":        "MM Net",
            "MM_Net_WoW":    "WoW Change",
            "MM_Percentile": f"Percentile ({pct_window}yr)",
            "Zero_Cross":    "Signal",
        })

        def _color_flow(row):
            wow = row.get("WoW Change", None)
            if wow is None or (isinstance(wow, float) and np.isnan(wow)):
                return [""] * len(row)
            if wow >= 20_000:
                bg = "background-color: #0d2b0d"
            elif wow >= 10_000:
                bg = "background-color: #0a1a0a"
            elif wow <= -20_000:
                bg = "background-color: #2b0d0d"
            elif wow <= -10_000:
                bg = "background-color: #1a0a0a"
            else:
                bg = ""
            return [bg] * len(row)

        styled_flow = flow_display.style.apply(_color_flow, axis=1).format(
            {
                "MM Net":                       lambda v: f"{int(v):,}"  if pd.notna(v) else "—",
                "WoW Change":                   lambda v: f"{int(v):+,}" if pd.notna(v) else "—",
                f"Percentile ({pct_window}yr)": lambda v: f"{int(v)}th"  if pd.notna(v) else "—",
            },
            na_rep="—",
        )

        st.dataframe(styled_flow, use_container_width=True, hide_index=True, height=420)
        st.caption(
            "🟢 Large buying (≥20k contracts)  |  🔴 Large selling (≥20k)  "
            "|  ⚡ FLIP = MM crossed from net long to short or vice versa"
        )

        # WoW bar chart
        st.markdown("##### WoW Change — Visual Ranking")
        chart_df  = flow_df.dropna(subset=["MM_Net_WoW"]).sort_values("MM_Net_WoW")
        bar_cols  = [_LONG_COLOR if v >= 0 else _SHORT_COLOR for v in chart_df["MM_Net_WoW"]]

        fig_flow = go.Figure(go.Bar(
            x             = chart_df["MM_Net_WoW"].values,
            y             = chart_df["Commodity"].values,
            orientation   = "h",
            marker_color  = bar_cols,
            opacity       = 0.85,
            hovertemplate = "<b>%{y}</b>: %{x:+,.0f} contracts<extra></extra>",
        ))
        fig_flow.update_layout(
            **_LAYOUT_BASE,
            hovermode  = "closest",
            height     = max(300, len(chart_df) * 42),
            margin     = dict(l=130, r=60, t=40, b=50),
            title      = dict(
                text = f"Week-over-Week Change in MM Net Position ({latest_date.strftime('%b %d, %Y')})",
                font = dict(size=13, color="#FFFFFF", family="Arial"),
                x=0.5,
            ),
            xaxis = dict(
                title     = dict(text="Contracts", font=dict(size=12, color=_TICK_COLOR)),
                tickfont  = dict(size=11, color=_TICK_COLOR),
                gridcolor = _GRID,
                linecolor = _LINE,
                zeroline  = True,
                zerolinecolor = "#444444",
            ),
            yaxis      = dict(tickfont=dict(size=12, color="#DDDDDD"), gridcolor=_GRID),
            showlegend = False,
        )
        st.plotly_chart(fig_flow, use_container_width=True)

        st.divider()
        st.download_button(
            label     = "⬇️ Download Flow Monitor as CSV",
            data      = flow_display.to_csv(index=False),
            file_name = f"cot_flow_{latest_date.date()}.csv",
            mime      = "text/csv",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — TRADER POSITIONING SCATTER
# ─────────────────────────────────────────────────────────────────────────────
with tab_scatter:
    st.subheader("Trader Positioning — Number of Traders vs. Net Position")
    st.markdown(
        "Each dot is one weekly COT report. "
        "**X-axis** = Managed Money net position (thousands of contracts). "
        "**Y-axis** = number of MM traders (long + short). "
        "Color runs from **oldest** (dark) → **newest** (cyan)."
    )

    sc_col1, sc_col2, sc_col3 = st.columns([2, 1, 1])
    with sc_col1:
        sc_commodity = st.selectbox(
            "Commodity",
            options     = filtered_keys,
            format_func = lambda k: COT_COMMODITIES[k]["display"],
            key         = "sc_commodity",
        )
    with sc_col2:
        sc_lookback = st.selectbox(
            "Lookback",
            options     = [1, 2, 3, 5],
            index       = 2,
            format_func = lambda x: f"{x} year{'s' if x > 1 else ''}",
            key         = "sc_lookback",
        )
    with sc_col3:
        trader_view = st.selectbox(
            "Traders (Y-axis)",
            options = ["Total (Long + Short)", "Long Only", "Short Only"],
            key     = "sc_trader_view",
        )

    sc_meta = COT_COMMODITIES[sc_commodity]
    sc_ts   = get_commodity_timeseries(cot_df, sc_commodity, pct_window)

    if sc_ts.empty:
        st.warning(f"No COT time series data for {sc_meta['display']}.")
    else:
        sc_cutoff = pd.Timestamp(date.today()) - pd.DateOffset(years=sc_lookback)
        sc_plot   = sc_ts[sc_ts.index >= sc_cutoff].copy()

        y_col = {
            "Total (Long + Short)": "Traders_MM_Total",
            "Long Only":            "Traders_MM_Long",
            "Short Only":           "Traders_MM_Short",
        }[trader_view]
        y_label = {
            "Total (Long + Short)": "Total MM Traders (Long + Short)",
            "Long Only":            "MM Long Traders",
            "Short Only":           "MM Short Traders",
        }[trader_view]

        sc_clean = sc_plot[["MM_Net", y_col]].dropna()

        if sc_clean.empty:
            st.warning("Not enough data to plot. Trader count columns may be missing from the CFTC file.")
        else:
            x_vals   = (sc_clean["MM_Net"] / 1000).values
            y_vals   = sc_clean[y_col].values
            dates    = sc_clean.index

            date_num  = (dates - dates.min()).days.astype(float)
            date_norm = date_num / date_num.max() if date_num.max() > 0 else date_num

            hover_text = [
                f"<b>{d.strftime('%b %d, %Y')}</b><br>"
                f"MM Net: {x:+.1f}k contracts<br>"
                f"{y_label}: {int(y)}"
                for d, x, y in zip(dates, x_vals, y_vals)
            ]

            latest_x = x_vals[-1]
            latest_y = y_vals[-1]
            latest_d = dates[-1]

            fig_sc = go.Figure()

            fig_sc.add_trace(go.Scatter(
                x    = x_vals[:-1],
                y    = y_vals[:-1],
                mode = "markers",
                name = "Historical",
                text = hover_text[:-1],
                hovertemplate = "%{text}<extra></extra>",
                marker = dict(
                    size       = 7,
                    color      = date_norm[:-1],
                    colorscale = [
                        [0.0,  "#1a3a1a"],
                        [0.4,  "#4169E1"],
                        [0.7,  "#9370DB"],
                        [0.85, "#FF8C00"],
                        [1.0,  "#00FFFF"],
                    ],
                    showscale  = True,
                    colorbar   = dict(
                        title      = dict(text="Older → Newer", font=dict(color=_TICK_COLOR, size=11)),
                        tickvals   = [0, 1],
                        ticktext   = [dates.min().strftime("%b '%y"), dates.max().strftime("%b '%y")],
                        tickfont   = dict(color=_TICK_COLOR, size=10),
                        outlinecolor = _LINE,
                        thickness  = 14,
                        len        = 0.6,
                    ),
                    opacity = 0.85,
                    line    = dict(width=0),
                ),
            ))

            fig_sc.add_trace(go.Scatter(
                x            = [latest_x],
                y            = [latest_y],
                mode         = "markers+text",
                name         = f"Latest ({latest_d.strftime('%b %d, %Y')})",
                text         = [f"  {latest_d.strftime('%b %d')}"],
                textposition = "middle right",
                textfont     = dict(color="#00FFFF", size=11),
                hovertemplate = hover_text[-1] + "<extra></extra>",
                marker = dict(
                    size   = 14,
                    color  = "#00FFFF",
                    symbol = "star",
                    line   = dict(color="#FFFFFF", width=1),
                ),
            ))

            fig_sc.add_vline(
                x                   = 0,
                line_width          = 1,
                line_dash           = "dash",
                line_color          = "#444444",
                annotation_text     = "Net Flat",
                annotation_position = "top",
                annotation_font     = dict(color="#666666", size=10),
            )

            fig_sc.update_layout(
                **_LAYOUT_BASE,
                hovermode = "closest",
                height    = 560,
                margin    = dict(l=70, r=160, t=60, b=70),
                title     = dict(
                    text = f"{sc_meta['display']} — Traders vs. Net Position ({sc_lookback}yr)",
                    font = dict(size=14, color="#FFFFFF", family="Arial"),
                    x=0.5, y=0.98,
                ),
                xaxis = dict(
                    title      = dict(text="MM Net Position (thousands of contracts)", font=dict(size=13, color=_TICK_COLOR)),
                    tickfont   = dict(size=11, color=_TICK_COLOR),
                    gridcolor  = _GRID,
                    linecolor  = _LINE,
                    zeroline   = True,
                    zerolinecolor = "#2A2A2A",
                    ticksuffix = "k",
                ),
                yaxis = dict(
                    title    = dict(text=y_label, font=dict(size=13, color=_TICK_COLOR)),
                    tickfont = dict(size=11, color=_TICK_COLOR),
                    gridcolor = _GRID,
                    linecolor = _LINE,
                    zeroline  = False,
                ),
            )

            st.plotly_chart(fig_sc, use_container_width=True)

            q1, q2, q3 = st.columns(3)
            q1.metric(
                f"Latest Net ({latest_d.strftime('%b %d')})",
                f"{latest_x:+.1f}k contracts",
            )
            q2.metric(
                f"Latest {y_label.split()[0]} Traders",
                f"{int(latest_y):,}",
            )
            trader_pct = round((sc_clean[y_col] < latest_y).sum() / len(sc_clean) * 100)
            q3.metric(
                "Trader Count Percentile",
                f"{trader_pct}th",
                help=f"Where today's trader count ranks vs the {sc_lookback}-year window.",
            )

            st.divider()
            st.download_button(
                label     = f"⬇️ Download {sc_meta['display']} scatter data as CSV",
                data      = sc_clean.assign(MM_Net_Thousands=x_vals).to_csv(),
                file_name = f"cot_scatter_{sc_commodity.replace(' ','_').lower()}_{date.today()}.csv",
                mime      = "text/csv",
            )


# ─────────────────────────────────────────────────────────────────────────────
# TROUBLESHOOT EXPANDER
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("🔍 Data fetch details (expand to troubleshoot)"):
    ok_icon = "✅" if not cot_df.empty else "❌"
    st.markdown(f"**{ok_icon} CFTC COT Data**")
    st.caption(cot_status)

    if not cot_df.empty:
        st.caption(f"Total rows loaded: {len(cot_df):,}")
        st.caption(f"Commodities matched: {cot_df['commodity_key'].nunique()} of {len(COT_COMMODITIES)}")

        missing = [
            f"{v['display']} ({v['cftc_name']})"
            for k, v in COT_COMMODITIES.items()
            if k not in cot_df["commodity_key"].unique()
        ]
        if missing:
            st.warning(
                "The following commodities were not found in the CFTC file. "
                "Verify the 'cftc_name' strings in `src/providers/cot.py`:\n\n"
                + "\n".join(f"- {m}" for m in missing)
            )