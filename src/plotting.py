"""
plotting.py
-----------
Builds the light-themed Plotly seasonality overlay chart.

Visual design:
  - Off-white / white background, dark text — minimalistic light mode
  - Color gradient from oldest → newest year (green → blue → purple → gold → orange → red)
  - Current/highlighted year: deep cyan (cyan-600), noticeably thicker line
  - Average: dark slate dashed line, medium weight
  - 10th–90th percentile band: very subtle semi-transparent fill
  - Unified hover tooltip
"""

import plotly.graph_objects as go
import pandas as pd


# ── Color palette ─────────────────────────────────────────────────────────────
# Historical year line colors — preserved from the original palette.
# The highlighted (most recent) year always overrides with a deep cyan
# that reads clearly against the light background.
_YEAR_COLORS = [
    "#4CAF7D",   # green          — oldest
    "#4169E1",   # royal blue
    "#9370DB",   # medium purple
    "#DAA520",   # goldenrod
    "#FF8C00",   # dark orange
    "#DC143C",   # crimson red    — second-most-recent
]
_CURRENT_COLOR   = "#0891B2"                     # deep cyan — current year
_AVERAGE_COLOR   = "#374151"                     # dark slate dashed
_BAND_COLOR      = "rgba(31, 41, 55, 0.08)"      # subtle gray band fill

# ── Light theme chrome (axes, fonts, legend, hover) ───────────────────────────
_PAPER_BG   = "#FFFFFF"
_PLOT_BG    = "#FFFFFF"
_TITLE_FG   = "#111827"
_FONT_FG    = "#374151"
_TICK_FG    = "#6B7280"
_GRID       = "#E5E7EB"
_AXIS_LINE  = "#D1D5DB"
_ZERO_LINE  = "#D1D5DB"
_LEGEND_BG  = "rgba(255,255,255,0.85)"
_HOVER_BG   = "rgba(255,255,255,0.95)"
_HOVER_BRD  = "#D1D5DB"


