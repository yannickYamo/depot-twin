"""The donor panel: hourly ride counts from every city that publishes them, in one table.

A new site has no ride history. What it can borrow is how rides move through the week in places that do
have one. Each series here is one service in one area of one city, labelled with the kind of place it is,
so that a new site can borrow from places like it.

Kinds: "core" (a dense downtown), "inner" (dense residential and mixed districts next to it), "outer"
(lower-density districts further out), "airport", and "city" (a whole city, every kind together).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from depot_twin.data import data_dir

KINDS = ("core", "inner", "outer", "airport", "city")
# When no other city has a donor of the kind wanted, borrow from the nearest kind instead.
NEAREST_KIND = {
    "core": ("inner", "city"),
    "inner": ("outer", "core", "city"),
    "outer": ("inner", "city"),
    "airport": ("city",),
    "city": ("inner", "core"),
}
NYC_FIRST, NYC_LAST = (2023, 1), (2026, 6)
NYC_AREAS = {
    "manhattan_core": "core",
    "upper_manhattan": "inner",
    "brooklyn": "inner",
    "outer_boroughs": "outer",
    "airports": "airport",
}
# Yellow taxis barely work outside Manhattan and the airports; the thin series are left out.
YELLOW_AREAS = ("manhattan_core", "upper_manhattan", "airports")
SF_AREAS = {"core": "core", "rest": "inner", "airport": "airport"}


@dataclass(frozen=True)
class Donor:
    """One series in the panel: where it is from and what kind of place it is."""

    name: str
    city: str  # the unit held out together in cross-city tests
    service: str
    kind: str
    weather: str  # key into depot_twin.data.weather.PLACES


def _nyc(service: str, areas) -> tuple[dict, list[Donor]]:
    from depot_twin.data import nyc

    table = nyc.fetch_hours("fhvhv" if service == "ridehail" else "yellow", NYC_FIRST, NYC_LAST)
    series = {f"nyc_{service}_{area}": table[area] for area in areas}
    series[f"nyc_{service}_city"] = table.sum(axis=1)
    donors = [Donor(f"nyc_{service}_{area}", "new_york", service, NYC_AREAS[area], "new_york") for area in areas]
    return series, [*donors, Donor(f"nyc_{service}_city", "new_york", service, "city", "new_york")]


def _chicago() -> tuple[dict, list[Donor]]:
    import pandas as pd

    from depot_twin.data import chicago

    rows = chicago.fetch_hours(last=date(2026, 8, 31))
    index = pd.to_datetime([row["day"] for row in rows]) + pd.to_timedelta([row["hour"] for row in rows], unit="h")
    series = pd.Series([float(row["trips"]) for row in rows], index=index).sort_index()
    series = series.reindex(pd.date_range(series.index.min(), series.index.max(), freq="h")).fillna(0.0)
    return {"chicago_ridehail_city": series}, [Donor("chicago_ridehail_city", "chicago", "ridehail", "city", "chicago")]


def _san_francisco() -> tuple[dict, list[Donor]]:
    import pandas as pd

    from depot_twin.data import sftaxi

    rides = sftaxi.fetch_rides()
    frame = pd.DataFrame({"hour": [ride["start"] for ride in rides], "area": [sftaxi.area_of(ride) for ride in rides]})
    frame["hour"] = frame["hour"].dt.floor("h")
    table = frame.groupby(["hour", "area"]).size().unstack(fill_value=0).astype(float)
    table = table.reindex(pd.date_range(table.index.min(), table.index.max(), freq="h")).fillna(0.0)
    series = {f"sf_taxi_{area}": table[area] for area in SF_AREAS}
    series["sf_taxi_city"] = table.sum(axis=1)
    donors = [
        Donor(f"sf_taxi_{area}", "san_francisco", "taxi", kind, "san_francisco") for area, kind in SF_AREAS.items()
    ]
    return series, [*donors, Donor("sf_taxi_city", "san_francisco", "taxi", "city", "san_francisco")]


def donors() -> list[Donor]:
    """Return the description of every series in the panel, without loading any data."""
    out = [Donor(f"nyc_ridehail_{area}", "new_york", "ridehail", kind, "new_york") for area, kind in NYC_AREAS.items()]
    out.append(Donor("nyc_ridehail_city", "new_york", "ridehail", "city", "new_york"))
    out += [Donor(f"nyc_yellow_{area}", "new_york", "yellow", NYC_AREAS[area], "new_york") for area in YELLOW_AREAS]
    out.append(Donor("nyc_yellow_city", "new_york", "yellow", "city", "new_york"))
    out.append(Donor("chicago_ridehail_city", "chicago", "ridehail", "city", "chicago"))
    out += [Donor(f"sf_taxi_{area}", "san_francisco", "taxi", kind, "san_francisco") for area, kind in SF_AREAS.items()]
    out.append(Donor("sf_taxi_city", "san_francisco", "taxi", "city", "san_francisco"))
    return out


def load_panel():
    """Return the panel as a frame: one row per hour, one column per series, blank where a series has no data.

    Built from the sources on first use and stored; the stored copy is derived from third-party records and
    is not committed.
    """
    import pandas as pd

    path = data_dir() / "derived" / "donor_panel.parquet"
    if path.exists():
        return pd.read_parquet(path)
    series: dict = {}
    for part, _ in (_nyc("ridehail", NYC_AREAS), _nyc("yellow", YELLOW_AREAS), _chicago(), _san_francisco()):
        series.update(part)
    panel = pd.DataFrame(series).sort_index()
    panel.to_parquet(path)
    return panel
