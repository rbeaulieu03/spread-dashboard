"""
5_Calendar.py
-------------
Market events calendar — USDA reports, EIA energy releases, CFTC COT
release schedule, WASDE dates, and CME/NYMEX/ICE holidays.

Two views on the same page:
  • Month grid — visual month-at-a-glance with colored dots per day,
    one per event.
  • Upcoming events — scrollable list of the next ~30 days of events,
    ordered chronologically.

Sidebar filters categories on/off (Grains, Livestock, Dairy, Energy,
Ag Prices, COT, Holiday).

Data lives in config/calendar.yaml (USDA NASS schedule + holidays +
WASDE).  EIA weekly releases and the CFTC COT cadence are generated
by rule in src/providers/calendar.py.
"""

import sys
import os
import calendar as pycalendar
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd

from src.providers.calendar import (
    list_events,
    upcoming_events,
    month_grid,
    CATEGORIES,
)


# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Calendar", page_icon="📅", layout="wide")

# ── Light theme constants ─────────────────────────────────────────────────────
_BG          = "#FFFFFF"
_GRID_BORDER = "#E5E7EB"
_TICK_COLOR  = "#6B7280"
_TITLE_FG    = "#111827"
_TODAY_BG    = "#FEF3C7"
_HOLIDAY_BG  = "#F3F4F6"
_WEEKEND_BG  = "#FAFAFA"


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    st.divider()

    st.subheader("Categories")
    selected_cats = []
    for code, meta in CATEGORIES.items():
        checked = st.checkbox(
            f"●  {meta['label']}",
            value = True,
            key   = f"cat_{code}",
            help  = f"Show {meta['label']} events on the calendar.",
        )
        if checked:
            selected_cats.append(code)

    st.divider()
    st.caption("Sources: USDA NASS, USDA WAOB (WASDE), EIA, CFTC, "
               "CME/NYMEX/ICE holiday schedules.")
    st.caption("Refresh: update `config/calendar.yaml` annually in December "
               "with next year's NASS calendar.")


# ── Header ────────────────────────────────────────────────────────────────────
today = date.today()
st.title("📅 Market Events Calendar")
st.caption(
    f"Today: {today.strftime('%A, %B %d, %Y')}  ·  "
    "USDA / EIA / CFTC report schedule plus exchange holidays."
)
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# Month grid
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Month at a Glance")

mc1, mc2 = st.columns([1, 3])
with mc1:
    view_month = st.date_input(
        "Pick any day in the month to display",
        value = today,
        key   = "month_picker",
    )

view_year  = view_month.year
view_mnum  = view_month.month
view_name  = pycalendar.month_name[view_mnum]

cats_tuple = tuple(selected_cats) if selected_cats else None
grid_data  = month_grid(view_year, view_mnum, categories=cats_tuple)

# Build the month grid using Python's calendar module — list of weeks,
# each week is a list of 7 (date or 0 for blank).
cal = pycalendar.Calendar(firstweekday=0)   # Monday-first
weeks = cal.monthdatescalendar(view_year, view_mnum)

# Render as HTML for compact event-dot display per cell.
def _category_badge(cat: str) -> str:
    meta = CATEGORIES.get(cat, {"color": "#9CA3AF", "label": cat})
    return f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{meta["color"]};margin-right:3px;" title="{meta["label"]}"></span>'

def _cell_html(d: date, in_month: bool) -> str:
    events = grid_data.get(d, []) if in_month else []
    is_today  = (d == today)
    is_weekend = d.weekday() >= 5
    is_holiday = any(e["category"] == "holiday" for e in events)

    if not in_month:
        bg, fg = "#FFFFFF", "#D1D5DB"
    elif is_today:
        bg, fg = _TODAY_BG, _TITLE_FG
    elif is_holiday:
        bg, fg = _HOLIDAY_BG, "#6B7280"
    elif is_weekend:
        bg, fg = _WEEKEND_BG, _TICK_COLOR
    else:
        bg, fg = "#FFFFFF", _TITLE_FG

    # Day number (top-left) + event dots + tiny event names
    day_num = d.day
    dots = "".join(_category_badge(e["category"]) for e in events[:8])

    event_lines = ""
    for e in events[:4]:
        clr = CATEGORIES.get(e["category"], {}).get("color", "#9CA3AF")
        event_lines += (
            f'<div style="font-size:10px;color:{fg};white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;border-left:2px solid {clr};'
            f'padding-left:4px;margin-top:2px;">{e["event"]}</div>'
        )
    if len(events) > 4:
        event_lines += f'<div style="font-size:9px;color:#9CA3AF;margin-top:2px;">+{len(events) - 4} more</div>'

    border = f"2px solid {CATEGORIES['holiday']['color']}" if is_today else f"1px solid {_GRID_BORDER}"

    return (
        f'<td style="vertical-align:top;width:14.2%;height:110px;'
        f'background:{bg};border:{border};padding:4px;">'
        f'<div style="font-size:12px;font-weight:600;color:{fg};">{day_num}</div>'
        f'<div style="margin-top:2px;">{dots}</div>'
        f'{event_lines}'
        f'</td>'
    )

