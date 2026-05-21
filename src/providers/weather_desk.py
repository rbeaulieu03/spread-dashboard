"""
weather_desk.py
---------------
Tyson Weather Desk provider (xweather subscription, Images API).

Returns PNG map URLs for the US (and regional subsets) covering forecast
Tmax/Tmin/Precip, observed Tmax/Tmin/Precip, drought, radar, satellite,
and forecast deviation maps.  Complementary to src/providers/weather.py
(NWS point forecasts).

Auth — add to .streamlit/secrets.toml on the dashboard machine:

    [weather_desk]
    username = "..."
    password = "..."

Rate limit: 10 requests per minute per account.  List endpoint cached
30 minutes.

API docs:
    https://api.weatherdesk.xweather.com/<tenant>/documentation/realtime/v1/main
"""

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime


# ── Tenant configuration ──────────────────────────────────────────────────────
_TENANT_ID = "a0387999-27e1-45b6-84fc-d60bc36a29fb"
_API_ROOT  = f"https://api.weatherdesk.xweather.com/{_TENANT_ID}"
_IMG_ROOT  = f"https://img.weatherdesk.xweather.com/{_TENANT_ID}/products/v1/realtime/maps"

_LIST_ENDPOINT = "/services/realtime/v1/main"


# ── Param catalog (display name → API code) ──────────────────────────────────
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


# ── Region bounding boxes (for plant overlay) ────────────────────────────────
# Approximate (lon_min, lat_min, lon_max, lat_max) for each xweather region.
# Equirectangular approximations of the Lambert Conformal Conic maps —
# alignment is roughly accurate near the region center and degrades slightly
# at the edges.  Tweak if Tyson markers drift visibly from their true spots.
REGION_BOUNDS = {
    "USUS": (-127.0, 22.0, -65.0,  50.0),
    "USMW": (-100.0, 36.0, -78.0,  50.0),
    "USNC": (-110.0, 33.0, -89.0,  50.0),
    "USSC": (-110.0, 26.0, -85.0,  40.0),
    "USNW": (-127.0, 38.0, -100.0, 50.0),
    "USSW": (-125.0, 30.0, -100.0, 42.0),
    "USNE": ( -85.0, 38.0,  -65.0, 48.0),
    "USSE": ( -95.0, 25.0,  -75.0, 38.0),
}


# ── Tyson plant locations (for overlay markers) ──────────────────────────────
TYSON_PLANTS = {
    "Springdale, AR (HQ / Poultry)":   {"lat": 36.1867, "lon":  -94.1288, "type": "HQ"},
    "Garden City, KS (Beef)":          {"lat": 37.9716, "lon": -100.8727, "type": "Beef"},
    "Holcomb, KS (Beef)":              {"lat": 37.9928, "lon": -100.9893, "type": "Beef"},
    "Amarillo, TX (Beef)":             {"lat": 35.2220, "lon": -101.8313, "type": "Beef"},
    "Dakota City, NE (Beef)":          {"lat": 42.4150, "lon":  -96.4205, "type": "Beef"},
    "Lexington, NE (Beef)":            {"lat": 40.7806, "lon":  -99.7430, "type": "Beef"},
    "Joslin, IL (Beef)":               {"lat": 41.5800, "lon":  -90.3300, "type": "Beef"},
    "Pasco, WA (Beef)":                {"lat": 46.2396, "lon": -119.1006, "type": "Beef"},
    "Storm Lake, IA (Pork)":           {"lat": 42.6411, "lon":  -95.2098, "type": "Pork"},
    "Logansport, IN (Pork)":           {"lat": 40.7542, "lon":  -86.3567, "type": "Pork"},
    "Council Bluffs, IA (Pork)":       {"lat": 41.2619, "lon":  -95.8608, "type": "Pork"},
    "Waterloo, IA (Pork)":             {"lat": 42.4928, "lon":  -92.3426, "type": "Pork"},
    "Madison, NE (Pork)":              {"lat": 41.8278, "lon":  -97.4570, "type": "Pork"},
    "Columbus Junction, IA (Pork)":    {"lat": 41.2811, "lon":  -91.3624, "type": "Pork"},
    "Vernon, TX (Beef)":               {"lat": 34.1547, "lon":  -99.2657, "type": "Beef"},
}

