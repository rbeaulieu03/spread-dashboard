"""
noaa.py
-------
NOAA macro-awareness provider — surfaces three data products on the
Weather page's "NOAA Macro" tab:

  1. Storm Prediction Center (SPC) — Day 1-8 severe weather outlooks
  2. US Drought Monitor (USDM) — current map + change comparisons
  3. NCEI Climate at a Glance (CAG) — link-out to NCEI's portal

Why we scrape SPC instead of hard-coding URLs:
  SPC publishes outlooks as timestamped images (e.g. day1otlk_2000.png)
  that change every few hours.  Hard-coded URLs go stale.  This module
  fetches each outlook's HTML landing page once per hour and pulls the
  current image src out of the markup so the dashboard always shows
  the latest.

Why we link-out for NCEI:
  NCEI restructured the Climate at a Glance JSON API multiple times in
  the last year (param IDs went from numeric → string, path moved from
  /cag/ → /access/monitoring/, timescale segments changed shape).
  Rather than chase the moving target, we link users to the portal where
  the data displays correctly without us needing to track schema changes.
"""

import re
import requests
import streamlit as st
from datetime import date


# ── Storm Prediction Center (SPC) — convective outlooks ──────────────────────

_SPC_USER_AGENT = "spread-dashboard (raymond.beaulieu@tyson.com)"
_SPC_ROOT       = "https://www.spc.noaa.gov/products/outlook"


def _spc_page_url(day: int) -> str:
    """Stable URL of the human-readable outlook landing page."""
    return f"{_SPC_ROOT}/day{day}otlk.html"


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _resolve_spc_image_url(day: int, hazard: str = "cat") -> str:
    """
    Scrape the SPC Day N landing page to find the current image URL.

    `hazard` selects which image to look for:
        "cat"  — categorical outlook (the default colored risk map)
        "torn" — Day 1 tornado probability
        "hail" — Day 1 hail probability
        "wind" — Day 1 wind probability

    Returns a fully-qualified URL.  Falls back to the non-timestamped
    "current" filename if the scrape fails or no match is found.
    """
    page = _spc_page_url(day)
    try:
        resp = requests.get(page, timeout=10, headers={"User-Agent": _SPC_USER_AGENT})
        resp.raise_for_status()

        # Patterns SPC uses today (timestamped, e.g. day1otlk_2000.png).
        # We allow the timestamp digits to vary; matching the leading
        # token + four-digit time + the .png/.gif suffix.
        if hazard == "cat":
            pattern = rf"day{day}otlk_\d{{4}}\.(?:png|gif)"
        else:
            pattern = rf"day{day}probotlk_{hazard}_\d{{4}}\.(?:png|gif)"

        match = re.search(pattern, resp.text)
        if match:
            return f"{_SPC_ROOT}/{match.group(0)}"
    except Exception:
        pass

    # Fallback: non-timestamped filename (works on some legacy clients
    # if SPC still serves an alias; otherwise this URL may 404).
    if hazard == "cat":
        return f"{_SPC_ROOT}/day{day}otlk.png"
    return f"{_SPC_ROOT}/day{day}probotlk_{hazard}.gif"


def get_spc_outlook(day: int, hazard: str = "cat") -> dict:
    """Return {image, page} for a given SPC outlook day + hazard slice."""
    return {
        "image": _resolve_spc_image_url(day, hazard),
        "page":  _spc_page_url(day),
    }


# Day 4-8 is served at a different path under /exper/ and uses a stable
# filename, so we keep that as a static entry.
SPC_DAY_4_8 = {
    "image": "https://www.spc.noaa.gov/products/exper/day4-8/day48prob.gif",
    "page":  "https://www.spc.noaa.gov/products/exper/day4-8/",
}


# ── US Drought Monitor (USDM) ────────────────────────────────────────────────
# Released every Thursday at 8:30 AM ET, current as of the prior Tuesday.
# These filenames update in place each week, so no scraping needed.
USDM_MAPS = {
    "Current week":         "https://droughtmonitor.unl.edu/data/png/current/current_conus_trd.png",
    "Change vs 1 wk ago":   "https://droughtmonitor.unl.edu/data/png/current/current_conus_chg1.png",
    "Change vs 4 wks ago":  "https://droughtmonitor.unl.edu/data/png/current/current_conus_chg4.png",
    "Change vs 12 wks ago": "https://droughtmonitor.unl.edu/data/png/current/current_conus_chg12.png",
}


# ── NCEI Climate at a Glance — link-outs only ────────────────────────────────
# Live data via JSON kept breaking when NCEI re-shaped the API.  We
# surface deep-links into their interactive portal instead — the user
# clicks through to view the current YTD anomaly numbers / maps directly.

NCEI_LINKS = {
    "National YTD Temperature Anomaly":
        "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/national/time-series/110/tavg/ytd/12",
    "National YTD Precipitation Anomaly":
        "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/national/time-series/110/pcp/ytd/12",
    "Latest Monthly U.S. Climate Summary":
        "https://www.ncei.noaa.gov/access/monitoring/monthly-report/national/",
    "Climate at a Glance — Mapping Interface":
        "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/national/mapping",
}


# ── Convenience: external landing pages ──────────────────────────────────────
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
