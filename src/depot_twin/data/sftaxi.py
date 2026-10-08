"""Taxi trips in San Francisco, from the city's open data.

Every taxi company permitted in San Francisco reports each trip to the transportation agency, which
publishes them: start and end time to the second, pickup and drop-off coordinates, distance and fare, in the
public domain. The series runs from December 2022 to May 2024.

It is the demand source for the short-horizon forecasts because it is the right city and fine-grained enough
for a five-minute controller. Its limits are stated wherever it is used: these are taxis, not ride-hail;
they are trips served, not trips requested; and the series stops in May 2024. Two flaws were found in the
feed itself and are handled or reported: exact repeats of records, which are dropped here, and a jump in
reported trips from mid-February 2024 with no change in the number of cabs, which looks like a change in
what is reported and is left in as the kind of shift a forecast has to survive.
"""

from __future__ import annotations

import csv
import urllib.parse
from datetime import date, datetime

from depot_twin.data import fetch

DATASET_URL = "https://data.sf.gov/resource/m8hk-2ipk.csv"
FIRST_MONTH, LAST_MONTH = (2022, 12), (2024, 5)
FIELDS = (
    "start_time_local,trip_distance_meters,fare_time_milliseconds,pickup_location_latitude,"
    "pickup_location_longitude,sfo_pickup,paratransit,total_fare_amount"
)
METERS_PER_MILE = 1609.344
# A record is counted as a ride only if it moved and lasted: the feed includes meter tests and cancellations.
MIN_METERS, MIN_SECONDS = 300.0, 60.0


def month_url(year: int, month: int) -> str:
    """Return the download URL for one month of trips."""
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    params = {
        "$select": FIELDS,
        "$where": f"start_time_local >= '{start}T00:00:00' and start_time_local < '{end}T00:00:00'",
        "$limit": "1000000",
    }
    return f"{DATASET_URL}?{urllib.parse.urlencode(params)}"


def is_ride(row: dict) -> bool:
    """Return whether a record is an ordinary passenger ride."""
    if row.get("paratransit") in ("1", "true"):
        return False  # scheduled paratransit is not on-demand
    try:
        return (
            float(row["trip_distance_meters"]) >= MIN_METERS
            and float(row["fare_time_milliseconds"]) >= MIN_SECONDS * 1000
        )
    except (KeyError, ValueError):
        return False


def parse_month(text: str) -> list[dict]:
    """Parse one month's download into rides with a start time, miles, fare and an airport flag."""
    rides = []
    seen: set[tuple] = set()
    for row in csv.DictReader(text.splitlines()):
        if not is_ride(row):
            continue
        # The feed repeats some records exactly, up to 15% in some months. A repeat is not a second ride.
        identity = tuple(row.values())
        if identity in seen:
            continue
        seen.add(identity)
        rides.append(
            {
                "start": datetime.fromisoformat(row["start_time_local"]),
                "miles": float(row["trip_distance_meters"]) / METERS_PER_MILE,
                "fare": float(row.get("total_fare_amount") or 0.0),
                "airport": row.get("sfo_pickup") in ("1", "true"),
                "latitude": float(row.get("pickup_location_latitude") or "nan"),
                "longitude": float(row.get("pickup_location_longitude") or "nan"),
            }
        )
    return rides


def area_of(ride: dict) -> str:
    """Return the part of the city a ride started in: the airport, the north-east core, or the rest.

    The core is the downtown quarter north of 16th Street and east of Divisadero, roughly, where taxi
    pickups are densest. Rides with no position count as the rest.
    """
    if ride["airport"]:
        return "airport"
    if ride["latitude"] >= 37.765 and ride["longitude"] >= -122.44:
        return "core"
    return "rest"


def months() -> list[tuple[int, int]]:
    """Return every (year, month) the series covers."""
    out, (year, month) = [], FIRST_MONTH
    while (year, month) <= LAST_MONTH:
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def fetch_rides() -> list[dict]:
    """Download every month once and return all rides in time order."""
    rides: list[dict] = []
    for year, month in months():
        path = fetch(month_url(year, month), f"sftaxi/{year}-{month:02d}.csv", timeout=900.0)
        rides.extend(parse_month(path.read_text()))
    return sorted(rides, key=lambda ride: ride["start"])
