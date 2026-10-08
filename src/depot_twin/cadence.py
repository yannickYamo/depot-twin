"""E22: the twin against the real visit cadence, and E21: what the service area asks of the depot.

The filings count charging sessions and chargers (`data/footprint.py`). A vehicle in the real operation
charges once every seven and a half to nine trips, and each charger sees about twenty sessions a day.
With one long visit a day the twin goes to the depot about 1.3 times a vehicle-day. E22 sweeps the settings that decide
cadence (the depot leg, how often a visit includes cleaning, the charge level that calls a vehicle in,
the charger count) to find the ones that reproduce the filings, then measures the findings under
them. E21 turns the filings' penetration and the census population around the parcel into rides, vehicles
and feeders by month. The registrations are in `EVALS.md`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from depot_twin.data import data_dir

E22_SEEDS = (2201, 2202, 2203)
E22_LEGS = {15: 4.0, 8: 2.0, 5: 1.2}  # minutes: miles, at city speeds
E22_CLEAN_EVERY = (1, 2, 4)
E22_CALL_BELOW = (0.20, 0.40, 0.55)
E22_CHARGERS = ("rule", "one_per_five")
E22_SIZE = 500
TARGET_TRIPS_PER_VISIT = (7.5, 8.5)
TARGET_VISITS_PER_CHARGER_DAY = (19.0, 21.0)


def _fleet_and_depot(size: int, leg_minutes: int, clean_every: int, chargers: str):
    """The scenario at a size with the cadence settings applied."""
    from depot_twin.growth import scaled_v2
    from depot_twin.resources import ChargerBank

    fleet, depot = scaled_v2(size, site_limit_kw=2750.0)
    fleet = replace(fleet, depot_leg_minutes=float(leg_minutes), depot_leg_miles=E22_LEGS[leg_minutes])
    count = size // 5 if chargers == "one_per_five" else sum(b.count for b in depot.chargers)
    depot = replace(depot, clean_every=clean_every, chargers=(ChargerBank("dc", count, 60.0),))
    return fleet, depot


def cadence_run(job: tuple) -> dict:
    """One fortnight at 500 vehicles under one cadence setting: trips a visit, visits a charger-day, rides, energy."""
    from depot_twin.evals import E8_DAYS, E8_START, replay_curves
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape
    from depot_twin.replay import ReplayDemand

    leg, clean_every, call_below, chargers, seed = job
    fleet, depot = _fleet_and_depot(E22_SIZE, leg, clean_every, chargers)
    demand = ReplayDemand.scaled(replay_curves(E8_START), E22_SIZE * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    rule = ThresholdRecall(recall_soc=call_below, target=0.85)
    result = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand).run(E8_DAYS)
    return {
        "leg": leg,
        "clean_every": clean_every,
        "call_below": call_below,
        "chargers": chargers,
        "seed": seed,
        **_measure(result, rule, depot, E22_SIZE),
    }


def _measure(result, rule, depot, size: int) -> dict:
    """What one run did over its scored week: rides, cadence as it actually ran, cost of energy, queueing."""
    from depot_twin.economics import Prices, energy_by_period
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS
    from depot_twin.evals.common import what_ran
    from depot_twin.fleet import served_share

    first = E8_WARMUP_DAYS * 1440.0
    days = E8_DAYS - E8_WARMUP_DAYS
    steps = result.steps[result.steps[:, 0] >= first]
    count = sum(b.count for b in depot.chargers)
    energy = energy_by_period(result.depot.series, skip_days=E8_WARMUP_DAYS)
    prices = Prices()
    cost = (
        energy["peak"] * prices.energy_peak
        + energy["off_peak"] * prices.energy_off_peak
        + energy["super_off_peak"] * prices.energy_super_off_peak
    )
    return {
        "charger_count": count,
        "served": served_share(steps),
        **what_ran(result, rule, size, count, first, days),
        "cost_per_kwh": cost / max(sum(energy.values()), 1.0),
        "waiting_share": float((result.depot.series[result.depot.series[:, 0] >= first][:, 4] > 0).mean()),
        "stranded": float(result.stranded),
    }


MEASURES = (
    "charger_count",
    "served",
    "visits_per_vehicle_day",
    "trips_per_visit",
    "visits_per_charger_day",
    "arrived_at_floor_share",
    "forced_call_share",
    "inspected_share",
    "cost_per_kwh",
    "waiting_share",
    "stranded",
)


def _average(runs: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """Average the seeds of each setting."""
    out = []
    settings = sorted({tuple(r[k] for k in keys) for r in runs})
    for setting in settings:
        group = [r for r in runs if tuple(r[k] for k in keys) == setting]
        row = dict(zip(keys, setting, strict=True))
        for name in MEASURES:
            row[name] = round(float(np.mean([r[name] for r in group])), 4)
        out.append(row)
    return out


def _matches(row: dict) -> bool:
    """Both of the filings' counts, each within 15%: trips a visit and sessions a charger-day."""
    trips, sessions = TARGET_TRIPS_PER_VISIT, TARGET_VISITS_PER_CHARGER_DAY
    return (
        trips[0] * 0.85 <= row["trips_per_visit"] <= trips[1] * 1.15
        and sessions[0] * 0.85 <= row["visits_per_charger_day"] <= sessions[1] * 1.15
    )


