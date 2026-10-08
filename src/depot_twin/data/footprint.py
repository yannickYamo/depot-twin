"""What the public filings say about where the service runs and how its vehicles charge.

Waymo's quarterly filings with the California Public Utilities Commission redact trips by tract, charger
power and session length. They do not redact three things the twin can use: the list of census tracts
served each month (the footprint), the number of chargers, and the number of charging sessions. With the
Census Bureau's 2020 tract populations and centroids, the footprint becomes residents served, and trips
over residents becomes penetration, quarter by quarter. Sessions over trips is how often a vehicle charges.

Everything here is a count from a public file; nothing is a figure the filings withhold.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from depot_twin.data import data_dir, fetch
from depot_twin.data.cpuc import BASE_URL, parse_month_csv

CENPOP_URL = "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR06.txt"
GAZETTEER_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_gaz_tracts_06.txt"
QUARTERS = {
    "2025q1": "waymo-driverless-deployment-2025-q1.zip",
    "2025q2": "waymo-deployment-2025q2.zip",
    "2025q3": "waymo-deployment-2025q3.zip",
    "2025q4": "waymo-deployment-2025q4.zip",
    "2026q1": "waymo-deployment-2026q1.zip",
    "2026q2": "waymo-deployment-2026q2.zip",
}
DAYS = {"q1": 90, "q2": 91, "q3": 92, "q4": 92}
TRACT_FILE = re.compile(r"(Driverless|Deployment 2025 Q1/).*Monthly[ _-]Tract.*\.csv$", re.IGNORECASE)
CHARGERS_FILE = re.compile(r"Driverless.*Chargers.*\.csv$", re.IGNORECASE)
SESSIONS_FILE = re.compile(r"Driverless.*Charging[ _-]Sessions.*\.csv$", re.IGNORECASE)
MONTH_FILE = re.compile(
    r"(Driverless|Deployment 2025 Q1/).*AV_ ?Month([-_]Level)?(_Part\d+)?(-Deployment)?\.csv$", re.IGNORECASE
)
COUNTIES = {"037": "Los Angeles", "075": "San Francisco", "081": "San Mateo", "085": "Santa Clara", "001": "Alameda"}
DEPOT = (37.75055, -122.1935)  # 7825 San Leandro Street, Oakland

# Service areas a depot here might serve, as circles of straight-line distance from the parcel. The
# twin's drive to the depot is fifteen minutes; eight kilometres is that at city speeds, twenty is the East Bay.
SERVICE_AREAS = {"oakland_8km": 8.0, "east_bay_15km": 15.0, "east_bay_20km": 20.0}


@dataclass(frozen=True)
class Tract:
    """One census tract: who lives there and where its people are."""

    geoid: str
    population: int
    lat: float
    lon: float
    land_km2: float


def tracts() -> dict[str, Tract]:
    """California's tracts with 2020 population, population-weighted centroid and land area."""
    cenpop = fetch(CENPOP_URL, "census/CenPop2020_Mean_TR06.txt", timeout=120.0)
    gazetteer = fetch(GAZETTEER_URL, "census/2023_gaz_tracts_06.txt", timeout=120.0)
    land = {}
    for row in csv.DictReader(io.StringIO(Path(gazetteer).read_text(encoding="utf-8-sig")), delimiter="\t"):
        land[row["GEOID"].strip()] = float(row["ALAND"]) / 1e6
    out = {}
    for row in csv.DictReader(io.StringIO(Path(cenpop).read_text(encoding="utf-8-sig"))):
        geoid = row["STATEFP"] + row["COUNTYFP"] + row["TRACTCE"]
        out[geoid] = Tract(
            geoid, int(row["POPULATION"]), float(row["LATITUDE"]), float(row["LONGITUDE"]), land.get(geoid, 0.0)
        )
    return out


