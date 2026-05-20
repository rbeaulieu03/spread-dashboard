"""
6_Weather.py
------------
Weather dashboard — 7-day NWS point forecasts for commodity-relevant
regions, split into Grain Belt and Livestock tabs.

Each location shows:
  • Forecast high/low temperature by day
  • Daily precip chance
  • Anomaly metrics: avg forecast temp vs the monthly climate normal,
    and avg precip-chance for context against the monthly normal precip.

Data source: api.weather.gov (no auth required).  CPC 6-10 and 8-14 day
outlook maps are embedded at the bottom of each tab as a forward-look
overlay.

Future: when the Tyson weather desk subscription is wired in, add a
source toggle in the sidebar to switch between NWS and Tyson Desk.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.providers.weather import (
    GRAIN_LOCATIONS,
    LIVESTOCK_LOCATIONS,
    fetch_all_forecasts,
    compute_anomaly,
)


# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Weather", page_icon="🌤️", layout="wide")

# ── Light theme constants (matches the rest of the dashboard) ─────────────────
_BG         = "#FFFFFF"
_PLOT_BG    = "#FFFFFF"
_GRID       = "#E5E7EB"
_LINE       = "#D1D5DB"
_FONT_COLOR = "#374151"
_TICK_COLOR = "#6B7280"
_TITLE_FG   = "#111827"
_LEGEND_BG  = "rgba(255,255,255,0.85)"
_HOVER_BG   = "rgba(255,255,255,0.95)"

_TEMP_HIGH  = "#DC143C"   # crimson — daily high
_TEMP_LOW   = "#4169E1"   # royal blue — daily low
_PRECIP     = "#0891B2"   # deep cyan — precip probability

_LAYOUT_BASE = dict(
    paper_bgcolor = _BG,
    plot_bgcolor  = _PLOT_BG,
    font          = dict(color=_FONT_COLOR, size=11, family="Arial"),
    legend        = dict(
        x=1.01, y=1.0, xanchor="left", yanchor="top",
        bgcolor=_LEGEND_BG, bordercolor=_LINE, borderwidth=1,
        font=dict(size=12, color=_FONT_COLOR),
    ),
    hoverlabel = dict(bgcolor=_HOVER_BG, bordercolor=_LINE,
                      font=dict(size=11, color=_TITLE_FG)),
)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    st.divider()
    st.caption("Source: National Weather Service (api.weather.gov)")
    st.caption("Refreshes hourly per location.")
    st.caption("")
    st.caption(
        "Future: switch to the Tyson Weather Desk feed once its endpoint "
        "details are documented in `src/providers/weather.py`."
    )

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🌤️ Weather — 7-Day Forecasts")
st.caption("Point forecasts for commodity-relevant locations across the US.")
st.divider()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _location_chart(name: str, region: str, df: pd.DataFrame) -> go.Figure:
    """One small forecast chart for a single location."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            **_LAYOUT_BASE,
            title  = dict(text=f"{name} — no data", font=dict(size=12, color=_TITLE_FG), x=0.5),
            height = 220,
            margin = dict(l=40, r=40, t=40, b=30),
        )
        return fig

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Temperature traces
    fig.add_trace(go.Scatter(
        x    = df["date"], y = df["tmax_f"],
        name = "High °F",
        mode = "lines+markers",
        line = dict(color=_TEMP_HIGH, width=2.2),
        marker = dict(size=6),
        hovertemplate = "<b>%{x|%a %b %d}</b><br>High: %{y:.0f}°F<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x    = df["date"], y = df["tmin_f"],
        name = "Low °F",
        mode = "lines+markers",
        line = dict(color=_TEMP_LOW, width=2.2),
        marker = dict(size=6),
        hovertemplate = "<b>%{x|%a %b %d}</b><br>Low: %{y:.0f}°F<extra></extra>",
    ), secondary_y=False)

    # Precip probability — bars on secondary axis
    fig.add_trace(go.Bar(
        x      = df["date"], y = df["precip_prob_max"],
        name   = "Precip %",
        marker_color = _PRECIP,
        opacity      = 0.35,
        hovertemplate = "<b>%{x|%a %b %d}</b><br>Precip chance: %{y:.0f}%<extra></extra>",
    ), secondary_y=True)

    fig.update_layout(
        **_LAYOUT_BASE,
        title = dict(
            text = f"{name}  ·  {region}",
            font = dict(size=13, color=_TITLE_FG, family="Arial"),
            x    = 0.5,
        ),
        height    = 280,
        margin    = dict(l=50, r=60, t=50, b=40),
        hovermode = "x unified",
        barmode   = "overlay",
        showlegend = True,
    )
    fig.update_xaxes(
        tickfont  = dict(size=10, color=_TICK_COLOR),
        gridcolor = _GRID, linecolor = _LINE, showline = True,
        tickformat = "%a %b %d",
    )
    fig.update_yaxes(
        title_text = "°F",
        tickfont   = dict(size=10, color=_TICK_COLOR),
        title_font = dict(size=11, color=_TICK_COLOR),
        gridcolor  = _GRID, linecolor = _LINE, showline = True,
        secondary_y = False,
    )
    fig.update_yaxes(
        title_text = "Precip %",
        tickfont   = dict(size=10, color=_TICK_COLOR),
        title_font = dict(size=11, color=_TICK_COLOR),
        range      = [0, 100], showgrid = False,
        secondary_y = True,
    )
    return fig