def build_seasonality_chart(
    pivot:                pd.DataFrame,
    commodity:            str,
    spread_name:          str,
    unit:                 str,
    highlight_year:       int,
    show_average:         bool = True,
    show_percentile_band: bool = True,
) -> go.Figure:
    """
    Build the seasonality overlay Plotly figure matching the reference style.

    Parameters
    ----------
    pivot                : output of compute_seasonality()
    commodity            : e.g. "Corn"
    spread_name          : e.g. "Jul-Sep"
    unit                 : e.g. "cents/bu"
    highlight_year       : drawn in cyan, thicker line
    show_average         : toggle the white dashed average line
    show_percentile_band : toggle the 10th–90th percentile band
    """

    # ── Empty data guard ──────────────────────────────────────────────────────
    if pivot.empty:
        fig = go.Figure()
        fig.update_layout(
            title       = dict(text="No data available — check Data Status page",
                               font=dict(color="#B91C1C"), x=0.5),
            paper_bgcolor = _PAPER_BG,
            plot_bgcolor  = _PLOT_BG,
        )
        return fig

    year_cols = sorted([c for c in pivot.columns if isinstance(c, int)])
    x_labels  = pivot.index.tolist()

    # ── Assign colors ─────────────────────────────────────────────────────────
    non_highlight = [y for y in year_cols if y != highlight_year]
    color_map     = {}

    for i, yr in enumerate(non_highlight):
        palette_idx       = i % len(_YEAR_COLORS)
        color_map[yr]     = _YEAR_COLORS[palette_idx]

    if highlight_year in year_cols:
        color_map[highlight_year] = _CURRENT_COLOR

    fig = go.Figure()

    # ── 1. Percentile band ────────────────────────────────────────────────────
    if show_percentile_band and "p10" in pivot.columns and "p90" in pivot.columns:
        p10 = pivot["p10"].tolist()
        p90 = pivot["p90"].tolist()

        fig.add_trace(go.Scatter(
            x          = x_labels + x_labels[::-1],
            y          = p90 + p10[::-1],
            fill       = "toself",
            fillcolor  = _BAND_COLOR,
            line       = dict(color="rgba(0,0,0,0)"),
            hoverinfo  = "skip",
            showlegend = True,
            name       = "10–90th %ile",
        ))

    # ── 2. Historical year lines ──────────────────────────────────────────────
    for year in year_cols:
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
            line = dict(
                color = color_map.get(year, "#888888"),
                width = 1.2,
            ),
            hovertemplate = f"<b>{year}</b>: %{{y:.2f}}<extra></extra>",
        ))

    # ── 3. Average line ───────────────────────────────────────────────────────
    if show_average and "Average" in pivot.columns:
        avg = pivot["Average"].dropna()
        if not avg.empty:
            fig.add_trace(go.Scatter(
                x    = avg.index.tolist(),
                y    = avg.values,
                mode = "lines",
                name = "Average",
                line = dict(color=_AVERAGE_COLOR, width=1.8, dash="dash"),
                hovertemplate = "<b>Average</b>: %{y:.2f}<extra></extra>",
            ))

    # ── 4. Current/highlighted year ───────────────────────────────────────────
    if highlight_year in year_cols:
        series = pivot[highlight_year].dropna()
        if not series.empty:
            fig.add_trace(go.Scatter(
                x    = series.index.tolist(),
                y    = series.values,
                mode = "lines",
                name = str(highlight_year),
                line = dict(
                    color = _CURRENT_COLOR,
                    width = 2.8,
                ),
                hovertemplate = f"<b>{highlight_year}</b>: %{{y:.2f}}<extra></extra>",
            ))

    # ── 5. Layout ─────────────────────────────────────────────────────────────
    n_total = len(x_labels)
    step    = max(1, n_total // 18)
    tick_vals = x_labels[::step]

    all_values = []
    for col in year_cols:
        if col in pivot.columns:
            all_values.extend(pivot[col].dropna().tolist())

    fig.update_layout(
        title = dict(
            text = f"{commodity} {spread_name} Spread Seasonality",
            font = dict(size=14, color=_TITLE_FG, family="Arial"),
            x    = 0.5,
            y    = 0.97,
        ),
        paper_bgcolor = _PAPER_BG,
        plot_bgcolor  = _PLOT_BG,
        font          = dict(color=_FONT_FG, size=11, family="Arial"),

        xaxis = dict(
            title         = dict(text="Date (MM-DD)", font=dict(size=14, color=_TICK_FG)),
            type          = "category",
            categoryorder = "array",
            categoryarray = x_labels,
            tickangle     = -45,
            tickvals      = tick_vals,
            ticktext      = tick_vals,
            tickfont      = dict(size=11, color=_TICK_FG),
            gridcolor     = _GRID,
            gridwidth     = 1,
            linecolor     = _AXIS_LINE,
            showline      = True,
        ),
        yaxis = dict(
            title       = dict(text=f"Spread ({unit})", font=dict(size=14, color=_TICK_FG)),
            tickfont    = dict(size=12, color=_TICK_FG),
            gridcolor   = _GRID,
            gridwidth   = 1,
            linecolor   = _AXIS_LINE,
            showline    = True,
            zeroline    = True,
            zerolinecolor = _ZERO_LINE,
            zerolinewidth = 1.5,
        ),
        legend = dict(
            x           = 1.01,
            y           = 1.0,
            xanchor     = "left",
            yanchor     = "top",
            bgcolor     = _LEGEND_BG,
            bordercolor = _AXIS_LINE,
            borderwidth = 1,
            font        = dict(size=12, color=_FONT_FG),
            traceorder  = "normal",
        ),
        hovermode = "x unified",
        hoverlabel = dict(
            bgcolor   = _HOVER_BG,
            bordercolor = _HOVER_BRD,
            font      = dict(size=11, color=_TITLE_FG),
        ),
        height  = 580,
        margin  = dict(l=70, r=140, t=60, b=90),
    )

    return fig
