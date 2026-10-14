"""Hourly weather from Open-Meteo's public archive of forecasts.

Two things are taken for each hour: temperature and precipitation. The archive stitches together the
forecasts that were issued at the time, so a value for an hour is close to what a forecaster would have said
a few hours ahead. Used as "the forecast for the target hour", it is a little better than a real 24-hour
forecast would have been, and that is stated wherever the weather features are evaluated.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime

from depot_twin.data import fetch

ARCHIVE_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PLACES = {
    "san_francisco": (37.77, -122.42, "America/Los_Angeles"),
    "chicago": (41.88, -87.63, "America/Chicago"),
    "new_york": (40.75, -73.98, "America/New_York"),
    "oakland": (37.76, -122.20, "America/Los_Angeles"),
}


def url(place: str | tuple[float, float, str], first: date, last: date) -> str:
    """Return the archive URL for a date range at a named place or at (latitude, longitude, time zone)."""
    latitude, longitude, zone = PLACES[place] if isinstance(place, str) else place
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": first.isoformat(),
        "end_date": last.isoformat(),
        "hourly": "temperature_2m,precipitation",
        "timezone": zone,
    }
    return f"{ARCHIVE_URL}?{urllib.parse.urlencode(params)}"


def parse(text: str) -> list[dict]:
    """Parse the archive's response into rows of local time, temperature (C) and precipitation (mm)."""
    hourly = json.loads(text)["hourly"]
    rows = zip(hourly["time"], hourly["temperature_2m"], hourly["precipitation"], strict=True)
    return [
        {"time": datetime.fromisoformat(time), "temperature_c": temperature, "precipitation_mm": rain or 0.0}
        for time, temperature, rain in rows
        if temperature is not None
    ]


def fetch_hours(place: str | tuple[float, float, str], first: date, last: date) -> list[dict]:
    """Download once and return hourly weather for a date range, at a named place or a point."""
    label = place if isinstance(place, str) else f"{place[0]:.2f}_{place[1]:.2f}"
    path = fetch(url(place, first, last), f"weather/{label}_{first}_{last}.json", timeout=120.0)
    return parse(path.read_text())