def _counts(archive: Path) -> dict:
    """Footprint, chargers, sessions and monthly trips from one quarter's archive."""
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        tract_name = next((n for n in names if TRACT_FILE.search(n)), None)
        served: dict[str, set[str]] = {}
        if tract_name:
            for row in csv.DictReader(io.StringIO(bundle.read(tract_name).decode("utf-8-sig"))):
                served.setdefault(f"{row['Year']}-{int(row['Month']):02d}", set()).add(row["Tract"].strip().zfill(11))
        chargers = sessions = 0
        name = next((n for n in names if CHARGERS_FILE.search(n)), None)
        if name:
            chargers = max(0, bundle.read(name).count(b"\n") - 1)
        name = next((n for n in names if SESSIONS_FILE.search(n)), None)
        if name:
            with bundle.open(name) as handle:
                sessions = max(0, sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b"")) - 1)
        name = next((n for n in names if MONTH_FILE.search(n)), None)
        months = parse_month_csv(bundle.read(name).decode("utf-8-sig")) if name else []
    return {"served": served, "chargers": chargers, "sessions": sessions, "months": months}


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two points, in kilometres."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def service_areas(all_tracts: dict[str, Tract]) -> dict:
    """Residents, land and density inside each circle around the parcel, Alameda County only."""
    out = {}
    for name, radius in SERVICE_AREAS.items():
        inside = [
            t
            for t in all_tracts.values()
            if t.geoid.startswith("06001") and distance_km(DEPOT, (t.lat, t.lon)) <= radius
        ]
        population = sum(t.population for t in inside)
        land = sum(t.land_km2 for t in inside)
        out[name] = {
            "radius_km": radius,
            "tracts": len(inside),
            "population": population,
            "land_km2": round(land, 1),
            "density": round(population / land, 1) if land else None,
        }
    return out


def build_footprint(out: str | None = None) -> Path:
    """Fetch every quarter's filing, count what is public, and write the penetration and cadence record."""
    all_tracts = tracts()
    quarters = []
    for quarter, filename in QUARTERS.items():
        archive = fetch(BASE_URL + filename, f"cpuc/{filename}", timeout=900.0)
        counts = _counts(Path(archive))
        trips = sum(m.trips for m in counts["months"])
        days = DAYS[quarter[-2:]]
        footprint = sorted(counts["served"].values(), key=len)[-1] if counts["served"] else set()
        known = [all_tracts[t] for t in footprint if t in all_tracts]
        population = sum(t.population for t in known)
        land = sum(t.land_km2 for t in known)
        by_county: dict[str, int] = {}
        for t in known:
            county = COUNTIES.get(t.geoid[2:5], t.geoid[2:5])
            by_county[county] = by_county.get(county, 0) + 1
        quarters.append(
            {
                "quarter": quarter,
                "months": [{"year": m.year, "month": m.month, "trips": m.trips} for m in counts["months"]],
                "trips": trips,
                "trips_per_day": round(trips / days, 0),
                "tracts": len(footprint),
                "tracts_by_county": by_county,
                "residents": population,
                "density": round(population / land, 1) if land else None,
                "trips_per_resident_month": round(trips / 3 / population, 4) if population else None,
                "chargers": counts["chargers"],
                "sessions": counts["sessions"],
                "sessions_per_day": round(counts["sessions"] / days, 0),
                "trips_per_session": round(trips / counts["sessions"], 2) if counts["sessions"] else None,
                "sessions_per_charger_day": round(counts["sessions"] / days / counts["chargers"], 1)
                if counts["chargers"]
                else None,
            }
        )
    record = {
        "source": "Waymo quarterly filings to the CPUC, driverless deployment; Census Bureau 2020 tract populations and 2023 gazetteer",
        "note": "Trips by tract, charger power and session length are redacted in the filings; only the served tracts, the counts of chargers and sessions, and monthly trip totals are read. Charging data covers the whole passenger fleet, pilot and deployment.",
        "quarters": quarters,
        "service_areas": service_areas(all_tracts),
    }
    path = Path(out) if out else data_dir() / "derived" / "footprint.json"
    path.write_text(json.dumps(record, indent=1))
    return path
