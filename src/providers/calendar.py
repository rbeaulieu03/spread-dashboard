"""
calendar.py
-----------
Market events calendar provider.

Loads config/calendar.yaml (curated USDA NASS reports + federal/exchange
holidays + WASDE dates), augments it with rule-based recurring events
(EIA weekly releases, CFTC COT weekly release), and exposes helpers for
the Calendar page:

    list_events(start_date, end_date, categories=None) -> DataFrame
    upcoming_events(n=20, categories=None)             -> DataFrame
    month_grid(year, month, categories=None)           -> dict (date → events list)

Each event row has:
    date        — calendar date (pd.Timestamp)
    event       — display name
    category    — one of: grains, livestock, dairy, energy, prices, cot, holiday
    time_et     — release time in ET (e.g. "12:00 PM" or "All day" for holidays)
    source      — usda_nass | wasde | eia | cftc | exchange_holiday

Annual refresh: update config/calendar.yaml in December with the next
year's USDA NASS calendar.
"""

import os
import yaml
import pandas as pd
import streamlit as st
from datetime import date, datetime, timedelta


_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "calendar.yaml",
)


# Map NASS time codes to display strings (Eastern Time).
_TIME_LABEL = {
    "PFEI_NOON": "12:00 PM ET",
    "PFEI_3PM":  "3:00 PM ET",
    "1200":      "12:00 PM ET",
    "1500":      "3:00 PM ET",
    "1600":      "4:00 PM ET",
}


# ── Category metadata (for filtering + color coding) ─────────────────────────
CATEGORIES = {
    "grains":     {"label": "Grains",     "color": "#DAA520"},   # goldenrod
    "livestock":  {"label": "Livestock",  "color": "#DC143C"},   # crimson
    "dairy":      {"label": "Dairy",      "color": "#4169E1"},   # royal blue
    "energy":     {"label": "Energy",     "color": "#FF8C00"},   # dark orange
    "prices":     {"label": "Ag Prices",  "color": "#9370DB"},   # purple
    "cot":        {"label": "CFTC COT",   "color": "#0891B2"},   # deep cyan
    "holiday":    {"label": "Holiday",    "color": "#6B7280"},   # slate
}


# ── Config loader ────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _load_config() -> dict:
    """Parse config/calendar.yaml.  Cached for the session."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Event assembly ───────────────────────────────────────────────────────────

def _from_yaml_holidays(cfg: dict) -> list:
    rows = []
    for h in cfg.get("holidays_2026", []):
        exchanges = ", ".join(h.get("exchanges", [])) or "—"
        rows.append({
            "date":     pd.Timestamp(h["date"]),
            "event":    f"Market Holiday — {h['label']}",
            "category": "holiday",
            "time_et":  "All day",
            "source":   "exchange_holiday",
            "detail":   f"Closed: {exchanges}",
        })
    return rows


def _from_yaml_usda(cfg: dict) -> list:
    rows = []
    for r in cfg.get("usda_reports_2026", []):
        rows.append({
            "date":     pd.Timestamp(r["date"]),
            "event":    r["report"],
            "category": r.get("category", "grains"),
            "time_et":  _TIME_LABEL.get(r.get("time", "1500"), r.get("time", "3:00 PM ET")),
            "source":   "usda_nass",
            "detail":   "USDA NASS release",
        })
    return rows


def _from_yaml_wasde(cfg: dict) -> list:
    rows = []
    for w in cfg.get("wasde_2026", []):
        rows.append({
            "date":     pd.Timestamp(w["date"]),
            "event":    "WASDE (World Agricultural Supply & Demand Estimates)",
            "category": "grains",
            "time_et":  _TIME_LABEL.get(w.get("time", "PFEI_NOON"), "12:00 PM ET"),
            "source":   "wasde",
            "detail":   "USDA WAOB — released with Crop Production",
        })
    return rows


def _generate_eia_weekly(start: pd.Timestamp, end: pd.Timestamp) -> list:
    """
    EIA publishes:
      • Weekly Petroleum Status — Wednesdays 10:30 AM ET
      • Weekly Natural Gas Storage — Thursdays 10:30 AM ET
    Both shift one weekday later when a federal holiday falls on or
    before the normal release day (Mon-Tue affects Wed/Thu).  For
    simplicity we generate the canonical weekday and let the user
    cross-check on holiday weeks.
    """
    rows  = []
    d = start
    while d <= end:
        if d.weekday() == 2:   # Wednesday
            rows.append({
                "date":     d,
                "event":    "EIA Weekly Petroleum Status",
                "category": "energy",
                "time_et":  "10:30 AM ET",
                "source":   "eia",
                "detail":   "Crude/distillate/gasoline inventories",
            })
        elif d.weekday() == 3: # Thursday
            rows.append({
                "date":     d,
                "event":    "EIA Weekly Natural Gas Storage",
                "category": "energy",
                "time_et":  "10:30 AM ET",
                "source":   "eia",
                "detail":   "Working gas in underground storage",
            })
        d += timedelta(days=1)
    return rows


def _generate_cot_weekly(start: pd.Timestamp, end: pd.Timestamp) -> list:
    """CFTC COT report — Fridays 3:30 PM ET as of prior Tuesday."""
    rows = []
    d = start
    while d <= end:
        if d.weekday() == 4:   # Friday
            rows.append({
                "date":     d,
                "event":    "CFTC COT Release",
                "category": "cot",
                "time_et":  "3:30 PM ET",
                "source":   "cftc",
                "detail":   "Disaggregated COT — positions as of prior Tuesday",
            })
        d += timedelta(days=1)
    return rows


# ── Public API ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def list_events(start_date: date = None, end_date: date = None,
                categories: tuple = None) -> pd.DataFrame:
    """
    Return all events between start_date and end_date (inclusive).
    Defaults: from today to one year from today.
    `categories` filters by the CATEGORIES keys (None = include all).
    """
    today = pd.Timestamp(date.today())
    start = pd.Timestamp(start_date) if start_date else today
    end   = pd.Timestamp(end_date)   if end_date   else (today + pd.DateOffset(years=1))

    cfg  = _load_config()
    rows = []
    rows.extend(_from_yaml_holidays(cfg))
    rows.extend(_from_yaml_usda(cfg))
    rows.extend(_from_yaml_wasde(cfg))
    rows.extend(_generate_eia_weekly(start, end))
    rows.extend(_generate_cot_weekly(start, end))

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df[(df["date"] >= start) & (df["date"] <= end)]

    if categories:
        cats = set(categories)
        df = df[df["category"].isin(cats)]

    return df.sort_values(["date", "category", "event"]).reset_index(drop=True)


def upcoming_events(n: int = 20, categories: tuple = None) -> pd.DataFrame:
    """Next `n` events starting today (or up to 30 days out, whichever first)."""
    today = date.today()
    df = list_events(today, today + timedelta(days=60), categories=categories)
    return df.head(n).reset_index(drop=True)


def month_grid(year: int, month: int, categories: tuple = None) -> dict:
    """
    Return {date: [event-row-dict, ...]} for every day of the given month
    that has at least one event.  Used by the calendar page to render dots
    on each day in the month grid.
    """
    start = pd.Timestamp(year=year, month=month, day=1)
    if month == 12:
        end = pd.Timestamp(year=year + 1, month=1,         day=1) - pd.Timedelta(days=1)
    else:
        end = pd.Timestamp(year=year,     month=month + 1, day=1) - pd.Timedelta(days=1)

    df = list_events(start, end, categories=categories)
    grid = {}
    for _, row in df.iterrows():
        d = row["date"].date()
        grid.setdefault(d, []).append(row.to_dict())
    return grid
