"""The builders behind `depot-twin data <name>`: tables fetched from public sources, and the page's files.

Every number the scenarios and documents quote from outside comes out of one of these files, and each file
records where it came from and when it was fetched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from depot_twin import analysis, provenance
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
    page = {"forecast": rows, "tests": ["E7b", "E13"], "code": provenance.page_stamp("web/public/facts.json")}
    path.write_text(json.dumps(page, indent=1))
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
        "code": provenance.page_stamp("web/public/money.json"),
    }
    path = Path(out)
    path.write_text(json.dumps(page, separators=(",", ":")))
    return path


SOURCES = {
    "sftaxi": "City and County of San Francisco, Taxi Trips (DataSF open data)",
    "chicago": "City of Chicago, Transportation Network Providers trips (Chicago Data Portal)",
    "nyc": "New York City Taxi and Limousine Commission, trip record data",
    "cpuc": "California Public Utilities Commission, autonomous vehicle quarterly reports",
    "census": "US Census Bureau, 2020 decennial population and 2023 gazetteer",
    "weather": "Open-Meteo historical forecast archive (CC BY 4.0)",
    "caiso": "California ISO, OASIS prices and Today's Outlook demand and emissions",
    "bev.xlsx": "Pacific Gas and Electric, Business Electric Vehicle rate sheet",
}


def build_manifest(out: str = "data/manifest.json") -> Path:
    """Write the size and checksum of every downloaded file the results were built from.

    The raw files are not committed: they are public records under their publishers' terms. This is the list
    of what was used, so that a rebuild can tell whether a publisher has revised a file since.
    """
    import hashlib

    raw = data_dir() / "raw"
    files = []
    for path in sorted(p for p in raw.rglob("*") if p.is_file()):
        relative = path.relative_to(raw)
        files.append(
            {
                "file": str(relative),
                "source": SOURCES.get(relative.parts[0], "unlisted"),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "retrieved": date.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    target = Path(out)
    target.write_text(json.dumps({"files": files}, indent=1) + "\n")
    return target


def manifest_problems(path: str = "data/manifest.json") -> list[str]:
    """Every downloaded file on disk whose size or checksum differs from the manifest. Files not on disk are skipped."""
    import hashlib

    raw = data_dir() / "raw"
    wrong = []
    for entry in json.loads(Path(path).read_text())["files"]:
        file = raw / entry["file"]
        if file.exists() and hashlib.sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
            wrong.append(f"{entry['file']}: differs from the manifest; the publisher may have revised it")
    return wrong


def build_reproduce(out: str = "data/reproduce") -> Path:
    """Copy the replay curves of the four replayed fortnights into the repository, as the depot tests read them."""
    import shutil

    from depot_twin import evals, provenance
    from depot_twin.evals import common

    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    for start in provenance.REPLAYED:
        evals.replay_curves(start)
        shutil.copyfile(common.replay_cache(start), target / f"replay_{start}.npz")
    return target


# The runs the page plays back: file, fleet, calling rule, power rule. Three days of the first test fortnight.
RECORDINGS = (
    ("sample", 500, "heartbeat", "slot_power"),
    ("threshold", 500, "threshold", "slot_power"),
    ("threshold_emptiest", 500, "threshold", "need_first"),
    ("plan_1000", 1000, "heartbeat", "slot_power"),
    ("threshold_1000", 1000, "threshold", "slot_power"),
)


def build_traces(out: str = "web/public/traces") -> Path:
    """Record the runs the page plays back, from the committed replay curves, and stamp them with the code that ran."""
    from depot_twin import cli, evals, provenance

    target = Path(out)
    curves = Path("data/reproduce") / f"replay_{evals.E8_START}.npz"
    for name, fleet, recall, policy in RECORDINGS:
        args = [
            "trace",
            f"scenarios/v2/east_oakland_{fleet}.toml",
            *("--out", str(target / f"{name}.json"), "--days", "3", "--seed", "1"),
            *("--recall", recall, "--policy", policy, "--demand", str(curves)),
        ]
        if cli.main(args):
            raise ValueError(f"the recording {name} breaks the trace contract")
    stamp = {
        "recordings": [name for name, *_ in RECORDINGS],
        "code": provenance.page_stamp("web/public/traces/stamp.json"),
    }
    (target / "stamp.json").write_text(json.dumps(stamp, indent=1) + "\n")
    return target / "stamp.json"


def build_reference(out: str = "web/tests/reference_stamp.json") -> Path:
    """Run the Python side of the browser parity test again, with the weekly shape the browser uses, and stamp it."""
    import subprocess
    import sys

    from depot_twin import provenance

    for script in ("shape.py", "reference.py"):
        subprocess.run([sys.executable, str(Path("web/scripts") / script)], check=True)
    target = Path(out)
    stamp = {"code": provenance.page_stamp("web/tests/reference_stamp.json")}
    target.write_text(json.dumps(stamp, indent=1) + "\n")
    return target


def build_figures() -> Path:
    """Draw the documents' figures from the result files."""
    from depot_twin import figures

    return figures.write()[0].parent


