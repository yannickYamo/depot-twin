"""Hourly ride-hail demand from the City of Chicago's public trip records.

Robotaxi operators redact their trip times, and no Bay Area city publishes ride-hail trips by the hour.
Chicago does, so it is the training ground for the demand forecast: what the model learns is how ride-hail
demand moves by hour, weekday, season and holiday. The level is rescaled to the simulated fleet afterwards;
only the shape is taken from here.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from depot_twin.data import USER_AGENT, data_dir

# Trips from 2025 onward. The city's earlier datasets time out on aggregate queries and are not used.
DATASET_URL = "https://data.cityofchicago.org/resource/6dvr-xwnh.json"
FIRST_DAY = date(2025, 1, 1)


def day_url(day: date) -> str:
    """Return the query URL for one day's trip count per hour.

    The query covers a single day because the service answers that in about a second and times out on
    longer spans.
    """
    params = {
        "$select": "date_extract_hh(trip_start_timestamp) as hour, count(*) as trips",
        "$where": f"trip_start_timestamp >= '{day}T00:00:00' and trip_start_timestamp < '{day + timedelta(days=1)}T00:00:00'",
        "$group": "hour",
        "$order": "hour",
    }
    return f"{DATASET_URL}?{urllib.parse.urlencode(params)}"


def parse_day(day: date, text: str) -> list[dict]:
    """Parse one day's response into rows of day, hour and trips."""
    return [{"day": day.isoformat(), "hour": int(row["hour"]), "trips": int(row["trips"])} for row in json.loads(text)]


def _fetch_day(day: date) -> list[dict]:
    request = urllib.request.Request(day_url(day), headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90.0) as response:
                return parse_day(day, response.read().decode())
        except OSError:
            if attempt == 2:
                raise
    return []


def fetch_hours(first: date = FIRST_DAY, last: date | None = None, workers: int = 6) -> list[dict]:
    """Return hourly rows for every day from first to last, fetching only days not already cached."""
    last = last or date.today() - timedelta(days=1)
    cache = data_dir() / "raw" / "chicago" / "hourly.json"
    rows: list[dict] = json.loads(cache.read_text()) if cache.exists() else []
    have = {row["day"] for row in rows}
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    missing = [day for day in days if day.isoformat() not in have]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fetched in pool.map(_fetch_day, missing):
            rows.extend(fetched)
    rows.sort(key=lambda row: (row["day"], row["hour"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return [row for row in rows if first.isoformat() <= row["day"] <= last.isoformat()]
