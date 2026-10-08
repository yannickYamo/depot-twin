"""Hourly pickups in New York City by kind of area, from the Taxi and Limousine Commission's trip records.

Two services are read: app-based ride-hail ("fhvhv": Uber and Lyft) and yellow taxis. Both give a pickup
time and a pickup zone for every trip. New York is the largest open source of ride-hail trips, and its zones
cover every kind of place a depot might serve: a dense core, inner and outer residential boroughs, airports.

The monthly files are large (half a gigabyte for ride-hail). Each is downloaded, reduced to hourly counts
per area, and deleted. Nothing but the counts is kept.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime

from depot_twin.data import data_dir, fetch

FILE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/{service}_tripdata_{year}-{month:02d}.parquet"
ZONES_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
TIME_COLUMN = {"fhvhv": "pickup_datetime", "yellow": "tpep_pickup_datetime"}
AIRPORT_ZONES = {"JFK Airport", "LaGuardia Airport"}
OUTER_BOROUGHS = {"Queens", "Bronx", "Staten Island"}


def area_of(borough: str, zone: str, service_zone: str) -> str | None:
    """Return the area a taxi zone belongs to, or None for zones outside the city or unknown.

    The commission's own "Yellow Zone" is the part of Manhattan where street hails are concentrated; it is
    used here as the core.
    """
    if zone in AIRPORT_ZONES:
        return "airports"
    if borough == "Manhattan":
        return "manhattan_core" if service_zone == "Yellow Zone" else "upper_manhattan"
    if borough == "Brooklyn":
        return "brooklyn"
    if borough in OUTER_BOROUGHS:
        return "outer_boroughs"
    return None


def parse_zones(text: str) -> dict[int, str]:
    """Parse the zone lookup table into zone number -> area."""
    areas = {}
    for row in csv.DictReader(text.splitlines()):
        area = area_of(row["Borough"], row["Zone"], row["service_zone"])
        if area:
            areas[int(row["LocationID"])] = area
    return areas


def count_hours(times, zones, areas: dict[int, str], year: int, month: int) -> Counter:
    """Count trips per (area, hour) from parallel columns of pickup times and zone numbers.

    Records dated outside the file's own month are dropped: the files carry a few with broken clocks.
    """
    import pandas as pd

    frame = pd.DataFrame({"hour": pd.Series(times).dt.floor("h"), "area": pd.Series(zones).map(areas)}).dropna()
    frame = frame[(frame["hour"].dt.year == year) & (frame["hour"].dt.month == month)]
    return Counter(dict(frame.groupby(["area", "hour"]).size()))


def month_hours(service: str, year: int, month: int, areas: dict[int, str]) -> Counter:
    """Download one month's file, return trips per (area, hour), and delete the file.

    The file is fetched whole, in one request: the server throttles clients that ask for many small
    ranges, which is what reading two columns over the network does.
    """
    import urllib.request

    import pyarrow.parquet as pq

    from depot_twin.data import USER_AGENT

    url = FILE_URL.format(service=service, year=year, month=month)
    path = data_dir() / "raw" / "nyc" / f"download_{service}_{year}-{month:02d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter = Counter()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=600.0) as response, path.open("wb") as out:
            while chunk := response.read(1 << 22):
                out.write(chunk)
        file = pq.ParquetFile(path)
        for group in range(file.metadata.num_row_groups):
            columns = file.read_row_group(group, columns=[TIME_COLUMN[service], "PULocationID"]).to_pandas()
            counts.update(count_hours(columns[TIME_COLUMN[service]], columns["PULocationID"], areas, year, month))
    finally:
        path.unlink(missing_ok=True)
    return counts


def _with_retries(service: str, year: int, month: int, areas: dict[int, str], attempts: int = 8) -> Counter:
    """Read a month, waiting and trying again when the file server turns a request away.

    The server answers "forbidden" for a while after too many requests, so the wait is long.
    """
    import time

    for attempt in range(attempts):
        try:
            return month_hours(service, year, month, areas)
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(300.0)
    return Counter()


def fetch_hours(service: str, first: tuple[int, int], last: tuple[int, int]):
    """Return hourly pickups per area as a frame (index: hour, columns: areas), caching each month."""
    import pandas as pd

    areas = parse_zones(fetch(ZONES_URL, "nyc/taxi_zone_lookup.csv").read_text())
    frames = []
    year, month = first
    while (year, month) <= last:
        cache = data_dir() / "raw" / "nyc" / f"{service}_{year}-{month:02d}.parquet"
        if not cache.exists():
            counts = _with_retries(service, year, month, areas)
            rows = [{"area": area, "hour": hour, "trips": trips} for (area, hour), trips in counts.items()]
            cache.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_parquet(cache)
        frames.append(pd.read_parquet(cache))
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    table = pd.concat(frames).pivot_table(index="hour", columns="area", values="trips", aggfunc="sum")
    full = pd.date_range(table.index.min(), table.index.max(), freq="h")
    return table.reindex(full).fillna(0.0)


def month_before(today: datetime, lag_months: int = 3) -> tuple[int, int]:
    """Return the latest (year, month) likely to be published: the commission runs about two months behind."""
    index = today.year * 12 + today.month - 1 - lag_months
    return index // 12, index % 12 + 1