def e22_cadence(workers: int = 5) -> Path:
    """E22: sweep the cadence settings, pick the one nearest the filings, and measure the findings under it."""
    from concurrent.futures import ProcessPoolExecutor

    from depot_twin.evals import E8_START, _write, replay_curves

    replay_curves(E8_START)
    jobs = [
        (leg, clean, call, chargers, seed)
        for leg in E22_LEGS
        for clean in E22_CLEAN_EVERY
        for call in E22_CALL_BELOW
        for chargers in E22_CHARGERS
        for seed in E22_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(cadence_run, jobs))
    sweep = _average(runs, ("leg", "clean_every", "call_below", "chargers"))
    middle = sum(TARGET_TRIPS_PER_VISIT) / 2
    candidates = [r for r in sweep if r["leg"] <= 8 and r["clean_every"] >= 2 and _matches(r)]
    chosen = min(
        candidates or sweep,
        key=lambda r: abs(r["trips_per_visit"] - middle) + abs(r["visits_per_charger_day"] - 20.0) / 20.0,
    )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        findings = list(pool.map(finding_run, [(arm, seed, chosen) for arm in FINDING_ARMS for seed in E22_SEEDS]))
    table = _average(findings, ("arm",))
    by = {r["arm"]: r for r in table}
    capacity, long_capacity = _capacity(table), _capacity(table, "long")
    low, high = TARGET_TRIPS_PER_VISIT
    plan, threshold = by["plan_500"], by["threshold_500"]
    bars = {
        "1_a_plausible_setting_reproduces_both_of_the_filings_counts": bool(candidates),
        "2_in_order_beats_emptiest_first_by_a_point_at_1000": by["slot_1000"]["served"] - by["need_1000"]["served"]
        >= 0.01,
        "3_capacity_at_99_within_100_vehicles_of_capacity_under_long_sessions": capacity is not None
        and long_capacity is not None
        and abs(capacity - long_capacity) <= 100,
        "4_plan_at_the_filings_cadence_buys_5pct_cheaper_at_500_rides_within_half_a_point": low * 0.85
        <= plan["trips_per_visit"]
        <= high * 1.15
        and plan["cost_per_kwh"] <= 0.95 * threshold["cost_per_kwh"]
        and abs(plan["served"] - threshold["served"]) <= 0.005,
    }
    return _write(
        "e22_cadence.json",
        {
            "eval": "E22",
            "window": "sf_e8",
            "targets": {
                "trips_per_visit": TARGET_TRIPS_PER_VISIT,
                "visits_per_charger_day": TARGET_VISITS_PER_CHARGER_DAY,
            },
            "sweep": sweep,
            "chosen": chosen,
            "findings": table,
            "capacity_at_99": capacity,
            "capacity_at_99_long_sessions": long_capacity,
            "capacity_sizes": list(CAPACITY_SIZES),
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


# Capacity is read over sizes on both sides of every answer seen so far, so the bar on it can fail either way.
CAPACITY_SIZES = (400, 500, 600, 700, 800, 900, 1000)
# `long_*` is the same depot under the long sessions every earlier test ran: called in at 20%, cleaned every
# visit, a 15-minute leg. Capacity under the filings' cadence is compared with capacity under those.
FINDING_ARMS = (
    "need_1000",
    "slot_1000",
    "plan_500",
    *(f"threshold_{size}" for size in CAPACITY_SIZES),
    *(f"long_{size}" for size in CAPACITY_SIZES),
)
LONG_SESSIONS = {"leg": 15, "clean_every": 1, "call_below": 0.20, "chargers": "rule"}
# A slot of 30 minutes delivers about 26 kWh, seven to eight trips' worth: the plan at the filings' cadence.
PLAN_BEAT_MIN = 30.0


def _capacity(table: list[dict], kind: str = "threshold") -> int | None:
    """The largest one-feeder fleet serving 99% of rides with every smaller size in the table serving it too."""
    sizes = sorted((int(r["arm"].split("_")[1]), r["served"]) for r in table if r["arm"].startswith(f"{kind}_"))
    capacity = None
    for size, served in sizes:
        if served < 0.99:
            break
        capacity = size
    return capacity


def finding_run(job: tuple) -> dict:
    """One of the findings measured under the chosen cadence: a power rule at 1,000, the plan at 500, capacity from 400 to 1,000."""
    from depot_twin.economics import Prices
    from depot_twin.evals import E8_DAYS, E8_START, E9_LEDGER, E12_SETTINGS, replay_curves
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape
    from depot_twin.heartbeat import Heartbeat
    from depot_twin.replay import ReplayDemand

    arm, seed, chosen = job
    kind, size = arm.split("_")
    size = int(size)
    if kind == "long":
        chosen = LONG_SESSIONS
    fleet, depot = _fleet_and_depot(size, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    demand = ReplayDemand.scaled(replay_curves(E8_START), size * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    prices = Prices()
    rule = (
        Heartbeat(**E9_LEDGER, prices=prices, **E12_SETTINGS, beat_min=PLAN_BEAT_MIN)
        if kind == "plan"
        else ThresholdRecall(recall_soc=chosen["call_below"], target=0.85)
    )
    policy = "need_first" if kind == "need" else "slot_power"
    result = FleetSim(fleet, depot, shape, rule, depot_policy=policy, seed=seed, demand=demand).run(E8_DAYS)
    return {"arm": arm, "seed": seed, **_measure(result, rule, depot, size)}


# ---------------------------------------------------------------------------------------------------------
# E21


def e21_demand() -> Path:
    """E21: what the service area around the parcel asks of the depot, from the filings' penetration and the census."""
    from depot_twin.evals import _write

    record = json.loads((data_dir() / "derived" / "footprint.json").read_text())
    quarters = record["quarters"]
    recent = quarters[-4:]
    penetration = float(np.mean([q["trips_per_resident_month"] for q in recent]))
    constant = [q for q in quarters if q["residents"] == quarters[-1]["residents"]]
    months = 3 * (len(constant) - 1)
    growth = (
        (constant[-1]["trips_per_resident_month"] / constant[0]["trips_per_resident_month"]) ** (1 / months) - 1
        if months
        else 0.0
    )
    # The capacity is E22's measurement and nothing else: with no E22 record there is no E21.
    capacity = json.loads((data_dir() / "derived" / "e22_cadence.json").read_text())["capacity_at_99"]
    if capacity is None:
        raise ValueError("E22 found no one-feeder fleet serving 99% of rides; E21 has no capacity to count against")
    rides_per_vehicle_day = 25.0
    elasticity = _density_elasticity()
    served_density = quarters[-1]["density"]
    areas = {}
    for name, area in record["service_areas"].items():
        adjust = (
            (area["density"] / served_density) ** elasticity["elasticity"]
            if elasticity.get("elasticity") is not None
            else 1.0
        )
        rides_day = area["population"] * penetration * adjust / 30.4
        vehicles = rides_day / rides_per_vehicle_day
        months_to_second = None
        months_to_second_slow = None
        if growth > 0 and vehicles < capacity:
            months_to_second = int(np.ceil(np.log(capacity / vehicles) / np.log(1 + growth)))
            # The measured rate is a scale-up phase; half of it is the slower case a lease decision should also see.
            months_to_second_slow = int(np.ceil(np.log(capacity / vehicles) / np.log(1 + growth / 2)))
        areas[name] = {
            **area,
            "density_adjustment": round(adjust, 3),
            "rides_per_day": round(rides_day, 0),
            "vehicles_at_25_rides": round(vehicles, 0),
            "feeders_needed": int(np.ceil(vehicles / capacity)),
            "months_until_second_feeder": months_to_second,
            "months_until_second_feeder_at_half_the_growth": months_to_second_slow,
        }
    far = areas["east_bay_20km"]
    bars = {
        "1_density_fit_loo_within_35pct_on_six_of_nine_with_positive_elasticity": elasticity.get("loo_within_35pct", 0)
        >= 6
        and (elasticity.get("elasticity") or 0) > 0,
        "2_20km_area_today_needs_fewer_vehicles_than_one_feeder_carries": far["vehicles_at_25_rides"] < capacity,
        "3_second_feeder_between_24_and_120_months_out": far["months_until_second_feeder"] is not None
        and 24 < far["months_until_second_feeder"] < 120,
    }
    return _write(
        "e21_demand.json",
        {
            "eval": "E21",
            "penetration_trips_per_resident_month": round(penetration, 4),
            "growth_per_month": round(growth, 4),
            "constant_footprint_quarters": [q["quarter"] for q in constant],
            "capacity_one_feeder": capacity,
            "rides_per_vehicle_day": rides_per_vehicle_day,
            "density": elasticity,
            "areas": areas,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def _density_elasticity() -> dict:
    """Rides per resident against residents per square kilometre across the donor areas, if their populations are known."""
    path = data_dir() / "derived" / "donor_areas.json"
    if not path.exists():
        return {"elasticity": None, "note": "donor area populations not built; the level stands on penetration alone"}
    rows = json.loads(path.read_text())
    x = np.log([r["density"] for r in rows])
    y = np.log([r["rides_per_resident_day"] for r in rows])
    within = 0
    for k in range(len(rows)):
        keep = np.arange(len(rows)) != k
        slope, intercept = np.polyfit(x[keep], y[keep], 1)
        predicted = np.exp(intercept + slope * x[k])
        within += abs(predicted / np.exp(y[k]) - 1) <= 0.35
    slope, intercept = np.polyfit(x, y, 1)
    return {
        "elasticity": round(float(slope), 3),
        "intercept": round(float(intercept), 3),
        "areas": len(rows),
        "loo_within_35pct": int(within),
        "rows": rows,
    }
