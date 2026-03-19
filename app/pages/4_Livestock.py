"""
4_Livestock.py
--------------
Livestock cash market dashboard.

Tabs:
  🐄 Cash Prices  — Weekly weighted average cash prices for 5 Area, Kansas,
                    and Nebraska Direct Slaughter Cattle (USDA AMS Datamart),
                    split by selling basis, overlaid with ProphetX front-month.
  ↕️ North/South  — Nebraska minus Kansas weekly LIVE FOB spread.

Data sources:
  Cash prices : USDA AMS Datamart (no auth required)
      Slug 2477  LM_CT150  5 Area
      Slug 2484  LM_CT157  Kansas
      Slug 2485  LM_CT158  Nebraska
  Futures     : ProphetX Excel (data/prophetx/cattle.xlsx)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date

from src.providers.usda  import fetch_all_cash_prices, CASH_REPORTS
from src.providers.excel import load_commodity_file

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Livestock", page_icon="🐄", layout="wide")

# ── Dark theme ────────────────────────────────────────────────────────────────
_BG         = "#000000"
_PLOT_BG    = "#000000"
_GRID       = "#1A1A1A"
_LINE       = "#333333"
_FONT_COLOR = "#BBBBBB"
_TICK_COLOR = "#AAAAAA"
_LEGEND_BG  = "rgba(0,0,0,0.75)"
_HOVER_BG   = "rgba(0,0,0,0.85)"

_COLOR_5AREA    = "#FFFFFF"
_COLOR_KANSAS   = "#FF8C00"
_COLOR_NEBRASKA = "#4CAF7D"
_COLOR_FUTURES  = "#00FFFF"

_LAYOUT_BASE = dict(
    paper_bgcolor = _BG,
    plot_bgcolor  = _PLOT_BG,
    font          = dict(color=_FONT_COLOR, size=11, family="Arial"),
    legend        = dict(
        x=1.01, y=1.0, xanchor="left", yanchor="top",
        bgcolor=_LEGEND_BG, bordercolor=_LINE, borderwidth=1,
        font=dict(size=12, color="#CCCCCC"),
    ),
    hoverlabel = dict(bgcolor=_HOVER_BG, bordercolor="#444444",
                      font=dict(size=11, color="#FFFFFF")),
)

# Reusable axis style helpers — applied via update_xaxes / update_yaxes
_XAXIS_BASE = dict(tickfont=dict(size=11, color=_TICK_COLOR),
                   gridcolor=_GRID, linecolor=_LINE, showline=True)
_YAXIS_BASE = dict(tickfont=dict(size=11, color=_TICK_COLOR),
                   gridcolor=_GRID, linecolor=_LINE, showline=True, zeroline=False)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    st.divider()

    lookback_years = st.selectbox(
        "Lookback Period",
        options=[1, 2, 3, 5], index=2,
        format_func=lambda x: f"{x} year{'s' if x > 1 else ''}",
    )

    st.subheader("Selling Basis")
    show_live_fob       = st.checkbox("Live FOB",          value=True)
    show_live_delivered = st.checkbox("Live Delivered",     value=False)
    show_dressed        = st.checkbox("Dressed Delivered",  value=False)

    show_futures = st.toggle(
        "Show Front-Month Futures (Friday Close)", value=True,
        help="Overlays Live Cattle front-month Friday close from ProphetX.",
    )

    st.divider()
    st.caption("Cash data: USDA AMS Datamart (no auth)")
    st.caption("Reports: LM_CT150, LM_CT157, LM_CT158")
    st.caption("Published: Fridays (weekly weighted average)")
    st.caption("Futures: ProphetX Excel (cattle.xlsx)")


# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner("Fetching USDA cash cattle prices…"):
    cash_df, cash_status = fetch_all_cash_prices(lookback_years=lookback_years)

futures_friday = pd.Series(dtype=float)
futures_status = "Not loaded"

if show_futures:
    with st.spinner("Loading ProphetX Live Cattle data…"):
        contract_data, futures_status = load_commodity_file("LiveCattle")

    if contract_data:
        month_codes = {"F":1,"G":2,"H":3,"J":4,"K":5,"M":6,
                       "N":7,"Q":8,"U":9,"V":10,"X":11,"Z":12}
        cutoff = pd.Timestamp(date.today()) - pd.DateOffset(years=lookback_years)

        contract_expiries = {}
        for sym in contract_data:
            try:
                yr = int(sym[-2:]) + 2000
                mc = sym[-3]
                if mc in month_codes:
                    contract_expiries[sym] = pd.Timestamp(year=yr, month=month_codes[mc], day=20)
            except Exception:
                continue

        combined = pd.DataFrame(contract_data)
        combined = combined[combined.index >= cutoff]
        combined = combined[combined.index.dayofweek == 4]

        front_prices = {}
        for idx_date in combined.index:
            active = {s: e for s, e in contract_expiries.items()
                      if e >= idx_date + pd.Timedelta(days=14) and s in combined.columns}
            if not active:
                continue
            front_sym = min(active, key=lambda s: active[s])
            price = combined.loc[idx_date, front_sym]
            if pd.notna(price):
                front_prices[idx_date] = price  # ProphetX LC is cents/lb = $/cwt (1 cwt = 100 lbs, 100 cents = $1)

        futures_friday = pd.Series(front_prices, name="futures").sort_index()


# ── Page title ────────────────────────────────────────────────────────────────
st.title("🐄 Livestock — Fed Cattle Cash Market")

if cash_df.empty:
    st.error("Could not load USDA cash cattle data. See fetch details below.")
    with st.expander("🔍 Data fetch details"):
        for key, msg in cash_status.items():
            icon = "✅" if msg.startswith("OK") else "❌"
            st.markdown(f"**{icon} {CASH_REPORTS[key]['label']}** (slug {CASH_REPORTS[key]['slug']})")
            st.caption(msg)
    st.stop()

latest_date = cash_df.index.max()
st.caption(f"**Latest USDA report: {latest_date.strftime('%A, %B %d, %Y')}**")
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
tab_cash, tab_spread = st.tabs(["🐄 Cash Prices", "↕️ North/South Spread"])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — CASH PRICES
# ─────────────────────────────────────────────────────────────────────────────
with tab_cash:
    st.subheader("Weekly Weighted Average Cash Prices — All Grades")
    st.markdown(
        "Negotiated direct slaughter cattle purchases (USDA LM_CT150/157/158). "
        "Prices are $/cwt. Toggle selling basis and futures overlay in the sidebar."
    )

    fig = go.Figure()

    regions = [
        ("5area",    "5 Area",   _COLOR_5AREA),
        ("kansas",   "Kansas",   _COLOR_KANSAS),
        ("nebraska", "Nebraska", _COLOR_NEBRASKA),
    ]
    basis_options = []
    if show_live_fob:
        basis_options.append(("price_live_fob",        "Live FOB",         "solid"))
    if show_live_delivered:
        basis_options.append(("price_live_delivered",   "Live Delivered",   "dash"))
    if show_dressed:
        basis_options.append(("price_dressed",           "Dressed Delivered","dot"))

    for key, region_label, region_color in regions:
        for basis_prefix, basis_label, dash in basis_options:
            col = f"{basis_prefix}_{key}"
            if col not in cash_df.columns:
                continue
            s = cash_df[col].dropna()
            if s.empty:
                continue
            name = f"{region_label} — {basis_label}"
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values,
                mode="lines+markers",
                name=name,
                line=dict(color=region_color, width=2, dash=dash),
                marker=dict(size=4),
                hovertemplate=f"<b>{name}</b>: $%{{y:.2f}}/cwt<br>%{{x|%b %d, %Y}}<extra></extra>",
            ))

    if show_futures and not futures_friday.empty:
        fig.add_trace(go.Scatter(
            x=futures_friday.index, y=futures_friday.values,
            mode="lines",
            name="LC Front-Month (Friday Close)",
            line=dict(color=_COLOR_FUTURES, width=1.5, dash="dash"),
            hovertemplate="<b>LC Futures</b>: $%{y:.2f}/cwt<br>%{x|%b %d, %Y}<extra></extra>",
        ))

    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text="Fed Cattle Weekly Cash Prices ($/cwt) — All Grades",
                   font=dict(size=14, color="#FFFFFF", family="Arial"), x=0.5, y=0.97),
        hovermode="x unified",
        height=540,
        margin=dict(l=80, r=200, t=60, b=70),
    )
    fig.update_yaxes(title=dict(text="Price ($/cwt)", font=dict(size=13, color=_TICK_COLOR)),
                     tickfont=dict(size=11, color=_TICK_COLOR),
                     gridcolor=_GRID, linecolor=_LINE,
                     showline=True, zeroline=False, tickprefix="$")
    fig.update_xaxes(title=dict(text="Week Ending Date", font=dict(size=13, color=_TICK_COLOR)),
                     tickfont=dict(size=11, color=_TICK_COLOR),
                     gridcolor=_GRID, linecolor=_LINE, showline=True)
    st.plotly_chart(fig, use_container_width=True)

    # Latest price metrics
    c1, c2, c3, c4 = st.columns(4)

    def _metric(col_obj, label, price_col):
        if price_col in cash_df.columns:
            s = cash_df[price_col].dropna()
            if not s.empty:
                val = s.iloc[-1]
                prev = s.iloc[-2] if len(s) > 1 else None
                delta = f"{val - prev:+.2f}" if prev is not None else None
                col_obj.metric(
                    label=f"{label}  ({s.index[-1].strftime('%b %d')})",
                    value=f"${val:.2f}/cwt",
                    delta=delta,
                )

    _metric(c1, "5 Area",   "price_live_fob_5area")
    _metric(c2, "Kansas",   "price_live_fob_kansas")
    _metric(c3, "Nebraska", "price_live_fob_nebraska")

    if show_futures and not futures_friday.empty:
        fv = futures_friday.iloc[-1]
        fp = futures_friday.iloc[-2] if len(futures_friday) > 1 else None
        c4.metric(
            label=f"LC Futures  ({futures_friday.index[-1].strftime('%b %d')})",
            value=f"${fv:.2f}/cwt",
            delta=f"{fv - fp:+.2f}" if fp is not None else None,
        )

    # Volume table
    st.divider()
    st.subheader("Weekly Volume (Head) — Live FOB")
    vol_map = {"5 Area": "head_live_fob_5area",
               "Kansas": "head_live_fob_kansas",
               "Nebraska": "head_live_fob_nebraska"}
    vol_data = {lbl: cash_df[col].dropna()
                for lbl, col in vol_map.items() if col in cash_df.columns}
    if vol_data:
        vdf = pd.DataFrame(vol_data).sort_index(ascending=False).head(12)
        vdf.index = vdf.index.strftime("%b %d, %Y")
        vdf = vdf.map(lambda x: f"{int(x):,}" if pd.notna(x) else "—")
        st.dataframe(vdf, use_container_width=True)

    st.divider()
    dl = cash_df.copy()
    dl.index = dl.index.strftime("%Y-%m-%d")
    st.download_button(
        label="⬇️ Download cash price data as CSV",
        data=dl.to_csv(),
        file_name=f"usda_cash_cattle_{date.today()}.csv",
        mime="text/csv",
    )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — NORTH/SOUTH SPREAD
# ─────────────────────────────────────────────────────────────────────────────
with tab_spread:
    st.subheader("North/South Cash Spread — Nebraska minus Kansas (Live FOB)")
    st.markdown(
        "Weekly differential between Nebraska and Kansas weighted average cash prices. "
        "Positive = Nebraska at a premium to Kansas."
    )

    spread_col = "spread_ne_ks_live_fob"

    if spread_col not in cash_df.columns:
        st.warning("Nebraska and/or Kansas data not available to compute the spread.")
    else:
        spread = cash_df[spread_col].dropna()
        bar_colors = [_COLOR_NEBRASKA if v >= 0 else _COLOR_KANSAS for v in spread.values]

        fig_spread = go.Figure()
        fig_spread.add_trace(go.Bar(
            x=spread.index, y=spread.values,
            name="NE − KS Spread",
            marker_color=bar_colors,
            hovertemplate="<b>NE − KS</b>: $%{y:+.2f}/cwt<br>%{x|%b %d, %Y}<extra></extra>",
        ))
        fig_spread.add_hline(y=0, line_width=1, line_color="#444444", line_dash="dash")

        if len(spread) >= 4:
            rolling = spread.rolling(4).mean().dropna()
            fig_spread.add_trace(go.Scatter(
                x=rolling.index, y=rolling.values,
                mode="lines", name="4-Week Avg",
                line=dict(color="#FFFFFF", width=1.8, dash="dot"),
                hovertemplate="<b>4-Wk Avg</b>: $%{y:+.2f}/cwt<br>%{x|%b %d, %Y}<extra></extra>",
            ))

        fig_spread.update_layout(
            **_LAYOUT_BASE,
            title=dict(text="Nebraska − Kansas Weekly Cash Spread ($/cwt) — Live FOB",
                       font=dict(size=14, color="#FFFFFF", family="Arial"), x=0.5, y=0.97),
            hovermode="x unified",
            height=500,
            margin=dict(l=80, r=160, t=60, b=70),
            bargroupgap=0.1,
        )
        fig_spread.update_yaxes(
            title=dict(text="Spread ($/cwt)", font=dict(size=13, color=_TICK_COLOR)),
            tickfont=dict(size=11, color=_TICK_COLOR),
            gridcolor=_GRID, linecolor=_LINE,
            showline=True, zeroline=True,
            zerolinecolor="#2A2A2A", zerolinewidth=1.5, tickprefix="$")
        fig_spread.update_xaxes(
            title=dict(text="Week Ending Date", font=dict(size=13, color=_TICK_COLOR)),
            tickfont=dict(size=11, color=_TICK_COLOR),
            gridcolor=_GRID, linecolor=_LINE, showline=True)
        st.plotly_chart(fig_spread, use_container_width=True)

        latest_spread = spread.iloc[-1]
        avg_spread    = spread.mean()
        pctile        = round((spread < latest_spread).sum() / len(spread) * 100)

        s1, s2, s3 = st.columns(3)
        s1.metric(label=f"Latest Spread  ({spread.index[-1].strftime('%b %d')})",
                  value=f"${latest_spread:+.2f}/cwt")
        s2.metric(label=f"Avg Spread  ({lookback_years}yr)",
                  value=f"${avg_spread:+.2f}/cwt",
                  delta=f"{latest_spread - avg_spread:+.2f} vs avg")
        s3.metric(label="Historical Percentile", value=f"{pctile}th",
                  help=f"Where current spread ranks vs the {lookback_years}-year window.")

        st.divider()
        st.subheader("Recent Spread History")

        ne_s = cash_df.get("price_live_fob_nebraska", pd.Series()).dropna()
        ks_s = cash_df.get("price_live_fob_kansas",   pd.Series()).dropna()

        history = pd.DataFrame({
            "Nebraska ($/cwt)": ne_s,
            "Kansas ($/cwt)":   ks_s,
            "NE − KS ($/cwt)":  spread,
        }).sort_index(ascending=False).head(16)
        history.index = history.index.strftime("%b %d, %Y")
        history = history.map(lambda x: f"${x:+.2f}" if pd.notna(x) else "—")
        st.dataframe(history, use_container_width=True)

        st.divider()
        st.download_button(
            label="⬇️ Download spread data as CSV",
            data=cash_df[["price_live_fob_nebraska", "price_live_fob_kansas",
                          spread_col]].to_csv(),
            file_name=f"ne_ks_cash_spread_{date.today()}.csv",
            mime="text/csv",
        )


# ── Troubleshoot expander ─────────────────────────────────────────────────────
with st.expander("🔍 Data fetch details (expand to troubleshoot)"):
    for key, msg in cash_status.items():
        icon = "✅" if msg.startswith("OK") else "❌"
        st.markdown(f"**{icon} {CASH_REPORTS[key]['label']}** (slug {CASH_REPORTS[key]['slug']})")
        st.caption(msg)
    if show_futures:
        fut_icon = "✅" if not futures_friday.empty else "❌"
        st.markdown(f"**{fut_icon} Live Cattle Futures (ProphetX)**")
        st.caption(futures_status)
        if not futures_friday.empty:
            st.caption(
                f"Friday closes: {len(futures_friday)} weeks "
                f"({futures_friday.index[0].strftime('%Y-%m-%d')} → "
                f"{futures_friday.index[-1].strftime('%Y-%m-%d')})"
            )