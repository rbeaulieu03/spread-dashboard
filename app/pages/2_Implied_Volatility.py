"""
3_Implied_Volatility.py
-----------------------
Implied volatility seasonality overlay chart page.

Traders can select a commodity, choose which years to overlay,
and toggle the average line and percentile band — same controls
as the Spread Seasonality page.

Data source: Bloomberg terminal exports stored in data/bloomberg/.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date

from src.providers.iv import load_iv_data, get_iv_commodities, get_iv_label

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "Implied Volatility",
    page_icon  = "📉",
    layout     = "wide",
)

# ── Color palette (matches spread seasonality page) ───────────────────────────
_YEAR_COLORS = [
    "#4CAF7D",   # green          — oldest
    "#4169E1",   # royal blue
    "#9370DB",   # medium purple
    "#DAA520",   # goldenrod
    "#FF8C00",   # dark orange
    "#DC143C",   # crimson red
]
_CURRENT_COLOR  = "#00FFFF"   # bright cyan — most recent year
_AVERAGE_COLOR  = "#FFFFFF"   # white dashed
_BAND_COLOR     = "rgba(255, 255, 255, 0.18)"


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    st.divider()

    commodities = get_iv_commodities()
    commodity   = st.selectbox("Commodity", commodities)

    # Year range — inferred from available data after load,
    # but provide defaults based on current year
    current_year    = date.today().year
    available_years = list(range(current_year - 5, current_year + 1))

    selected_years = st.multiselect(
        "Season Years",
        options = available_years,
        default = available_years,
        help    = "Select which years to display on the chart.",
    )

    st.divider()

    st.subheader("Display Options")
    show_average    = st.toggle("Show Average",          value=True)
    show_percentile = st.toggle("Show 10th–90th % Band", value=True)

    st.divider()
    st.caption("Data source: Bloomberg Terminal")
    st.caption("To update: paste new Bloomberg pull into the Excel file and push to GitHub.")


# ── Guard ─────────────────────────────────────────────────────────────────────
if not selected_years:
    st.warning("⚠️ Select at least one year in the sidebar.")
    st.stop()


# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner(f"Loading {commodity} implied volatility data…"):
    pivot, status_msg = load_iv_data(commodity)

chart_title = get_iv_label(commodity)
st.title(f"📉 {chart_title}")

# ── Error state ───────────────────────────────────────────────────────────────
if pivot.empty:
    st.error(
        f"No data could be loaded for {commodity} implied volatility. "
        f"Make sure `data/bloomberg/{commodity.lower()}_iv.xlsx` exists "
        f"and is formatted correctly."
    )
    st.info(f"Detail: {status_msg}")
    st.stop()

# ── Filter to selected years ──────────────────────────────────────────────────
year_cols     = sorted([c for c in pivot.columns if isinstance(c, int)])
selected_valid = [y for y in selected_years if y in year_cols]

if not selected_valid:
    st.warning(
        f"None of the selected years have data. "
        f"Available years in this file: {', '.join(str(y) for y in year_cols)}"
    )
    st.stop()

# ── Build chart ───────────────────────────────────────────────────────────────
highlight_year  = max(selected_valid)
x_labels        = pivot.index.tolist()

# Thin x-axis ticks to ~18 labels
step      = max(1, len(x_labels) // 18)
tick_vals = x_labels[::step]

# Color assignment
non_highlight = [y for y in selected_valid if y != highlight_year]
color_map     = {}
for i, yr in enumerate(non_highlight):
    color_map[yr] = _YEAR_COLORS[i % len(_YEAR_COLORS)]
if highlight_year in year_cols:
    color_map[highlight_year] = _CURRENT_COLOR

fig = go.Figure()

# 1. Percentile band
if show_percentile and "p10" in pivot.columns and "p90" in pivot.columns:
    p10 = pivot["p10"].tolist()
    p90 = pivot["p90"].tolist()
    fig.add_trace(go.Scatter(
        x         = x_labels + x_labels[::-1],
        y         = p90 + p10[::-1],
        fill      = "toself",
        fillcolor = _BAND_COLOR,
        line      = dict(color="rgba(0,0,0,0)"),
        hoverinfo = "skip",
        showlegend = True,
        name      = "10–90th %ile",
    ))

# 2. Historical year lines
for year in selected_valid:
    if year == highlight_year:
        continue
    series = pivot[year].dropna()
    if series.empty:
        continue
    fig.add_trace(go.Scatter(
        x    = series.index.tolist(),
        y    = series.values,
        mode = "lines",
        name = str(year),
        line = dict(color=color_map.get(year, "#888888"), width=1.2),
        hovertemplate = f"<b>{year}</b>: %{{y:.2f}}%<extra></extra>",
    ))

# 3. Average line
if show_average and "Average" in pivot.columns:
    avg = pivot["Average"].dropna()
    if not avg.empty:
        fig.add_trace(go.Scatter(
            x    = avg.index.tolist(),
            y    = avg.values,
            mode = "lines",
            name = "Average",
            line = dict(color=_AVERAGE_COLOR, width=1.8, dash="dash"),
            hovertemplate = "<b>Average</b>: %{y:.2f}%<extra></extra>",
        ))

# 4. Current/highlighted year on top
if highlight_year in year_cols:
    series = pivot[highlight_year].dropna()
    if not series.empty:
        fig.add_trace(go.Scatter(
            x    = series.index.tolist(),
            y    = series.values,
            mode = "lines",
            name = str(highlight_year),
            line = dict(color=_CURRENT_COLOR, width=2.8),
            hovertemplate = f"<b>{highlight_year}</b>: %{{y:.2f}}%<extra></extra>",
        ))

# 5. Layout
fig.update_layout(
    title = dict(
        text = chart_title,
        font = dict(size=14, color="#FFFFFF", family="Arial"),
        x    = 0.5,
        y    = 0.97,
    ),
    paper_bgcolor = "#000000",
    plot_bgcolor  = "#000000",
    font          = dict(color="#BBBBBB", size=11, family="Arial"),

    xaxis = dict(
        title         = dict(text="Date (MM-DD)", font=dict(size=14, color="#AAAAAA")),
        type          = "category",
        categoryorder = "array",
        categoryarray = x_labels,
        tickangle     = -45,
        tickvals      = tick_vals,
        ticktext      = tick_vals,
        tickfont      = dict(size=11, color="#AAAAAA"),
        gridcolor     = "#1A1A1A",
        gridwidth     = 1,
        linecolor     = "#333333",
        showline      = True,
    ),
    yaxis = dict(
        title         = dict(text="Implied Volatility (%)", font=dict(size=14, color="#AAAAAA")),
        tickfont      = dict(size=12, color="#AAAAAA"),
        ticksuffix    = "%",
        gridcolor     = "#1A1A1A",
        gridwidth     = 1,
        linecolor     = "#333333",
        showline      = True,
        zeroline      = False,
    ),
    legend = dict(
        x           = 1.01,
        y           = 1.0,
        xanchor     = "left",
        yanchor     = "top",
        bgcolor     = "rgba(0, 0, 0, 0.75)",
        bordercolor = "#333333",
        borderwidth = 1,
        font        = dict(size=12, color="#CCCCCC"),
    ),
    hovermode  = "x unified",
    hoverlabel = dict(
        bgcolor     = "rgba(0,0,0,0.85)",
        bordercolor = "#444444",
        font        = dict(size=11, color="#FFFFFF"),
    ),
    height = 580,
    margin = dict(l=70, r=140, t=60, b=90),
)

st.plotly_chart(fig, use_container_width=True)

# ── Quick stats ───────────────────────────────────────────────────────────────
if highlight_year in pivot.columns:
    hy_series = pivot[highlight_year].dropna()
    if not hy_series.empty:
        last_mmdd = hy_series.index[-1]
        last_val  = hy_series.iloc[-1]

        at_date = pivot.loc[last_mmdd, selected_valid].dropna() if last_mmdd in pivot.index else pd.Series(dtype=float)
        pctile  = None
        if len(at_date) > 1:
            rank   = int((at_date < last_val).sum())
            pctile = round(rank / len(at_date) * 100)

        avg_val = pivot.loc[last_mmdd, "Average"] if "Average" in pivot.columns and last_mmdd in pivot.index else None

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                label = f"{highlight_year} — latest IV  (as of {last_mmdd})",
                value = f"{last_val:.2f}%",
            )
        with col2:
            if pctile is not None:
                st.metric(
                    label = "Historical Percentile",
                    value = f"{pctile}th",
                    help  = "Where the current year's IV sits vs all other years at this point.",
                )
        with col3:
            if avg_val is not None and not pd.isna(avg_val):
                diff = last_val - avg_val
                st.metric(
                    label = "vs. Average",
                    value = f"{diff:+.2f}%",
                    help  = "Current year minus the historical average IV at this date.",
                )

# ── Download ──────────────────────────────────────────────────────────────────
st.divider()
st.download_button(
    label     = "⬇️ Download data as CSV",
    data      = pivot.to_csv(),
    file_name = f"{commodity}_implied_volatility.csv",
    mime      = "text/csv",
)

# ── Status expander ───────────────────────────────────────────────────────────
with st.expander("🔍 Data load details (expand to troubleshoot)"):
    ok = "✅" if not pivot.empty else "❌"
    st.markdown(f"**{ok} {commodity}**")
    st.caption(status_msg)
    if not pivot.empty:
        st.caption(f"Years available in file: {', '.join(str(y) for y in year_cols)}")
        st.caption(f"Years selected: {', '.join(str(y) for y in selected_valid)}")