# Build the HTML table
weekday_header = "".join(
    f'<th style="background:#F9FAFB;color:{_TICK_COLOR};font-size:11px;'
    f'font-weight:600;padding:6px;border:1px solid {_GRID_BORDER};">{day}</th>'
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
)
rows_html = ""
for week in weeks:
    cells = "".join(_cell_html(d, d.month == view_mnum) for d in week)
    rows_html += f"<tr>{cells}</tr>"

table_html = (
    f'<div style="font-family:Arial,sans-serif;">'
    f'<h4 style="color:{_TITLE_FG};margin-bottom:8px;">{view_name} {view_year}</h4>'
    f'<table style="width:100%;border-collapse:collapse;">'
    f'<thead><tr>{weekday_header}</tr></thead>'
    f'<tbody>{rows_html}</tbody>'
    f'</table>'
    f'</div>'
)
st.markdown(table_html, unsafe_allow_html=True)

# Mini legend
legend_html = '<div style="margin-top:8px;font-size:11px;color:#6B7280;">Legend: '
for code, meta in CATEGORIES.items():
    legend_html += (
        f'<span style="display:inline-block;margin-right:14px;">'
        f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
        f'background:{meta["color"]};margin-right:4px;vertical-align:middle;"></span>'
        f'{meta["label"]}</span>'
    )
legend_html += '</div>'
st.markdown(legend_html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# Upcoming events list
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Upcoming Events (next 30 days)")

upc = upcoming_events(n=60, categories=cats_tuple)
upc = upc[upc["date"] <= pd.Timestamp(today + timedelta(days=30))]

if upc.empty:
    st.info("No events in the next 30 days match the selected categories.")
else:
    # Pretty up the DataFrame for display
    display = upc.copy()
    display["When"]    = display["date"].dt.strftime("%a %b %d, %Y")
    display["Days"]    = (display["date"].dt.date - today).apply(lambda x: x.days)
    display["Category"] = display["category"].map(lambda c: CATEGORIES.get(c, {}).get("label", c))

    display = display[["When", "Days", "Category", "event", "time_et", "detail"]].rename(columns={
        "event":   "Event",
        "time_et": "Time",
        "detail":  "Detail",
    })

    def _color_category(row):
        cat_label = row.get("Category", "")
        for code, meta in CATEGORIES.items():
            if meta["label"] == cat_label:
                # Subtle tinted background per category — same hue, very light
                color_map = {
                    "Grains":    "#FEF3C7",
                    "Livestock": "#FEE2E2",
                    "Dairy":     "#DBEAFE",
                    "Energy":    "#FFEDD5",
                    "Ag Prices": "#EDE9FE",
                    "CFTC COT":  "#CFFAFE",
                    "Holiday":   "#F3F4F6",
                }
                tint = color_map.get(cat_label, "")
                if tint:
                    return [f"background-color: {tint}"] * len(row)
        return [""] * len(row)

    styled = display.style.apply(_color_category, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True,
                 height=min(600, 45 + 35 * len(display)))

    st.caption(
        f"Showing {len(display)} events in the next 30 days. "
        "Adjust category checkboxes in the sidebar to filter."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Annual totals — quick view of what's coming over the rest of the year
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
with st.expander("📊 Event counts by category — rest of year"):
    all_evts = list_events(today, date(today.year, 12, 31), categories=None)
    if all_evts.empty:
        st.info("No remaining events configured for this year. "
                "Update config/calendar.yaml for the new year.")
    else:
        counts = (
            all_evts.groupby("category").size()
            .reindex(list(CATEGORIES.keys()), fill_value=0)
            .reset_index(name="Count")
        )
        counts["Category"] = counts["category"].map(lambda c: CATEGORIES.get(c, {}).get("label", c))
        counts = counts[["Category", "Count"]]
        st.dataframe(counts, use_container_width=True, hide_index=True)
        st.caption(f"Total: {counts['Count'].sum()} events between today and Dec 31.")


# ══════════════════════════════════════════════════════════════════════════════
# Annual refresh reminder
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🔁 Annual refresh notes"):
    st.markdown("""
    **When to update:** December each year, when USDA NASS publishes the
    next year's Agricultural Statistics Board Calendar.

    **Where:** `config/calendar.yaml` — replace the `holidays_<year>:`,
    `usda_reports_<year>:`, and `wasde_<year>:` blocks with the new year's
    data, then update the YAML keys to match the new year (or rename to
    a generic `holidays:` / `usda_reports:` / `wasde:` if you prefer).

    **What's auto-generated (no annual update needed):**
    - EIA Weekly Petroleum Status (Wednesdays 10:30 AM ET)
    - EIA Weekly Natural Gas Storage (Thursdays 10:30 AM ET)
    - CFTC COT Release (Fridays 3:30 PM ET)

    These follow strict weekly cadences and are built by rule in
    `src/providers/calendar.py`. They occasionally slip by a weekday
    when a federal holiday falls earlier in the week — cross-check on
    holiday weeks.
    """)
