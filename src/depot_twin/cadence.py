"""E22: the twin against the real visit cadence; E23: what one feeder carries; E21: what the service area asks.

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


def _measure(result, rule, depot, size: int, total_days: int | None = None, skip_days: int | None = None) -> dict:
    """What one run did over its scored week: rides, cadence as it actually ran, cost of energy, queueing."""
    from depot_twin.economics import Prices, energy_by_period
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS
    from depot_twin.evals.common import what_ran
    from depot_twin.fleet import served_share

    total_days, skip_days = total_days or E8_DAYS, E8_WARMUP_DAYS if skip_days is None else skip_days
    first = skip_days * 1440.0
    days = total_days - skip_days
    steps = result.steps[result.steps[:, 0] >= first]
    count = sum(b.count for b in depot.chargers)
    energy = energy_by_period(result.depot.series, skip_days=skip_days)
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
    # Two readings of where demand stands: the year's average, which the bars are scored on, and the
    # latest quarter, which is higher while the service is growing.
    levels = {"last_four_quarters": penetration, "latest_quarter": float(quarters[-1]["trips_per_resident_month"])}
    constant = [q for q in quarters if q["residents"] == quarters[-1]["residents"]]
    ways = growth_estimates([q["trips_per_resident_month"] for q in constant])
    growth = ways["first_to_last"]
    # The capacity is E23's measurement and nothing else: with no E23 record there is no E21.
    capacity = json.loads((data_dir() / "derived" / "e23_capacity.json").read_text())["capacity"]
    if capacity is None:
        raise ValueError("E23 found no one-feeder fleet it would call carried; E21 has no capacity to count against")
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
        months_to_second = months_until(capacity, vehicles, growth)
        # The measured rate is a scale-up phase; half of it is the slower case a lease decision should also see.
        months_to_second_slow = months_until(capacity, vehicles, growth / 2)
        by_way = {name: months_until(capacity, vehicles, rate) for name, rate in ways.items()}
        by_level = {}
        for level, trips in levels.items():
            fleet = area["population"] * trips * adjust / 30.4 / rides_per_vehicle_day
            by_level[level] = {
                "rides_per_day": round(fleet * rides_per_vehicle_day, 0),
                "vehicles_at_25_rides": round(fleet, 0),
                "months_until_second_feeder_by_estimate": {
                    name: months_until(capacity, fleet, rate) for name, rate in ways.items()
                },
            }
        reached = [
            m
            for row in by_level.values()
            for m in row["months_until_second_feeder_by_estimate"].values()
            if m is not None
        ]
        areas[name] = {
            **area,
            "density_adjustment": round(adjust, 3),
            "rides_per_day": round(rides_day, 0),
            "vehicles_at_25_rides": round(vehicles, 0),
            "feeders_needed": int(np.ceil(vehicles / capacity)),
            "months_until_second_feeder": months_to_second,
            "months_until_second_feeder_at_half_the_growth": months_to_second_slow,
            "months_until_second_feeder_by_estimate": by_way,
            "by_level": by_level,
            "vehicles_range": sorted(row["vehicles_at_25_rides"] for row in by_level.values()),
            # Across both readings of the level and all three readings of growth.
            "months_until_second_feeder_range": [min(reached), max(reached)] if reached else None,
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
            "penetration_by_level": {name: round(value, 4) for name, value in levels.items()},
            "growth_per_month": round(growth, 4),
            "growth_per_month_by_estimate": {name: round(rate, 6) for name, rate in ways.items()},
            "constant_footprint_quarters": [q["quarter"] for q in constant],
            "capacity_one_feeder": capacity,
            "rides_per_vehicle_day": rides_per_vehicle_day,
            "density": elasticity,
            "areas": areas,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def growth_estimates(per_quarter: list[float]) -> dict[str, float]:
    """Three readings of monthly growth from quarterly figures at a constant footprint.

    The first quarter to the last, as one compound rate; a straight line through the logs of all of them;
    and the last six months alone (the latest quarter over the one two before it). They differ when growth
    came in one jump, and a date that depends on growth should be read off all three.
    """
    values = np.asarray(per_quarter, dtype=float)
    if len(values) < 2:
        return {"first_to_last": 0.0, "fitted": 0.0, "last_six_months": 0.0}
    months = 3.0 * np.arange(len(values))
    return {
        "first_to_last": float((values[-1] / values[0]) ** (1.0 / months[-1]) - 1.0),
        "fitted": float(np.exp(np.polyfit(months, np.log(values), 1)[0]) - 1.0),
        "last_six_months": float((values[-1] / values[-3]) ** (1.0 / 6.0) - 1.0) if len(values) >= 3 else 0.0,
    }


def months_until(capacity: float, vehicles: float, growth: float) -> int | None:
    """Months until demand growing at a monthly rate reaches a capacity; None when it never does, 0 when it has."""
    if vehicles >= capacity:
        return 0
    if growth <= 0:
        return None
    return int(np.ceil(np.log(capacity / vehicles) / np.log(1.0 + growth)))


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


# ---------------------------------------------------------------------------------------------------------
# E23

E23_WINDOWS = ("2024-03-18", "2024-04-15", "2024-04-29", "2024-05-13")  # the four replayed fortnights
E23_SEEDS = tuple(range(2301, 2311))
E23_SIZES = (500, 600, 700, 800, 900)
E23_RULES = ("threshold", "threshold_waits", "plan")
E23_CONFIDENCE = 0.9  # a fleet is carried when this share of runs serves the floor
E23_FLOOR = 0.99
E23_RULE_IN_CHARGE = 0.5  # at most this share of vehicles may arrive at the low-battery level
E23_FEW_SEEDS = E23_SEEDS[:3]
# The fortnight is replayed this many times and the last week scored. A run that has not settled by then,
# its scored week reading differently from the same week a pass earlier, is run again at the next count.
E23_PASSES = (2, 4, 8)
E23_SETTLED = {"arrived_at_floor_share": 0.02, "charge_on_the_road": 0.005}  # the most a settled run may still move
# One input moved at a time, under the rule that carried most: (label, fleet changes, sizes).
E23_MOVED = (
    ("rides_18", {"rides_per_vehicle_day": 18.0}, (600, 700, 800, 900, 1000, 1100, 1200)),
    ("rides_21.5", {"rides_per_vehicle_day": 21.5}, (600, 700, 800, 900, 1000)),
    ("ride_minutes_18", {"ride_minutes": 18.0}, E23_SIZES),
    ("ride_minutes_28", {"ride_minutes": 28.0}, E23_SIZES),
    ("wait_5", {"max_wait_minutes": 5.0}, E23_SIZES),
    ("wait_15", {"max_wait_minutes": 15.0}, E23_SIZES),
)


class _Watch:
    """Reads two things off a run as it goes: the charge of the vehicles on the road, and vehicles between stations."""

    def __init__(self) -> None:
        self.rows: list[tuple[float, float, int]] = []

    def tick(self, sim) -> None:
        from depot_twin.fleet import AT_DEPOT, ON_ROAD

        depot = sim.depot
        on_road = sim.status == ON_ROAD
        between = int((sim.status == AT_DEPOT).sum()) - len(depot.waiting) - len(depot.charging) - depot.bays.count
        self.rows.append((sim.env.now, float(sim.soc[on_road].mean()) if on_road.any() else 0.0, between))

    def between(self, first_day: int, last_day: int) -> np.ndarray:
        rows = np.asarray(self.rows)
        return rows[(rows[:, 0] >= first_day * 1440.0) & (rows[:, 0] < last_day * 1440.0)]


def _replayed(curves: dict, size: int, rides_per_vehicle_day: float, passes: int):
    """The fortnight replayed a number of times, scaled so the scored week offers the rides asked for.

    A fleet starts every run with the same spread of charge, and a week is not always enough for a fleet at
    the edge of what a feeder carries to settle to the level it would hold. So the fortnight is run more
    than once and only the last week counts. The scaling is taken on that week, the fortnight's second, so
    that a fleet of a given size is offered the same rides a day in every fortnight.
    """
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS
    from depot_twin.replay import ReplayDemand

    scored = curves["counts"][len(curves["counts"]) * E8_WARMUP_DAYS // E8_DAYS :]
    whole = float(curves["counts"].mean())
    tiled = {name: np.concatenate([values] * passes) for name, values in curves.items()}
    return ReplayDemand.scaled(tiled, size * rides_per_vehicle_day * whole / float(scored.mean()))


def capacity_run(job: tuple) -> dict:
    """One fleet under one calling rule and one power rule on one fortnight, replayed until its scored week has settled."""
    for passes in E23_PASSES:
        run = _capacity_run(job, passes)
        run["settled"] = all(abs(run[key] - run[f"{key}_a_pass_earlier"]) <= most for key, most in E23_SETTLED.items())
        if run["settled"]:
            break
    return run


def _capacity_run(job: tuple, passes: int) -> dict:
    """One fleet under one calling rule and one power rule on one fortnight replayed `passes` times, at the cadence setting E22 chose."""
    from depot_twin import finance
    from depot_twin.dispatch import HARD_FLOOR_SOC
    from depot_twin.economics import Prices
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS, E9_LEDGER, E12_SETTINGS, replay_curves
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape
    from depot_twin.heartbeat import Heartbeat

    label, rule_name, policy, size, window, seed, chosen, moved = job
    fleet, depot = _fleet_and_depot(size, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    fleet = replace(fleet, **moved)
    demand = _replayed(replay_curves(window), size, fleet.rides_per_vehicle_day, passes)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    if rule_name == "plan":
        rule = Heartbeat(**E9_LEDGER, prices=Prices(), **E12_SETTINGS, beat_min=PLAN_BEAT_MIN)
    else:
        rule = ThresholdRecall(chosen["call_below"], 0.85, wait_for_charger=rule_name == "threshold_waits")
    total = E8_DAYS * passes
    skip = total - (E8_DAYS - E8_WARMUP_DAYS)
    sim = FleetSim(fleet, depot, shape, rule, depot_policy=policy, seed=seed, demand=demand)
    watch = sim.observer = _Watch()
    result = sim.run(total)
    measured = _measure(result, rule, depot, size, total, skip)
    books = finance.account(result, depot, size, total, skip)
    scored = result.steps[result.steps[:, 0] >= skip * 1440.0]
    series = result.depot.series[result.depot.series[:, 0] >= skip * 1440.0]
    # The same week one pass earlier: if the fleet had settled, it reads the same.
    earlier = [
        s.visit.soc_in <= HARD_FLOOR_SOC
        for s in result.depot.sessions
        if (skip - E8_DAYS) * 1440.0 <= s.visit.arrive_min < (total - E8_DAYS) * 1440.0
    ]
    now, before = watch.between(skip, total), watch.between(skip - E8_DAYS, total - E8_DAYS)
    return {
        "label": label,
        "rule": rule_name,
        "policy": policy,
        "size": size,
        "window": window,
        "seed": seed,
        "passes": passes,
        "rides_offered_per_day": round(float(scored[:, 1].sum()) / (total - skip), 1),
        **{
            key: round(float(measured[key]), 5)
            for key in (
                "served",
                "trips_per_visit",
                "cost_per_kwh",
                "arrived_at_floor_share",
                "stranded",
                "forced_call_share",
                "quota_at_ceiling_share",
                "quota_unfilled_share",
            )
        },
        "arrived_at_floor_share_a_pass_earlier": round(float(np.mean(earlier)) if earlier else 0.0, 5),
        # Visits the 8% floor forced, as a share of the scored week's visits: the rest were the rule's own calls.
        "floor_forced_share": round(
            sum(1 for m in result.forced_calls if m >= skip * 1440.0)
            / max(sum(1 for s in result.depot.sessions if s.visit.arrive_min >= skip * 1440.0), 1),
            5,
        ),
        "charge_on_the_road": round(float(now[:, 1].mean()), 4),
        "charge_on_the_road_a_pass_earlier": round(float(before[:, 1].mean()), 4),
        "between_stations": round(float(now[:, 2].mean()), 2),
        "grid_share_used": round(float(series[:, 1].mean()) / depot.usable_kw, 4),
        "grid_at_limit_share": round(float((series[:, 1] >= 0.98 * depot.usable_kw).mean()), 4),
        "contribution_per_day": books["contribution_per_day"],
        "rides_lost_per_day": books["rides_lost_per_day"],
        "per_day": books["per_day"],
    }


def _spread(values: list[float]) -> dict:
    """The middle of a set of runs and the range most of them fall in."""
    array = np.asarray(values, dtype=float)
    return {
        "median": round(float(np.median(array)), 4),
        "p10": round(float(np.quantile(array, 0.1)), 4),
        "p90": round(float(np.quantile(array, 0.9)), 4),
        "runs": len(array),
    }


def _detail(mine: list[dict]) -> dict:
    """What the runs of one fleet size say beyond rides: whether the fleet had settled, the grid, and the account."""
    middle = lambda key: round(float(np.median([r[key] for r in mine])), 4)  # noqa: E731
    return {
        "arrived_at_floor_share_by_fortnight": {
            window: round(float(np.median([r["arrived_at_floor_share"] for r in mine if r["window"] == window])), 4)
            for window in sorted({r["window"] for r in mine})
        },
        # Settled or not: the same week one pass earlier, and the charge on the road in each.
        "arrived_at_floor_share_a_pass_earlier": middle("arrived_at_floor_share_a_pass_earlier"),
        "floor_forced_share": round(float(np.median([r.get("floor_forced_share", 0.0) for r in mine])), 4),
        "charge_on_the_road": middle("charge_on_the_road"),
        "charge_on_the_road_a_pass_earlier": middle("charge_on_the_road_a_pass_earlier"),
        "grid_share_used": middle("grid_share_used"),
        "grid_at_limit_share": middle("grid_at_limit_share"),
        "rides_offered_per_day": middle("rides_offered_per_day"),
        "runs_settled": round(float(np.mean([r["settled"] for r in mine])), 3),
        "passes": sorted({r["passes"] for r in mine}),
        "rides_lost_per_day": _spread([r["rides_lost_per_day"] for r in mine]),
        "contribution_per_day": _spread([r["contribution_per_day"] for r in mine]),
        "per_day": {name: round(float(np.mean([r["per_day"][name] for r in mine])), 2) for name in mine[0]["per_day"]},
    }


def _at_planned_fleets(base: list[dict], runs: list[dict], best: str, planned: list[int]) -> dict:
    """The power rule at the fleets a site would be planned for: in order less emptiest first, run for run."""
    out = {}
    for size in planned:
        in_order = [r for r in base if r["rule"] == best and r["size"] == size]
        emptiest = [r for r in runs if r["label"] == "power_at_fleet" and r["size"] == size]
        apart = _paired(in_order + emptiest, {"policy": "slot_power"}, {"policy": "need_first"}, "served")
        alone = carried(emptiest, (size,))
        out[str(size)] = {
            "gain": _spread(apart),
            "emptiest_first": alone["by_size"][str(size)],
            "emptiest_first_carried": alone["capacity"] == size,
        }
    return out


def carried(runs: list[dict], sizes: tuple[int, ...]) -> dict:
    """By fleet size: the spread of rides served and the share of runs at the floor; and the largest fleet carried.

    A fleet is carried when at least nine runs in ten serve the service floor, the calling rule and not the
    low-battery floor is bringing most vehicles in, and every smaller fleet is carried too. The second
    condition matters: a fleet can serve its rides for a fortnight with nearly every vehicle arriving at
    the emergency level, and that is a depot with no margin, not a depot with capacity. The largest fleet
    that serves its rides on any terms is kept beside it.
    """
    by_size, capacity, serving = {}, None, None
    still = still_serving = True
    for size in sizes:
        mine = [r for r in runs if r["size"] == size]
        if not mine:
            still = still_serving = False
            continue
        served = [r["served"] for r in mine]
        at_floor = float(np.mean([s >= E23_FLOOR for s in served]))
        low_battery = float(np.median([r["arrived_at_floor_share"] for r in mine]))
        by_size[str(size)] = {
            **_spread(served),
            "runs_at_floor": round(at_floor, 3),
            "trips_per_visit": round(float(np.median([r["trips_per_visit"] for r in mine])), 2),
            "arrived_at_floor_share": round(low_battery, 4),
            "stranded": round(float(np.sum([r["stranded"] for r in mine])), 0),
            **(_detail(mine) if "window" in mine[0] else {}),
        }
        still_serving = still_serving and at_floor >= E23_CONFIDENCE
        still = still and still_serving and low_battery <= E23_RULE_IN_CHARGE
        if still_serving:
            serving = size
        if still:
            capacity = size
    return {"by_size": by_size, "capacity": capacity, "largest_serving_the_floor": serving}


def _paired(runs: list[dict], first: dict, second: dict, key: str, ratio: bool = False) -> list[float]:
    """For each fortnight and seed, the first arm's figure less the second's (or one less their ratio)."""

    def pick(match: dict) -> dict:
        return {(r["window"], r["seed"]): r[key] for r in runs if all(r[k] == v for k, v in match.items())}

    a, b = pick(first), pick(second)
    return [(1.0 - a[k] / b[k]) if ratio else (a[k] - b[k]) for k in sorted(a) if k in b]


def e23_capacity(workers: int = 5) -> Path:
    """E23: what one feeder carries, as a spread over seeds and weeks, under three ways of calling vehicles in."""
    from concurrent.futures import ProcessPoolExecutor

    from depot_twin.evals import _write, replay_curves

    chosen = json.loads((data_dir() / "derived" / "e22_cadence.json").read_text())["chosen"]
    for window in E23_WINDOWS:
        replay_curves(window)
    jobs = [
        ("base", rule, "slot_power", size, window, seed, chosen, {})
        for rule in E23_RULES
        for size in E23_SIZES
        for window in E23_WINDOWS
        for seed in E23_SEEDS
    ]
    jobs += [
        ("power", "threshold", policy, 1000, window, seed, chosen, {})
        for policy in ("slot_power", "need_first")
        for window in E23_WINDOWS
        for seed in E23_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(capacity_run, jobs, chunksize=4))
    base = [r for r in runs if r["label"] == "base"]
    rules = {rule: carried([r for r in base if r["rule"] == rule], E23_SIZES) for rule in E23_RULES}
    best = max(E23_RULES, key=lambda rule: (rules[rule]["capacity"] or 0, rule == "threshold_waits"))
    # The inputs are moved under the rule that carried most, which is only known once the runs above are in.
    more = [
        (label, best, "slot_power", size, window, seed, chosen, changes)
        for label, changes, sizes in E23_MOVED
        for size in sizes
        for window in E23_WINDOWS
        for seed in E23_FEW_SEEDS
    ]
    # The power rule at the fleets a site would be planned for, under the same rule, on the same forty runs.
    top = rules[best]["capacity"] or E23_SIZES[0]
    planned = [size for size in E23_SIZES if top - 100 <= size <= top]
    more += [
        ("power_at_fleet", best, "need_first", size, window, seed, chosen, {})
        for size in planned
        for window in E23_WINDOWS
        for seed in E23_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs += list(pool.map(capacity_run, more, chunksize=4))
    by_window = {
        window: carried([r for r in base if r["rule"] == best and r["window"] == window], E23_SIZES)["capacity"]
        for window in E23_WINDOWS
    }
    moved = {
        label: carried([r for r in runs if r["label"] == label], sizes)
        | {"rides_per_vehicle_day": changes.get("rides_per_vehicle_day", 25.0)}
        for label, changes, sizes in E23_MOVED
    }
    power = [r for r in runs if r["label"] == "power"]
    gap = _paired(power, {"policy": "slot_power"}, {"policy": "need_first"}, "served")
    at_fleet = _at_planned_fleets(base, runs, best, planned)
    at_500 = [r for r in base if r["size"] == 500]
    saving = _paired(at_500, {"rule": "plan"}, {"rule": "threshold"}, "cost_per_kwh", ratio=True)
    rides_apart = _paired(at_500, {"rule": "plan"}, {"rule": "threshold"}, "served")
    capacities = [c for c in by_window.values() if c is not None]
    bars = {
        "1_waiting_for_a_charger_carries_no_fewer_vehicles_than_the_plain_threshold": (
            rules["threshold_waits"]["capacity"] or 0
        )
        >= (rules["threshold"]["capacity"] or 0),
        "2_in_order_beats_emptiest_first_by_a_point_in_nine_runs_in_ten": float(np.mean([g >= 0.01 for g in gap]))
        >= E23_CONFIDENCE,
        "3_plan_buys_5pct_cheaper_at_500_with_rides_within_half_a_point_in_nine_runs_in_ten": float(
            np.mean([s >= 0.05 and abs(d) <= 0.005 for s, d in zip(saving, rides_apart, strict=True)])
        )
        >= E23_CONFIDENCE,
        "4_capacity_under_the_best_rule_within_one_fleet_step_across_the_four_fortnights": len(capacities)
        == len(E23_WINDOWS)
        and max(capacities) - min(capacities) <= 100,
    }
    return _write(
        "e23_capacity.json",
        {
            "eval": "E23",
            "windows": list(E23_WINDOWS),
            "seeds": list(E23_SEEDS),
            "setting": chosen,
            "passes": list(E23_PASSES),
            "settled_when_within": E23_SETTLED,
            "rides_per_vehicle_day": 25.0,
            "floor": E23_FLOOR,
            "confidence": E23_CONFIDENCE,
            "rules": rules,
            "best_rule": best,
            "capacity": rules[best]["capacity"],
            "capacity_rides_per_day": (rules[best]["capacity"] or 0) * 25.0,
            "capacity_by_fortnight": by_window,
            "largest_serving_the_floor": {rule: rules[rule]["largest_serving_the_floor"] for rule in E23_RULES},
            "rule_in_charge_at_most": E23_RULE_IN_CHARGE,
            "inputs_moved": moved,
            "power_rule_gain": {
                **_spread(gap),
                "runs_with_a_point_or_more": round(float(np.mean([g >= 0.01 for g in gap])), 3),
            },
            "power_rule_served": {
                policy: _spread([r["served"] for r in power if r["policy"] == policy])
                for policy in ("slot_power", "need_first")
            },
            # Why: the share of the usable connection drawn, and the vehicles standing between stations.
            "power_rule_grid_share_used": {
                policy: _spread([r["grid_share_used"] for r in power if r["policy"] == policy])
                for policy in ("slot_power", "need_first")
            },
            "power_rule_between_stations": {
                policy: _spread([r["between_stations"] for r in power if r["policy"] == policy])
                for policy in ("slot_power", "need_first")
            },
            "power_rule_at_planned_fleets": at_fleet,
            "plan_energy_saving_at_500": _spread(saving),
            "plan_rides_less_threshold_at_500": _spread(rides_apart),
            "trips_per_visit": {
                rule: _spread([r["trips_per_visit"] for r in at_500 if r["rule"] == rule]) for rule in E23_RULES
            },
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