def build_account() -> Path:
    """Write the account study: what the recorded sweep says when its unsourced inputs are moved."""
    from depot_twin.analysis import account_study

    return account_study()


def build_trust() -> Path:
    """Fit the reference forecast once and write the figures of the page's trust views."""
    from depot_twin.trust import build_trust as write

    return write()


def build_footprint() -> Path:
    """Read the filings' footprint, chargers and sessions, with census populations, into one record."""
    from depot_twin.data.footprint import build_footprint as write

    return write()


def build_demand(out: str = "web/public/demand.json") -> Path:
    """Write the page's service-area file from E21's record, with the fleet E23 served at the feeder's limit."""
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
    page["growth_per_month_by_estimate"] = record["growth_per_month_by_estimate"]
    capacity = json.loads((data_dir() / "derived" / "e23_capacity.json").read_text())
    page["served_at_the_limit_one_feeder"] = capacity["largest_serving_the_floor"][capacity["best_rule"]]
    # The fleet one feeder carries at the estimated energy use, and the fleet to plan for, which still fits
    # with 10% more. The months until the area outgrows one feeder are counted against the plan.
    page["capacity_one_feeder"] = analysis.carried_fleet(data_dir() / "derived")[0]
    page["planned_one_feeder"] = analysis.planned_fleet(data_dir() / "derived")[0]
    page["areas"] = analysis.demand_at(record, page["planned_one_feeder"])
    # The growth the months after the footprint last changed support, and the months it gives each area:
    # the range the page leads with. The faster readings stay in the file as what another enlargement would do.
    from depot_twin.cadence import months_until

    settled = analysis.growth_since_the_footprint_settled(
        json.loads((data_dir() / "derived" / "footprint.json").read_text())
    )
    page["growth_since_the_footprint_settled"] = settled["growth_per_month"]
    for area in page["areas"].values():
        months = [
            months_until(page["planned_one_feeder"], row["vehicles_at_25_rides"], settled["growth_per_month"])
            for row in area.get("by_level", {}).values()
        ]
        reached = sorted(m for m in months if m is not None)
        area["months_on_the_growth_since_the_footprint_settled"] = [reached[0], reached[-1]] if reached else None
    page["code"] = provenance.page_stamp("web/public/demand.json")
    path = Path(out)
    path.write_text(json.dumps(page, separators=(",", ":")))
    return path


