"""
config.py
---------
Loads and provides access to the spread configuration in config/spreads.yaml.

Everything about which commodities and spreads exist lives in the YAML file.
This module just makes it easy for the rest of the app to read that file.
"""

import yaml
import os

# Build an absolute path to the config folder regardless of where the
# script is run from. This file lives at:  spread-dashboard/src/config.py
# So two levels up (src → project root) + "config" gets us there.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH  = os.path.join(_PROJECT_ROOT, "config", "spreads.yaml")


def load_spreads_config() -> dict:
    """Load the full spreads.yaml and return it as a Python dict."""
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_commodity_names(config: dict) -> list:
    """Return a list of commodity names, e.g. ['Corn', 'Wheat', ...]"""
    return list(config["commodities"].keys())


def get_commodity_info(config: dict, commodity: str) -> dict:
    """Return the full config block for one commodity."""
    return config["commodities"][commodity]


def get_spreads_for_commodity(config: dict, commodity: str) -> list:
    """Return the list of spread definitions for one commodity."""
    return config["commodities"][commodity]["spreads"]


def get_spread_by_id(config: dict, commodity: str, spread_id: str) -> dict:
    """Look up a specific spread definition by its id string."""
    spreads = get_spreads_for_commodity(config, commodity)
    return next((s for s in spreads if s["id"] == spread_id), None)
