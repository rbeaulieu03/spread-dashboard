"""
noaa.py
-------
NOAA macro-awareness provider.

Surfaces three data products on the Weather page's "NOAA Macro" tab:

  1. Storm Prediction Center (SPC) outlooks — Day 1-8 severe weather
     risk maps (categorical convective outlooks).
  2. US Drought Monitor (USDM) — weekly drought classification map +
     change comparisons (1 / 4 / 12 weeks ago).
  3. NCEI Climate at a Glance (CAG) — national year-to-date temperature
     and precipitation anomaly values for context against history.

The SPC and USDM products are served as stable PNG/GIF URLs that update
in place on their respective schedules, so we just embed them via
st.image — no auth, no rate limit to worry about.

The NCEI CAG endpoint returns a clean JSON time series for a given
national parameter + timescale, also without auth.  We cache it for
six hours (it updates monthly).

All sources are public US-government data, free to use.
"""

import requests
import streamlit as st
from datetime import date


# ── Storm Prediction Center (SPC) — convective outlooks ──────────────────────
# Days 1-3 are the most-watched outlooks for severe weather (hail,
# tornado, damaging wind risk).  Day 4-8 is a smoothed probability map.
SPC_OUTLOOKS = {
    "Day 1 — Categorical":   "https://www.spc.noaa.gov/products/outlook/day1otlk.gif",
    "Day 2 — Categorical":   "https://www.spc.noaa.gov/products/outlook/day2otlk.gif",
    "Day 3 — Categorical":   "https://www.spc.noaa.gov/products/outlook/day3otlk.gif",
    "Day 4-8 — Probabilistic": "https://www.spc.noaa.gov/products/exper/day4-8/day48prob.gif",
}

# Per-hazard maps available on Day 1 (separate hail / wind / tornado).
SPC_DAY1_HAZARDS = {
    "Day 1 — Tornado":  "https://www.spc.noaa.gov/products/outlook/day1probotlk_torn.gif",
    "Day 1 — Hail":     "https://www.spc.noaa.gov/products/outlook/day1probotlk_hail.gif",
    "Day 1 — Wind":     "https://www.spc.noaa.gov/products/outlook/day1probotlk_wind.gif",
}


# ── US Drought Monitor (USDM) ────────────────────────────────────────────────
# Released every Thursday at 8:30 AM ET, current as of the prior Tuesday.
# "trd" = transparent classification map, "None" = solid version.
USDM_MAPS = {
    "Current week":   "https://droughtmonitor.unl.edu/data/png/current/current_conus_trd.png",
    "Change vs 1 wk ago":  "https://droughtmonitor.unl.edu/data/png/current/current_conus_chg1.png",
    "Change vs 4 wks ago": "https://droughtmonitor.unl.edu/data/png/current/current_conus_chg4.png",
    "Change vs 12 wks ago": "https://droughtmonitor.unl.edu/data/png/current/current_conus_chg12.png",
}


# ── NCEI Climate at a Glance (CAG) ───────────────────────────────────────────
# JSON endpoints for the contiguous US (national, code "110"):
#   Parameter codes:  1 = Average Temperature, 2 = Precipitation
#   Timescale codes:  12 = year-to-date, 1 = monthly, etc.
# URL pattern: /cag/national/time-series/{location}/{param}/{timescale}/{start}-{end}.json
_CAG_BASE = "https://www.ncei.noaa.gov/cag/national/time-series"


def _cag_url(param: int, year: int) -> str:
    """
    Build a CAG JSON URL for national-level data for one calendar year.
    Timescale 12 = year-to-date through the most recent complete month.
    """
    return f"{_CAG_BASE}/110/{param}/12/{year}-{year}.json"


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def fetch_national_anomaly(year: int = None) -> tuple:
    """
    Pull YTD national temperature and precipitation anomalies from NCEI
    Climate at a Glance.

    Returns (dict, status_message) where dict has:
        year, ytd_temp_value_f, ytd_temp_anomaly_f, ytd_temp_rank,
        ytd_precip_value_in, ytd_precip_anomaly_in, ytd_precip_rank,
        through_month  (e.g. "April 2026")

    Empty dict + error message on failure.
    """
    yr = year or date.today().year

    out = {
        "year":                    yr,
        "ytd_temp_value_f":        None,
        "ytd_temp_anomaly_f":      None,
        "ytd_temp_rank":           None,
        "ytd_precip_value_in":     None,
        "ytd_precip_anomaly_in":   None,
        "ytd_precip_rank":         None,
        "through_month":           None,
    }

    msgs = []
    try:
        # Temperature (param=1)
        t_resp = requests.get(_cag_url(1, yr), timeout=15)
        t_resp.raise_for_status()
        t_data = t_resp.json().get("data", {})
        # Latest available month is the highest YYYYMM key
        if t_data:
            latest_key = max(t_data.keys())
            row = t_data[latest_key]
            out["ytd_temp_value_f"]   = float(row.get("value"))   if row.get("value")   else None
            out["ytd_temp_anomaly_f"] = float(row.get("anomaly")) if row.get("anomaly") else None
            out["ytd_temp_rank"]      = row.get("rank")
            # Key format is YYYYMM — derive a friendly month name
            month_idx = int(latest_key[-2:])
            month_names = ["", "January", "February", "March", "April",
                           "May", "June", "July", "August", "September",
                           "October", "November", "December"]
            if 1 <= month_idx <= 12:
                out["through_month"] = f"{month_names[month_idx]} {yr}"
        msgs.append(f"temp OK ({len(t_data)} months)")
    except Exception as e:
        msgs.append(f"temp FAILED: {e}")

    try:
        # Precipitation (param=2)
        p_resp = requests.get(_cag_url(2, yr), timeout=15)
        p_resp.raise_for_status()
        p_data = p_resp.json().get("data", {})
        if p_data:
            latest_key = max(p_data.keys())
            row = p_data[latest_key]
            out["ytd_precip_value_in"]   = float(row.get("value"))   if row.get("value")   else None
            out["ytd_precip_anomaly_in"] = float(row.get("anomaly")) if row.get("anomaly") else None
            out["ytd_precip_rank"]       = row.get("rank")
        msgs.append(f"precip OK ({len(p_data)} months)")
    except Exception as e:
        msgs.append(f"precip FAILED: {e}")

    status = " | ".join(msgs) if msgs else "no data returned"
    return out, status


# ── Convenience: pre-canned report-page URLs ─────────────────────────────────
LINKS = {
    "NCEI Monthly U.S. Climate Summary":
        "https://www.ncei.noaa.gov/access/monitoring/monthly-report/national/",
    "Drought Monitor home":
        "https://droughtmonitor.unl.edu/",
    "Storm Prediction Center home":
        "https://www.spc.noaa.gov/",
    "Climate Prediction Center home":
        "https://www.cpc.ncep.noaa.gov/",
}
