"""Rebuild the derived tables under data/derived from their public sources.

Every number the scenarios and documents quote from outside comes out of one of these files, and each file
records where it came from and when it was fetched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from depot_twin.data import cpuc, data_dir, pge

# The former foundry parcel at 7825 San Leandro Street, Oakland: about 14.5 acres, zoned general industrial.
# The twin places a hypothetical depot here because the parcel, its zoning and the grid around it are all
# on the public record. Nothing here says the site is available.
SITE = {"name": "East Oakland", "address": "7825 San Leandro St, Oakland, CA 94621", "lat": 37.75055, "lon": -122.19350}


def _write(name: str, payload: dict) -> Path:
    target = data_dir() / "derived" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


def build_site(radius_m: float = 150.0) -> Path:
    """Write the feeders near the site and their load headroom."""
    feeders = pge.summarize_feeders(pge.fetch_sections(SITE["lat"], SITE["lon"], radius_m))
    return _write(
        "site.json",
        {
            "site": SITE,
            "radius_m": radius_m,
            "feeders": [f.as_dict() for f in feeders],
            "source": "PG&E Integration Capacity Analysis, LineDetail layer, LoadCapacity_kW",
            "source_url": pge.ICA_QUERY_URL,
            "fetched": date.today().isoformat(),
        },
    )


def build_cpuc() -> Path:
    """Write monthly fleet totals and the per-trip calibration targets from the latest quarter."""
    by_quarter = {quarter: cpuc.fetch_month_rows(quarter) for quarter in cpuc.QUARTERS}
    latest = max(by_quarter)
    months = [
        {"year": r.year, "month": r.month, "trips": r.trips, "miles": round(r.miles, 1)}
        for rows in by_quarter.values()
        for r in rows
    ]
    return _write(
        "cpuc_targets.json",
        {
            "scope": "Waymo driverless deployment, California, all service areas combined",
            "months": months,
            "targets_quarter": latest,
            "targets": cpuc.targets(by_quarter[latest]),
            "source": "CPUC autonomous vehicle quarterly reports, monthly table",
            "source_url": cpuc.BASE_URL,
            "fetched": date.today().isoformat(),
        },
    )


GRID_WEEK = date(2024, 4, 15)  # a Monday inside the days the depot's demand is replayed from
GRID_DAYS = 14  # the whole replay fortnight: the first week is shown, the second is scored


def build_grid(out: str = "web/public/grid/california_week.json") -> Path:
    """Write a week of California grid net demand and carbon intensity for the front end."""
    from depot_twin.data import caiso

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    from depot_twin.data import caiso_prices

    week = {
        "source": "California ISO, Today's Outlook history; prices from the CAISO OASIS market archive",
        "source_url": "https://www.caiso.com/todays-outlook",
        "week_of": GRID_WEEK.isoformat(),
        "days": GRID_DAYS,
        "step_min": 5,
        **caiso.fetch_week(GRID_WEEK, days=GRID_DAYS),
        **caiso_prices.fetch_week(GRID_WEEK, days=GRID_DAYS),
    }
    path.write_text(json.dumps(week, separators=(",", ":")))
    return path


def build_facts(out: str = "web/public/facts.json") -> Path:
    """Write the tested forecast scores the front end quotes, read from the result files, never typed in."""
    derived = data_dir() / "derived"
    in_city = json.loads((derived / "e7b_scale_free.json").read_text())["san_francisco"]
    new_site = json.loads((derived / "e13_new_site.json").read_text())["cells"]
    rows = []
    for horizon in (1, 6, 24):
        own = in_city[f"{horizon}h"]
        cells = [c for c in new_site if c["horizon"] == horizon]
        against = [c["donors_and_generated"]["wape"] / c["naive"]["same_time_last_week"] for c in cells]
        rows.append(
            {
                "hours_ahead": horizon,
                "error": own["model_wape"],
                # The column is the same hour last week, whichever simple rule the fit happened to pick as its baseline.
                "same_hour_last_week": own["all_baselines_wape"]["same_time_last_week"],
                "upper_bound_held": own["upper_95_coverage"],
                "no_history_error_against_last_week": [round(min(against), 3), round(max(against), 3)],
            }
        )
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"forecast": rows, "tests": ["E7b", "E13"]}, indent=1))
    return path


def build_models() -> Path:
    """Train every forecast variant, run the depot on each, and write the front end's model workbench file."""
    from depot_twin import workbench

    return workbench.build_all()


def build_money(out: str = "web/public/money.json") -> Path:
    """Write the page's account file from E19's recorded sweep: every design's lines, nothing recomputed."""
    from depot_twin import evals

    result = json.loads((data_dir() / "derived" / "e19_sweet_spot.json").read_text())
    page = {
        "window": result["window"],
        "assumptions": result["assumptions"],
        "fleets": list(evals.E19_FLEETS),
        "feeders": list(evals.E19_FEEDERS),
        "chargers": list(evals.E19_CHARGERS),
        "controls": list(evals.E19_CONTROLS),
        "rows": result["rows"],
    }
    path = Path(out)
    path.write_text(json.dumps(page, separators=(",", ":")))
    return path


def build_trust() -> Path:
    """Fit the reference forecast once and write the figures of the page's trust views."""
    from depot_twin.trust import build_trust as write

    return write()


def build_footprint() -> Path:
    """Read the filings' footprint, chargers and sessions, with census populations, into one record."""
    from depot_twin.data.footprint import build_footprint as write

    return write()


def build_demand(out: str = "web/public/demand.json") -> Path:
    """Write the page's service-area file from E21's record: residents, rides, vehicles and the feeder timeline."""
    record = json.loads((data_dir() / "derived" / "e21_demand.json").read_text())
    page = {
        k: record[k]
        for k in (
            "penetration_trips_per_resident_month",
            "growth_per_month",
            "capacity_one_feeder",
            "rides_per_vehicle_day",
            "areas",
            "run",
        )
    }
    path = Path(out)
    path.write_text(json.dumps(page, separators=(",", ":")))
    return path


BUILDERS = {
    "footprint": build_footprint,
    "demand": build_demand,
    "trust": build_trust,
    "site": build_site,
    "cpuc": build_cpuc,
    "grid": build_grid,
    "facts": build_facts,
    "models": build_models,
    "money": build_money,
}