def build_outcome(out: str = "web/public/outcome.json") -> Path:  # noqa: PLR0915
    """Write what each of the four decisions is worth, with and without it, read from the records.

    Each decision is one measured pair: the same depot on the same fortnights and draws with the decision
    taken and not taken. Nothing is added across decisions: they were measured at different fleets.
    """
    import numpy as np

    derived = data_dir() / "derived"
    capacity = json.loads((derived / "e23_capacity.json").read_text())
    account = json.loads((derived / "account_study.json").read_text())
    margin = json.loads((derived / "e26_margin.json").read_text())
    parked = json.loads((derived / "e27_parked.json").read_text())
    steer = json.loads((derived / "e29_steer.json").read_text())
    carried, rows = analysis.carried_fleet(derived)
    planned, _ = analysis.planned_fleet(derived)
    rides = capacity["rides_per_vehicle_day"]
    runs = capacity["runs"]

    def median(key: str, **match: object) -> float:
        return float(np.median([r[key] for r in runs if all(r[k] == v for k, v in match.items())]))

    def depot(fleet: int, contribution: float, **more: object) -> dict:
        return {"fleet": fleet, "rides_per_day": fleet * rides, "contribution_per_day": round(contribution), **more}

    base = {"label": "base", "policy": "slot_power"}
    power = {"label": "power", "rule": "threshold", "size": 1000}
    power_arm = lambda policy: {  # noqa: E731
        "fleet": 1000,
        "rides_per_day": round(1000 * rides * median("served", **power, policy=policy)),
        "rides_served_share": round(median("served", **power, policy=policy), 4),
        "contribution_per_day": round(median("contribution_per_day", **power, policy=policy)),
    }
    plan_arm = lambda rule: depot(  # noqa: E731
        500,
        median("contribution_per_day", **base, rule=rule, size=500),
        energy_per_kwh=round(median("cost_per_kwh", **base, rule=rule, size=500), 4),
    )
    # The calling rule on the steps both rules were run on (E26): the largest fleet each carries.
    same = margin["on_the_same_steps"]
    waits, plain = same["waits_for_a_charger"], same["plain"]
    with_rule = rows["by_size"][str(waits)]
    timing = account["feeder_timing"]
    summary = timing["summary"]
    settled = timing["growth_since_the_footprint_settled"]
    slow = [
        s
        for s in timing["scenarios"]
        if (s["growth"], s["fleet_costs"], s["applied_months_after_signing"])
        == (settled["nearest_reading"], "base", 12)
    ]
    demand = json.loads((derived / "e21_demand.json").read_text())
    # Both readings of today's level and all three of growth, as the documents quote the range.
    months = analysis.demand_at(demand, planned)["east_bay_20km"]["months_until_second_feeder_range"]
    at_plan = account["split"][str(planned)]
    above = margin["by_energy"][f"{margin['margin']:g}"]["by_size"][str(planned)]
    # What the plan as tested pays for a kWh at the planned fleet, against the rule that waits on the same
    # fortnights and seeds (E29).
    tested = steer["by_peak_level"][f"{steer['plan_settings_in_the_capacity_test']['peak_call_below']:g}"]
    waits_pays = float(
        np.mean(
            [
                r["cost_per_kwh"]
                for r in runs
                if (r["label"], r["rule"], r["size"]) == ("base", capacity["best_rule"], planned)
                and r["seed"] in steer["seeds"]
            ]
        )
    )
    page = {
        "fare_per_ride": json.loads((derived / "e19_sweet_spot.json").read_text())["assumptions"]["pricing"][
            "published_average_fare"
        ],
        "runs": len(capacity["windows"]) * len(capacity["seeds"]),
        "rides_per_vehicle_day": rides,
        "area_vehicles_today": demand["areas"]["east_bay_20km"]["vehicles_range"],
        # The fleet to plan one feeder for, and what the feeder carries as the vehicles' energy use moves.
        "one_feeder": {
            "planned": depot(
                planned, at_plan["contribution"], power_share_used=rows["by_size"][str(planned)]["grid_share_used"]
            ),
            "power_share_used_at_the_plan_with_more_energy_use": above["grid_share_used"],
            "margin": margin["margin"],
            "carried_by_energy_use": {energy: fleet for energy, fleet in margin["carried"].items()},
            "registered_rule_gives": margin["planned_fleet"],
            # The same fleets asked to be carried in each fortnight taken alone.
            "carried_in_every_fortnight_by_energy_use": {
                energy: max(
                    (
                        int(size)
                        for size, row in group["by_size"].items()
                        if int(size) <= (group["capacity"] or 0) and all(row["carried_by_fortnight"].values())
                    ),
                    default=None,
                )
                for energy, group in margin["by_energy"].items()
            },
            "carried_in_every_fortnight_with_the_parked_load": {
                energy: group["carried_in_every_fortnight"] for energy, group in parked["by_energy"].items()
            },
            # With the always-on load also running while a vehicle is in the depot (E27).
            "carried_with_the_parked_load": {energy: group["carried"] for energy, group in parked["by_energy"].items()},
            "carried_in_every_fortnight_with_both": parked["by_energy"][f"{margin['margin']:g}"][
                "carried_in_every_fortnight"
            ],
            "planned_holds_with_the_parked_load": all(
                parked["by_energy"]["1"]["by_size"][str(planned)]["carried_by_fortnight"].values()
            ),
            "fortnights": len(capacity["windows"]),
            "draws_a_fortnight": len(capacity["seeds"]),
            "served_at_the_limit": capacity["largest_serving_the_floor"][capacity["best_rule"]],
            "feeder_kwh_per_vehicle_day": rows["by_size"][str(carried)]["feeder_kwh_per_vehicle_day"],
            "usable_kwh_a_day": margin["usable_kwh_a_day"],
        },
        "decisions": {
            "calling": {
                "steps": same["steps"],
                "without": depot(
                    plain,
                    float(
                        np.median(
                            [
                                r["contribution_per_day"]
                                for r in margin["runs"]
                                if (r["label"], r["rule"], r["size"]) == ("energy_1", "threshold", plain)
                            ]
                        )
                    ),
                ),
                "with": depot(
                    waits,
                    with_rule["contribution_per_day"]["median"],
                    power_share_used=with_rule["grid_share_used"],
                    rides_served_share_lowest_run=min(
                        r["served"]
                        for r in margin["runs"]
                        if (r["label"], r["rule"], r["size"]) == ("energy_1", capacity["best_rule"], waits)
                    ),
                ),
                # The plain rule at the fleet the waiting rule carries: what the watched pair shows.
                "plain_at_the_larger_fleet": {
                    "fleet": waits,
                    "rides_served_share": margin["plain_rule"]["by_size"][str(waits)]["median"],
                    "fortnights_at_the_floor": sum(
                        margin["plain_rule"]["by_size"][str(waits)]["carried_by_fortnight"].values()
                    ),
                    "fortnights": len(capacity["windows"]),
                },
            },
            "power": {
                "without": power_arm("need_first"),
                "with": power_arm("slot_power"),
                "no_gain_at": sorted(int(size) for size in capacity["power_rule_at_planned_fleets"]),
            },
            "plan": {
                "without": plan_arm("threshold"),
                "with": plan_arm("plan"),
                "energy_saving": capacity["plan_energy_saving_at_500"]["median"],
                "energy_saving_at_the_planned_fleet": round(
                    1 - tested["by_size"][str(planned)]["cost_per_kwh"] / waits_pays, 4
                ),
            },
            "feeder": {
                "capital": timing["capital"],
                "months_until_one_feeder_is_full": [months[0], months[-1]],
                "a_year_late_at_base_costs_on_the_faster_growth_readings": summary[
                    "a_year_late_at_base_costs_on_the_faster_growth_readings"
                ],
                "a_year_late_at_base_costs_on_the_slowest_growth_reading": summary[
                    "a_year_late_at_base_costs_on_the_slowest_growth_reading"
                ],
                "a_year_late_across_fleet_costs": summary["a_year_late_across_fleet_costs"],
                "carrying_cost_of_applying_a_year_early": summary["carrying_cost_of_applying_a_year_early"],
                "lead_months": timing["lead_months_assumed"],
                "scenarios": summary["scenarios"],
                # The growth the months after the footprint last changed support, and what waiting costs on it.
                "growth_since_the_footprint_settled": settled["growth_per_month"],
                "months_on_that_growth": sorted(settled["months_until_one_feeder_is_full"].values()),
                "a_year_late_on_that_growth_by_lead": {
                    str(lead): [
                        min(s["cost_of_waiting"] for s in slow if s["lead_months"] == lead),
                        max(s["cost_of_waiting"] for s in slow if s["lead_months"] == lead),
                    ]
                    for lead in timing["lead_months_assumed"]
                },
            },
        },
        "code": provenance.page_stamp("web/public/outcome.json"),
    }
    path = Path(out)
    path.write_text(json.dumps(page, separators=(",", ":")))
    return path


def build_blocks() -> Path:
    """Write E24's ranges with weeks resampled in blocks, from the weekly figures E24 recorded."""
    from depot_twin import blocks

    return blocks.study()


def build_baseline() -> Path:
    """Write the stronger naive forecast beside E24's models. Needs the ride series."""
    from depot_twin import baseline

    return baseline.study()


def build_spread() -> Path:
    """Write where the spread of the capacity runs comes from: the fortnight or the draw."""
    return analysis.spread_study()


BUILDERS = {
    "outcome": build_outcome,
    "spread": build_spread,
    "blocks": build_blocks,
    "baseline": build_baseline,
    "footprint": build_footprint,
    "demand": build_demand,
    "trust": build_trust,
    "site": build_site,
    "cpuc": build_cpuc,
    "grid": build_grid,
    "facts": build_facts,
    "models": build_models,
    "money": build_money,
    "account": build_account,
    "figures": build_figures,
    "manifest": build_manifest,
    "reproduce": build_reproduce,
    "traces": build_traces,
    "reference": build_reference,
}