PLANT_TYPE_COLORS = {
    "Beef":    "#DC143C",   # crimson
    "Pork":    "#FF8C00",   # orange
    "Poultry": "#4CAF7D",   # green
    "HQ":      "#0891B2",   # deep cyan
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
    u, p = _load_credentials()
    return bool(u and p)


# ── List endpoint ────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 30, show_spinner=False)
def list_images(param_code: str, region_code: str, limit: int = 1) -> tuple:
    """
    Query the Weather Desk Images API for the most recent N images.
    Returns (image_urls, status_message).
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

    paths = payload.get("images") or [it.get("path") for it in payload.get("Items", [])]
    paths = [p for p in paths if p]

    if not paths:
        return [], (
            f"Weather Desk returned no images for param={param_code} "
            f"region={region_code} (Count={payload.get('Count', 0)})"
        )

    urls = [_IMG_ROOT + path for path in paths]

    valid_time = None
    items = payload.get("Items") or []
    if items:
        vt = items[0].get("valid_time")
        if isinstance(vt, (int, float)):
            valid_time = datetime.fromtimestamp(vt / 1000)

    when = f" (valid {valid_time.strftime('%Y-%m-%d %H:%M UTC')})" if valid_time else ""
    return urls, f"OK — {len(urls)} image(s){when}"


def get_latest_image_url(param_code: str, region_code: str) -> tuple:
    urls, msg = list_images(param_code, region_code, limit=1)
    return (urls[0] if urls else None), msg


# ── Plotly overlay helper ────────────────────────────────────────────────────

def build_image_overlay_figure(image_url: str, region_code: str,
                                plants: dict = None) -> go.Figure:
    """
    Render a Weather Desk PNG as a Plotly figure background with Tyson
    plant markers placed at their lat/lon coordinates on top.

    The image is positioned in plain (lon, lat) axes using
    REGION_BOUNDS[region_code] as the bounding box.  Markers within
    those bounds are scattered as colored dots labeled with the plant
    name.  Aspect ratio is locked so the image is not distorted.

    Useful for "is this plant in the storm path / heat dome / drought
    zone" checks.  Alignment is approximate — see REGION_BOUNDS comment.
    """
    if plants is None:
        plants = TYSON_PLANTS

    bounds = REGION_BOUNDS.get(region_code, REGION_BOUNDS["USUS"])
    lon_min, lat_min, lon_max, lat_max = bounds

    fig = go.Figure()

    # Background image (positioned by lon/lat).
    fig.add_layout_image(dict(
        source = image_url,
        xref   = "x",  yref = "y",
        x      = lon_min,
        y      = lat_max,        # top-left corner
        sizex  = lon_max - lon_min,
        sizey  = lat_max - lat_min,
        sizing = "stretch",
        layer  = "below",
        opacity = 1.0,
    ))

    # Filter plants to those within the region bounds.
    in_view = {
        name: meta for name, meta in plants.items()
        if lon_min <= meta["lon"] <= lon_max and lat_min <= meta["lat"] <= lat_max
    }

    # Group by plant type so each group gets its own legend entry/color.
    by_type = {}
    for name, meta in in_view.items():
        by_type.setdefault(meta["type"], []).append((name, meta["lat"], meta["lon"]))

    for plant_type, items in by_type.items():
        names = [n for n, _, _ in items]
        lats  = [la for _, la, _ in items]
        lons  = [lo for _, _, lo in items]
        fig.add_trace(go.Scatter(
            x         = lons,
            y         = lats,
            mode      = "markers",
            name      = plant_type,
            text      = names,
            marker    = dict(
                size  = 11,
                color = PLANT_TYPE_COLORS.get(plant_type, "#374151"),
                line  = dict(width=1.5, color="#FFFFFF"),
                symbol = "circle",
            ),
            hovertemplate = "<b>%{text}</b><br>%{y:.3f}, %{x:.3f}<extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor = "#FFFFFF",
        plot_bgcolor  = "#FFFFFF",
        margin        = dict(l=0, r=0, t=10, b=0),
        height        = 600,
        showlegend    = True,
        legend        = dict(
            x=0.01, y=0.99, xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#D1D5DB", borderwidth=1,
            font=dict(size=11, color="#374151"),
        ),
        xaxis = dict(range=[lon_min, lon_max], visible=False),
        yaxis = dict(range=[lat_min, lat_max], visible=False,
                     scaleanchor="x", scaleratio=1.0),
    )
    return fig
