"""
weather.py
----------
Fetches 7-day point forecasts from the National Weather Service
(api.weather.gov) for commodity-relevant locations across the US grain
belt and Tyson plant / livestock-country sites.

The NWS API requires no auth but expects a descriptive User-Agent.

ANOMALY VS NORMAL
-----------------
NWS gives you the raw forecast.  To express it as "X°F above normal" we
embed a small monthly climate normals table (NOAA NCEI 1991-2020 U.S.
Climate Normals) for each reference location.  This keeps the provider
self-contained and avoids a second API call / token.

Refresh cadence: NOAA publishes new 30-year normals every decade.  Next
expected update: 2031.  Until then, the values below are static.

FUTURE: when the Tyson weather desk subscription is wired in, this
provider can stay the same and a sibling provider can return the same
shape (DataFrame columns: date, tmax, tmin, precip, ...).  The page can
then offer a source toggle.
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta


# Polite User-Agent — NWS rate-limits anonymous clients.
_USER_AGENT = "spread-dashboard (raymond.beaulieu@tyson.com)"
_NWS_ROOT   = "https://api.weather.gov"


# ── Reference locations ──────────────────────────────────────────────────────
GRAIN_LOCATIONS = {
    "Des Moines, IA":   {"lat": 41.5868, "lon": -93.6250, "region": "Central Corn Belt"},
    "Bloomington, IL":  {"lat": 40.4842, "lon": -88.9937, "region": "Eastern Corn Belt"},
    "Lincoln, NE":      {"lat": 40.8136, "lon": -96.7026, "region": "Western Corn Belt"},
    "Sioux Falls, SD":  {"lat": 43.5446, "lon": -96.7311, "region": "Northern Plains"},
    "Wichita, KS":      {"lat": 37.6872, "lon": -97.3301, "region": "HRW Wheat Belt"},
    "Minneapolis, MN":  {"lat": 44.9778, "lon": -93.2650, "region": "HRS Wheat / N Soy"},
    "St. Louis, MO":    {"lat": 38.6270, "lon": -90.1994, "region": "SRW Wheat / S Soy"},
}

LIVESTOCK_LOCATIONS = {
    "Springdale, AR":   {"lat": 36.1867, "lon": -94.1288, "region": "Tyson HQ / Poultry"},
    "Garden City, KS":  {"lat": 37.9716, "lon": -100.8727, "region": "Beef Plant / Fed Cattle"},
    "Amarillo, TX":     {"lat": 35.2220, "lon": -101.8313, "region": "TX Panhandle Cattle"},
    "Dakota City, NE":  {"lat": 42.4150, "lon": -96.4205, "region": "Beef Plant"},
    "Storm Lake, IA":   {"lat": 42.6411, "lon": -95.2098, "region": "Pork Plant"},
    "Logansport, IN":   {"lat": 40.7542, "lon": -86.3567, "region": "Pork Plant"},
}


# ── Monthly climate normals (1991-2020) ──────────────────────────────────────
# Each entry: 12 tuples (tavg_F, precip_in), one per month Jan..Dec.
# Approximate values from the nearest NOAA station to each reference point.
# For exact-station accuracy, replace with NCEI lookup at refresh time.
_CLIMATE_NORMALS = {
    "Des Moines, IA":  [(21.6,1.05),(26.4,1.21),(38.5,2.27),(50.4,3.55),(61.6,4.79),(71.2,4.99),(75.0,4.40),(72.7,4.27),(64.2,3.41),(52.0,2.78),(38.0,1.92),(26.0,1.41)],
    "Bloomington, IL": [(25.7,2.06),(29.7,2.13),(40.7,3.05),(52.4,3.89),(63.1,4.79),(72.5,4.55),(75.6,4.27),(73.6,3.98),(66.3,3.31),(54.0,3.27),(41.3,2.93),(30.2,2.46)],
    "Lincoln, NE":     [(24.5,0.69),(28.7,0.75),(40.3,2.13),(52.0,2.99),(62.7,4.45),(72.8,4.31),(77.4,3.39),(75.2,3.27),(66.4,2.64),(53.7,2.21),(39.0,1.39),(27.7,0.99)],
    "Sioux Falls, SD": [(17.8,0.59),(22.0,0.71),(34.4,1.89),(46.6,2.99),(58.9,3.65),(68.9,4.11),(73.6,3.07),(71.4,2.92),(62.3,2.83),(49.4,2.18),(33.3,1.39),(21.2,0.71)],
    "Wichita, KS":     [(33.3,0.83),(37.7,1.06),(48.4,2.78),(58.7,2.95),(68.4,4.45),(78.4,4.36),(82.7,3.27),(80.9,3.10),(72.3,3.31),(60.0,2.86),(45.9,1.69),(35.8,1.34)],
    "Minneapolis, MN": [(17.9,0.91),(22.3,0.79),(34.7,1.89),(48.0,2.83),(60.4,3.94),(70.1,4.41),(74.5,4.14),(72.2,4.31),(63.4,3.31),(50.4,2.65),(35.1,1.69),(22.6,1.18)],
    "St. Louis, MO":   [(31.5,2.13),(36.0,2.27),(46.6,3.34),(57.4,4.06),(66.9,4.55),(76.0,4.36),(80.1,3.94),(78.2,3.50),(70.5,3.27),(58.5,3.50),(45.7,3.34),(35.1,2.79)],
    "Springdale, AR":  [(37.2,2.84),(41.4,2.93),(50.7,4.61),(59.6,4.65),(68.0,5.71),(75.7,4.49),(80.4,3.81),(79.5,3.50),(71.7,4.21),(60.1,4.61),(48.0,4.06),(39.0,3.46)],
    "Garden City, KS": [(30.9,0.51),(34.7,0.55),(45.0,1.61),(54.3,1.97),(64.4,3.46),(75.0,3.39),(80.2,2.83),(78.5,2.99),(69.7,2.05),(56.3,1.34),(42.6,0.83),(32.5,0.59)],
    "Amarillo, TX":    [(36.1,0.59),(40.4,0.79),(48.7,1.42),(57.5,1.42),(66.2,2.95),(76.0,3.46),(80.0,2.91),(78.4,3.27),(70.4,2.36),(59.2,1.69),(46.4,0.83),(37.6,0.71)],
    "Dakota City, NE": [(20.9,0.71),(25.7,0.79),(37.1,1.97),(49.6,2.91),(61.2,4.13),(71.4,4.45),(75.7,3.46),(73.4,3.39),(64.3,2.91),(51.4,2.30),(36.2,1.42),(24.0,0.91)],
    "Storm Lake, IA":  [(18.5,0.79),(23.2,0.91),(35.5,1.97),(48.0,3.03),(60.0,4.45),(70.0,4.65),(73.7,3.94),(71.4,3.94),(62.7,3.07),(49.7,2.36),(34.7,1.61),(22.5,1.06)],
    "Logansport, IN":  [(25.3,2.36),(28.7,2.13),(39.5,2.99),(51.0,3.78),(62.4,4.49),(71.9,4.41),(75.3,4.21),(73.4,3.46),(66.0,2.99),(53.6,3.31),(41.2,3.27),(30.4,2.79)],
}


# ── NWS API helpers ──────────────────────────────────────────────────────────

@st.cache_data(ttl=3600 * 12, show_spinner=False)
def _resolve_grid(lat: float, lon: float) -> dict:
    """
    Translate a lat/lon to NWS office grid coordinates.

    The /points endpoint changes rarely for any given lat/lon, so we cache
    for 12 hours.  Returns the parsed JSON or raises.
    """
    url  = f"{_NWS_ROOT}/points/{lat},{lon}"
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/geo+json"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=3600 * 1, show_spinner=False)
def _fetch_forecast_periods(forecast_url: str) -> list:
    """
    Fetch the 7-day forecast periods JSON from a resolved /forecast URL.

    Cached for 1 hour — NWS refreshes forecasts every few hours.
    Returns the list of period dicts or raises.
    """
    resp = requests.get(forecast_url, headers={"User-Agent": _USER_AGENT, "Accept": "application/geo+json"}, timeout=15)
    resp.raise_for_status()
    return resp.json()["properties"]["periods"]


def fetch_location_forecast(location_name: str, lat: float, lon: float) -> tuple:
    """
    Pull a 7-day forecast for a single (lat, lon) and return a daily
    summary DataFrame plus a status string.

    DataFrame columns:
        date            : ISO date (calendar day)
        tmax_f, tmin_f  : daily high / low °F
        precip_prob_max : max probability of precip (%) across that day's periods
        short_forecast  : the daytime narrative ("Partly cloudy", etc.)
    """
    try:
        meta = _resolve_grid(lat, lon)
        fc_url = meta["properties"]["forecast"]
        periods = _fetch_forecast_periods(fc_url)
    except Exception as e:
        return pd.DataFrame(), f"NWS error for {location_name}: {e}"

    # Period objects come in 12-hour blocks alternating day / night.
    # Roll them up to one row per calendar date.
    daily = {}
    for p in periods:
        # startTime e.g. "2026-05-19T06:00:00-05:00"
        start_dt = pd.to_datetime(p["startTime"])
        d = start_dt.date()
        temp     = p.get("temperature")
        is_day   = p.get("isDaytime", True)
        pop_obj  = p.get("probabilityOfPrecipitation") or {}
        pop_val  = pop_obj.get("value")
        short_fc = p.get("shortForecast", "")

        row = daily.setdefault(d, {"tmax_f": None, "tmin_f": None,
                                   "precip_prob_max": None, "short_forecast": ""})
        if temp is not None:
            if is_day:
                row["tmax_f"] = temp
                row["short_forecast"] = short_fc
            else:
                row["tmin_f"] = temp
        if pop_val is not None:
            if row["precip_prob_max"] is None or pop_val > row["precip_prob_max"]:
                row["precip_prob_max"] = pop_val

    if not daily:
        return pd.DataFrame(), f"No forecast periods returned for {location_name}"

    df = pd.DataFrame.from_dict(daily, orient="index").sort_index()
    df.index.name = "date"
    df = df.reset_index()

    return df, f"OK — {len(df)} day forecast"


def fetch_all_forecasts(locations: dict) -> tuple:
    """
    Fetch forecasts for every entry in `locations` (the dict shape used
    in GRAIN_LOCATIONS / LIVESTOCK_LOCATIONS).

    Returns (results_dict, status_dict) where:
        results_dict[name] = DataFrame (may be empty on failure)
        status_dict[name]  = status message string
    """
    results, status = {}, {}
    for name, meta in locations.items():
        df, msg = fetch_location_forecast(name, meta["lat"], meta["lon"])
        results[name] = df
        status[name]  = msg
    return results, status


# ── Climate normals helpers ──────────────────────────────────────────────────

def get_normal(location: str, month: int) -> tuple:
    """
    Return (tavg_F, precip_in_monthly) for the given location and month.
    Returns (None, None) if the location isn't in the normals table.
    """
    entry = _CLIMATE_NORMALS.get(location)
    if not entry or not (1 <= month <= 12):
        return None, None
    return entry[month - 1]


def compute_anomaly(forecast_df: pd.DataFrame, location: str) -> dict:
    """
    Roll the multi-day NWS forecast into a single anomaly summary
    relative to the monthly climate normal for that location.

    Returns a dict:
        avg_temp_f          : mean of (tmax+tmin)/2 over forecast horizon
        normal_temp_f       : monthly normal TAVG for the dominant month
        temp_anomaly_f      : avg_temp_f - normal_temp_f
        total_precip_prob   : mean precip probability across days (%)
        normal_precip_in    : monthly normal PRCP for dominant month
        horizon_days        : number of forecast days used
    All keys map to None if data is missing.
    """
    if forecast_df.empty:
        return {k: None for k in (
            "avg_temp_f", "normal_temp_f", "temp_anomaly_f",
            "total_precip_prob", "normal_precip_in", "horizon_days",
        )}

    df = forecast_df.copy()
    df["date"]    = pd.to_datetime(df["date"])
    df["tavg_f"]  = (df["tmax_f"] + df["tmin_f"]) / 2

    avg_temp = df["tavg_f"].mean(skipna=True)
    avg_pop  = df["precip_prob_max"].mean(skipna=True)

    # Pick the month that covers the most forecast days.
    months    = df["date"].dt.month.tolist()
    dom_month = max(set(months), key=months.count) if months else None

    norm_t, norm_p = get_normal(location, dom_month) if dom_month else (None, None)

    return {
        "avg_temp_f":        round(avg_temp, 1) if pd.notna(avg_temp) else None,
        "normal_temp_f":     norm_t,
        "temp_anomaly_f":    round(avg_temp - norm_t, 1) if (norm_t is not None and pd.notna(avg_temp)) else None,
        "total_precip_prob": round(avg_pop, 0)  if pd.notna(avg_pop)  else None,
        "normal_precip_in":  norm_p,
        "horizon_days":      len(df),
    }
