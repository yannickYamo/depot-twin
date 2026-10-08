"""Fleet totals from the quarterly reports Waymo files with the California Public Utilities Commission.

Trip-level fields in these filings are redacted, so the monthly table is the usable part: trips, and miles
split into three periods. Period 1 is driving with no ride assigned, period 2 is driving to a pickup, and
period 3 is driving with a passenger. Those totals are what the simulated fleet is calibrated against.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass

from depot_twin.data import fetch

BASE_URL = (
    "https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/consumer-protection-and-enforcement-division/"
    "documents/tlab/av-programs/"
)
QUARTERS = {
    "2025q4": "waymo-deployment-2025q4.zip",
    "2026q1": "waymo-deployment-2026q1.zip",
    "2026q2": "waymo-deployment-2026q2.zip",
}
# The driverless monthly table; its file name changed between quarters.
MONTH_FILE = re.compile(r"AV_Month(-Level)?_Part\d+-Deployment\.csv$")


@dataclass(frozen=True)
class MonthRow:
    """One month of statewide driverless service."""

    year: int
    month: int
    trips: int
    waiting_hours: float
    miles_idle: float  # period 1
    miles_to_pickup: float  # period 2
    miles_with_passenger: float  # period 3

    @property
    def miles(self) -> float:
        """Return all miles driven in the month."""
        return self.miles_idle + self.miles_to_pickup + self.miles_with_passenger


def _number(text: str) -> float:
    return float(text.replace(",", "").strip() or 0)


def parse_month_csv(text: str) -> list[MonthRow]:
    """Parse the monthly table."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        rows.append(
            MonthRow(
                year=int(row["Year"]),
                month=int(row["Month"]),
                trips=int(_number(row["TotalTrips"])),
                waiting_hours=_number(row["TotalWaiting"]),
                miles_idle=_number(row["TotalVMTPeriod1"]),
                miles_to_pickup=_number(row["TotalVMTPeriod2"]),
                miles_with_passenger=_number(row["TotalVMTPeriod3"]),
            )
        )
    return rows


def fetch_month_rows(quarter: str) -> list[MonthRow]:
    """Download one quarter's filing and return its monthly rows."""
    archive = fetch(BASE_URL + QUARTERS[quarter], f"cpuc/{QUARTERS[quarter]}", timeout=600.0)
    with zipfile.ZipFile(archive) as bundle:
        name = next(n for n in bundle.namelist() if MONTH_FILE.search(n))
        return parse_month_csv(bundle.read(name).decode("utf-8-sig"))


def targets(rows: list[MonthRow]) -> dict[str, float]:
    """Return the per-trip figures the simulated fleet must reproduce."""
    trips = sum(r.trips for r in rows)
    miles = sum(r.miles for r in rows)
    with_passenger = sum(r.miles_with_passenger for r in rows)
    return {
        "months": len(rows),
        "trips": trips,
        "miles": miles,
        "miles_per_trip": miles / trips,
        "passenger_miles_per_trip": with_passenger / trips,
        "idle_share": sum(r.miles_idle for r in rows) / miles,
        "to_pickup_share": sum(r.miles_to_pickup for r in rows) / miles,
        "with_passenger_share": with_passenger / miles,
        "waiting_minutes_per_trip": 60.0 * sum(r.waiting_hours for r in rows) / trips,
    }
