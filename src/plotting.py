"""
plotting.py
-----------
Builds the dark-themed Plotly seasonality overlay chart.

Visual design matches the reference charts from Spreads.pdf:
  - Pure black background
  - Color gradient from oldest → newest year (green → blue → purple → gold → orange → red)
  - Current/highlighted year: bright CYAN, noticeably thicker line
  - Average: white dashed line, medium weight
  - 10th–90th percentile band: very subtle semi-transparent fill
  - Unified hover tooltip
"""

import plotly.graph_objects as go
import pandas as pd


# ── Color palette ─────────────────────────────────────────────────────────────
# Matches the reference chart progression: oldest → newest historical year.
# The highlighted (most recent) year always overrides with bright cyan.
_YEAR_COLORS = [
    "#4CAF7D",   # green          — oldest
    "#4169E1",   # royal blue
    "#9370DB",   # medium purple
    "#DAA520",   # goldenrod
    "#FF8C00",   # dark orange
    "#DC143C",   # crimson red    — second-most-recent
]
_CURRENT_COLOR   = "#00FFFF"                     # bright cyan — current year
_AVERAGE_COLOR   = "#FFFFFF"                     # white dashed
_BAND_COLOR      = "rgba(255, 255, 255, 0.06)"   # very subtle band fill


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
                               font=dict(color="#FF4444"), x=0.5),
            paper_bgcolor = "#000000",
            plot_bgcolor  = "#000000",
        )
        return fig

    year_cols = sorted([c for c in pivot.columns if isinstance(c, int)])
    x_labels  = pivot.index.tolist()

    # ── Assign colors ─────────────────────────────────────────────────────────
    # Non-highlighted years get the palette in order (oldest first).
    # Highlighted year always gets cyan.
    non_highlight = [y for y in year_cols if y != highlight_year]
    color_map     = {}

    # Align colors so the year just before highlight is always the last
    # palette color (red), giving the clearest visual separation.
    for i, yr in enumerate(non_highlight):
        palette_idx       = i % len(_YEAR_COLORS)
        color_map[yr]     = _YEAR_COLORS[palette_idx]

    if highlight_year in year_cols:
        color_map[highlight_year] = _CURRENT_COLOR

    fig = go.Figure()

    # ── 1. Percentile band (behind everything else) ───────────────────────────
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

    # ── 2. Historical year lines (non-highlighted, drawn first) ───────────────
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

    # ── 4. Current/highlighted year (drawn last so it's always on top) ────────
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
    # Space x-axis ticks evenly — aim for ~18 visible labels.
    n_total = len(x_labels)
    step    = max(1, n_total // 18)
    tick_vals = x_labels[::step]

    # Zero reference line
    all_values = []
    for col in year_cols:
        if col in pivot.columns:
            all_values.extend(pivot[col].dropna().tolist())

    fig.update_layout(
        title = dict(
            text = f"{commodity} {spread_name} Spread Seasonality",
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
            title       = dict(text=f"Spread ({unit})", font=dict(size=14, color="#AAAAAA")),
            tickfont    = dict(size=12, color="#AAAAAA"),
            gridcolor   = "#1A1A1A",
            gridwidth   = 1,
            linecolor   = "#333333",
            showline    = True,
            zeroline    = True,
            zerolinecolor = "#2A2A2A",
            zerolinewidth = 1.5,
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
            traceorder  = "normal",
        ),
        hovermode = "x unified",
        hoverlabel = dict(
            bgcolor   = "rgba(0,0,0,0.85)",
            bordercolor = "#444444",
            font      = dict(size=11, color="#FFFFFF"),
        ),
        height  = 580,
        margin  = dict(l=70, r=140, t=60, b=90),
    )

    return fig
