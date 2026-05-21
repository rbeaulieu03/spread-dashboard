"""
weather_desk.py
---------------
Tyson Weather Desk provider (xweather subscription, Images API).

What this is
------------
Tyson's Weather Desk subscription exposes a Real-Time Weather IMAGES API
that returns PNG map URLs for the US (and regional subsets) covering
forecast Tmax/Tmin/Precip, observed Tmax/Tmin/Precip, drought, radar,
satellite, and forecast deviation maps.

This provider is COMPLEMENTARY to src/providers/weather.py (NWS), not a
drop-in replacement. NWS gives per-location numeric forecasts; Weather
Desk gives regional images for the macro view.

Auth
----
Add the Tyson Weather Desk credentials to .streamlit/secrets.toml on
the machine running the dashboard (NEVER commit secrets to git):

    [weather_desk]
    username = "..."
    password = "..."

If those keys are missing, every call returns an empty list with a
status message.  The Data Status page surfaces this clearly.

API DOCS
--------
    https://api.weatherdesk.xweather.com/a0387999-27e1-45b6-84fc-d60bc36a29fb/
        documentation/realtime/v1/main

Endpoint summary (from those docs):
    GET /a0387999.../services/realtime/v1/main
        ?param=<image-type>&region=<region-code>&limit=<n>

    Response:
        {"Count": n, "Items": [{...}], "images": ["/satvis/usus/...png", ...]}

    Image retrieval (build a full URL from each `images[]` path):
        https://img.weatherdesk.xweather.com/a0387999.../products/v1/realtime/maps/<path>

Rate limit: 10 requests per minute per account.  We cache 30 minutes
because the forecast/obs maps refresh on the order of hours, not minutes.
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime


# ── Tenant configuration ──────────────────────────────────────────────────────
_TENANT_ID = "a0387999-27e1-45b6-84fc-d60bc36a29fb"
_API_ROOT  = f"https://api.weatherdesk.xweather.com/{_TENANT_ID}"
_IMG_ROOT  = f"https://img.weatherdesk.xweather.com/{_TENANT_ID}/products/v1/realtime/maps"

_LIST_ENDPOINT = "/services/realtime/v1/main"


# ── Param catalog (display name → API code) ──────────────────────────────────
# Grouped by category for UI ordering.  Pulled directly from the
# Getting Started table in the API docs.
IMAGE_PARAMS = {
    "Current Conditions": {
        "Temperature":          "temp",
        "Dew Point":            "dewp",
        "Apparent Temperature": "tapr",
        "Wind Speed / Dir":     "wind",
    },
    "Forecast (Today)": {
        "Today Tmax":   "tmaxfcstd00",
        "Today Tmin":   "tminfcstd00",
        "Today Precip": "prcpfcstd00",
    },
    "Forecast (Tomorrow)": {
        "Tomorrow Tmax":   "tmaxfcstd01",
        "Tomorrow Tmin":   "tminfcstd01",
        "Tomorrow Precip": "prcpfcstd01",
    },
    "Observed (Yesterday)": {
        "Yesterday Tmax":   "tmaxobsm01",
        "Yesterday Tmin":   "tminobsm01",
        "Yesterday Precip": "prcpobsm01",
    },
    "Change vs Prior": {
        "24hr Temp Change":            "tempdiff24hr",
        "1hr Temp Change":             "tempdiff1hr",
        "24hr Apparent Temp Change":   "taprdiff24hr",
        "24hr Dew Point Change":       "dewpdiff24hr",
        "Temp Dev from AM Forecast":   "tempdiffamfcst",
        "Temp Dev from Yest AM Fcst":  "tempdiffamfcstyest",
    },
    "Imagery": {
        "Radar":      "radar",
        "Visible":    "satvis",
        "Infrared":   "satir",
        "Water Vapor": "satwv",
    },
    "Other": {
        "Drought":    "drought",
        "Snow Depth": "snowdepth",
    },
}


# ── Region catalog (display name → API code) ─────────────────────────────────
IMAGE_REGIONS = {
    "United States":      "USUS",
    "Midwest":            "USMW",
    "N. Central (Plains)": "USNC",
    "S. Central":         "USSC",
    "Northwest":          "USNW",
    "Southwest":          "USSW",
    "Northeast":          "USNE",
    "Southeast":          "USSE",
}


# ── Credential plumbing ──────────────────────────────────────────────────────

def _load_credentials() -> tuple:
    """
    Return (username, password) from Streamlit secrets, or (None, None)
    if the secrets section is missing.
    """
    try:
        section = st.secrets["weather_desk"]
        return section.get("username"), section.get("password")
    except (KeyError, AttributeError, FileNotFoundError):
        return None, None


def has_credentials() -> bool:
    """Quick precondition check — used by the Data Status page."""
    u, p = _load_credentials()
    return bool(u and p)


# ── List endpoint ────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 30, show_spinner=False)
def list_images(param_code: str, region_code: str, limit: int = 1) -> tuple:
    """
    Query the Weather Desk Images API for the most recent N images of a
    given param/region combo.

    Returns (image_urls, status_message) where image_urls is a list of
    fully-qualified https URLs ready for st.image().  Empty list on
    failure.

    Cached 30 minutes — the forecast/obs maps regenerate on the hour or
    less frequently, well within the 10-req/min rate limit.
    """
    u, p = _load_credentials()
    if not (u and p):
        return [], (
            "Weather Desk credentials not configured. "
            "Add a [weather_desk] section with username/password to "
            ".streamlit/secrets.toml."
        )

    url    = _API_ROOT + _LIST_ENDPOINT
    params = {"param": param_code, "region": region_code, "limit": int(limit)}

    try:
        resp = requests.get(url, params=params, auth=(u, p), timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except requests.HTTPError as e:
        return [], f"Weather Desk HTTP {resp.status_code}: {e}"
    except Exception as e:
        return [], f"Weather Desk error: {e}"

    # The docs show two equivalent shapes — a bare `images` array and an
    # `Items[].path` list.  Prefer `images` since it's already a flat list.
    paths = payload.get("images") or [it.get("path") for it in payload.get("Items", [])]
    paths = [p for p in paths if p]  # drop None

    if not paths:
        return [], (
            f"Weather Desk returned no images for param={param_code} "
            f"region={region_code} (Count={payload.get('Count', 0)})"
        )

    urls = [_IMG_ROOT + path for path in paths]

    # Pull the most recent valid_time so the UI can show "as of …"
    valid_time = None
    items = payload.get("Items") or []
    if items:
        vt = items[0].get("valid_time")
        if isinstance(vt, (int, float)):
            # API returns epoch milliseconds
            valid_time = datetime.fromtimestamp(vt / 1000)

    when = f" (valid {valid_time.strftime('%Y-%m-%d %H:%M UTC')})" if valid_time else ""
    return urls, f"OK — {len(urls)} image(s){when}"


def get_latest_image_url(param_code: str, region_code: str) -> tuple:
    """Convenience wrapper — returns (single URL or None, status)."""
    urls, msg = list_images(param_code, region_code, limit=1)
    return (urls[0] if urls else None), msg