def _render_tab(locations: dict, label: str, cpc_caption: str):
    """Render one tab — fetch forecasts, draw a card grid, show CPC outlooks."""
    with st.spinner(f"Fetching {label} forecasts from NWS…"):
        results, status = fetch_all_forecasts(locations)

    # ── Anomaly summary strip ────────────────────────────────────────────
    st.subheader(f"{label} — Anomaly Summary (forecast vs monthly normal)")
    st.caption(
        "Temperature anomaly = avg forecast temp − historical monthly normal at that location. "
        "Precip column shows mean daily chance-of-precipitation across the forecast horizon "
        "alongside the historical monthly precip total for context."
    )

    summary_rows = []
    for name in locations:
        df = results.get(name, pd.DataFrame())
        anom = compute_anomaly(df, name)
        summary_rows.append({
            "Location":    name,
            "Region":      locations[name]["region"],
            "Days":        anom["horizon_days"] or 0,
            "Avg Temp °F": anom["avg_temp_f"],
            "Normal °F":   anom["normal_temp_f"],
            "Anomaly °F":  anom["temp_anomaly_f"],
            "Avg Precip %": anom["total_precip_prob"],
            "Normal Precip (in/mo)": anom["normal_precip_in"],
        })
    summary_df = pd.DataFrame(summary_rows)

    def _color_temp_anom(v):
        if v is None or pd.isna(v):
            return ""
        if v >= 5:
            return "background-color: #FEE2E2"   # warm anomaly
        if v >= 2:
            return "background-color: #FEF2F2"
        if v <= -5:
            return "background-color: #DBEAFE"   # cool anomaly
        if v <= -2:
            return "background-color: #EFF6FF"
        return ""

    styled = summary_df.style.format({
        "Avg Temp °F":             lambda v: f"{v:.1f}"   if pd.notna(v) else "—",
        "Normal °F":               lambda v: f"{v:.1f}"   if pd.notna(v) else "—",
        "Anomaly °F":              lambda v: f"{v:+.1f}"  if pd.notna(v) else "—",
        "Avg Precip %":            lambda v: f"{int(v)}%" if pd.notna(v) else "—",
        "Normal Precip (in/mo)":   lambda v: f"{v:.2f}\""  if pd.notna(v) else "—",
    }, na_rep="—").map(_color_temp_anom, subset=["Anomaly °F"])

    st.dataframe(styled, use_container_width=True, hide_index=True, height=min(300, 45 + 35 * len(summary_df)))

    # ── Per-location forecast charts (2 across) ──────────────────────────
    st.divider()
    st.subheader(f"{label} — 7-Day Point Forecasts")

    names = list(locations.keys())
    for i in range(0, len(names), 2):
        cols = st.columns(2)
        for col, name in zip(cols, names[i:i + 2]):
            with col:
                df = results.get(name, pd.DataFrame())
                fig = _location_chart(name, locations[name]["region"], df)
                st.plotly_chart(fig, use_container_width=True)

    # ── CPC 6-10 / 8-14 day outlook embed ────────────────────────────────
    st.divider()
    st.subheader("CPC Medium-Range Outlooks")
    st.caption(cpc_caption)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 6-10 Day Temperature")
        st.image("https://www.cpc.ncep.noaa.gov/products/predictions/610day/610temp.new.gif",
                 caption="Probability of above- (red) / below-normal (blue) temperature.")
    with c2:
        st.markdown("##### 6-10 Day Precipitation")
        st.image("https://www.cpc.ncep.noaa.gov/products/predictions/610day/610prcp.new.gif",
                 caption="Probability of above- (green) / below-normal (brown) precipitation.")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("##### 8-14 Day Temperature")
        st.image("https://www.cpc.ncep.noaa.gov/products/predictions/814day/814temp.new.gif",
                 caption="8-14 day temperature outlook.")
    with c4:
        st.markdown("##### 8-14 Day Precipitation")
        st.image("https://www.cpc.ncep.noaa.gov/products/predictions/814day/814prcp.new.gif",
                 caption="8-14 day precipitation outlook.")

    # ── Troubleshoot expander ────────────────────────────────────────────
    with st.expander("🔍 NWS fetch details"):
        for name, msg in status.items():
            ok = "✅" if msg.startswith("OK") else "❌"
            st.markdown(f"**{ok} {name}** — {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_grain, tab_livestock = st.tabs(["🌾 Grain Belt", "🐄 Livestock"])

with tab_grain:
    _render_tab(
        GRAIN_LOCATIONS, "Grain Belt",
        "Forward-looking probability maps from NOAA Climate Prediction Center. "
        "Watch the Corn Belt and Plains states for crop-development implications.",
    )

with tab_livestock:
    _render_tab(
        LIVESTOCK_LOCATIONS, "Livestock",
        "Watch Plains-states heat anomalies for cattle stress and transport "
        "disruptions, and Southern/Midwest precip for plant operations.",
    )
