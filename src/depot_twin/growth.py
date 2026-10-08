"""How far one site carries a growing fleet, and what to add when it stops.

The fleet is grown from 200 to 2,000 vehicles on the same parcel. Chargers, cleaning bays and staff are
scaled with the fleet, because those can be bought. The grid connection is not scaled, because it cannot:
it is whatever the feeders have. The study reports where rides start to be lost, which resource is
saturated at that point, and how much further each remedy carries the site.
"""

from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import numpy as np

from depot_twin import sizing
from depot_twin.dispatch import HeadroomRecall
from depot_twin.fleet import FleetConfig, FleetSim, load_fleet_scenario, load_weekly_shape, served_share
from depot_twin.resources import DAY_MIN, Buffer, ChargerBank, DepotConfig

TEMPLATE = "scenarios/east_oakland_200.toml"
SHAPE = "data/derived/weekly_shape.json"
KWH_PER_VEHICLE_DAY = 95.0  # measured in the unconstrained 200-vehicle run
CHARGER_KW_AVERAGE = 50.0  # a 60 kW charger averaged over a session with taper
CHARGER_USE = 0.6  # planned share of the day a charger is delivering

# What can be done about the grid, cheapest and fastest first.
OPTIONS: dict[str, dict] = {
    "one_feeder": {"site_limit_kw": 2750.0},
    "one_feeder_with_buffer": {"site_limit_kw": 2750.0, "buffer": Buffer(energy_kwh=4000.0, power_kw=2000.0)},
    "two_feeders": {"site_limit_kw": 5500.0},
}


def chargers_for(size: int) -> int:
    """Return the charger count for a fleet: its daily energy over what one charger delivers in a day."""
    return math.ceil(size * KWH_PER_VEHICLE_DAY / (CHARGER_KW_AVERAGE * 24 * CHARGER_USE))


def charger_ceiling(depot: DepotConfig, charger_kw: float = 60.0) -> int:
    """The most plugs a site takes: two for every one its usable connection feeds at once, as paired dispensers share a cabinet.

    The grid bounds power, not plugs; a load manager may plug in more than it feeds. Past two per fed plug the
    extra ones only idle (E19 found half as many again bought nothing), so the page and the local tool stop there.
    """
    return max(2, 2 * int(depot.usable_kw * depot.charger_efficiency // charger_kw))


def energy_limited_fleet(site_limit_kw: float, efficiency: float = 0.93, usable_share: float = 0.95) -> int:
    """Return the hand answer: the fleet whose daily energy equals what the connection's usable share delivers flat out."""
    return int(site_limit_kw * usable_share * efficiency * 24 / KWH_PER_VEHICLE_DAY)


def scaled(size: int, site_limit_kw: float, buffer: Buffer | None = None) -> tuple[FleetConfig, DepotConfig]:
    """Return the East Oakland fleet and depot at a given size and grid connection."""
    fleet, depot = load_fleet_scenario(TEMPLATE)
    people = max(4, size // 40)
    depot = replace(
        depot,
        name=f"East Oakland, {size} vehicles",
        site_limit_kw=site_limit_kw,
        chargers=(ChargerBank("dc", chargers_for(size), 60.0),),
        buffer=buffer,
        staff=people,
        cleaning_bays=people,
    )
    return replace(fleet, size=size), depot


def run_one(task: tuple[str, int, int, float]) -> dict:
    """Run one fleet size under one grid option and one seed."""
    option, size, seed, days = task
    fleet, depot = scaled(size, **OPTIONS[option])
    # One day more than asked for, and the first left out of rides served: the fleet settling from its starting charge.
    result = FleetSim(fleet, depot, load_weekly_shape(SHAPE), HeadroomRecall(), seed=seed).run(days + 1)
    summary = result.summary()
    series = result.depot.series
    chargers = depot.chargers[0].count
    return {
        "option": option,
        "size": size,
        "seed": seed,
        "rides_served_share": served_share(result.steps[result.steps[:, 0] >= DAY_MIN]),
        "available_at_peak_share": summary["available_at_peak_share"],
        "queue_wait_min": summary["depot_queue_wait_mean_min"],
        "grid_use": float(series[:, 1].mean() / depot.usable_kw),
        "charger_use": float(series[:, 3].mean() / chargers),
        "peak_grid_kw": summary["depot_peak_grid_kw"],
    }


def sweep(sizes: list[int], seeds: list[int], days: float = 7.0, workers: int = 4) -> list[dict]:
    """Run every option at every size and seed, and return one averaged row per option and size."""
    tasks = [(option, size, seed, days) for option in OPTIONS for size in sizes for seed in seeds]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(run_one, tasks))
    rows = []
    for option in OPTIONS:
        for size in sizes:
            group = [r for r in runs if r["option"] == option and r["size"] == size]
            row = {"option": option, "size": size, "chargers": chargers_for(size)}
            for key in ("rides_served_share", "available_at_peak_share", "queue_wait_min", "grid_use", "charger_use"):
                row[key] = round(float(np.mean([r[key] for r in group])), 4)
            rows.append(row)
    return rows


def largest_fleet(rows: list[dict], option: str, served_at_least: float) -> int:
    """Return the largest simulated fleet under an option that still serves the given share of rides."""
    good = [r["size"] for r in rows if r["option"] == option and r["rides_served_share"] >= served_at_least]
    return max(good, default=0)


def hand_check(site_limit_kw: float) -> dict:
    """Return the planner's arithmetic for a connection, for comparison with the simulation."""
    fleet = energy_limited_fleet(site_limit_kw)
    return {
        "site_limit_kw": site_limit_kw,
        "energy_limited_fleet": fleet,
        "daily_energy_kwh": round(sizing.daily_energy_kwh(fleet, 1.0, KWH_PER_VEHICLE_DAY), 0),
    }


# The second version of the study: each vehicle type has its own energy use, demand is replayed from real
# days, and the heartbeat controller is compared with the headroom rule at every size.
TEMPLATE_V2 = "scenarios/v2/east_oakland_500.toml"
RULES_V2 = ("headroom", "heartbeat")


def scaled_v2(size: int, site_limit_kw: float, buffer: Buffer | None = None) -> tuple[FleetConfig, DepotConfig]:
    """Return the second-version East Oakland fleet and depot at a given size and grid connection."""
    fleet, depot = load_fleet_scenario(TEMPLATE_V2)
    people = max(4, size // 40)
    depot = replace(
        depot,
        name=f"East Oakland, {size} vehicles",
        site_limit_kw=site_limit_kw,
        chargers=(ChargerBank("dc", chargers_for(size), 60.0),),
        buffer=buffer,
        staff=people,
        cleaning_bays=people,
    )
    return replace(fleet, size=size), depot


def run_one_v2(job: tuple[str, str, int, int, str]) -> dict:
    """Run one rule at one fleet size under one grid option and seed, on replayed demand."""
    from depot_twin import evals
    from depot_twin.replay import ReplayDemand

    option, rule_name, size, seed, start = job
    fleet, depot = scaled_v2(size, **OPTIONS[option])
    demand = ReplayDemand.scaled(evals.replay_curves(start), size * fleet.rides_per_vehicle_day)
    rule = evals._e8_rule(rule_name)
    policy = "slot_power" if rule_name == "heartbeat" else "need_first"
    sim = FleetSim(fleet, depot, load_weekly_shape(SHAPE), rule, depot_policy=policy, seed=seed, demand=demand)
    result = sim.run(evals.E8_DAYS)
    first = evals.E8_WARMUP_DAYS * 1440.0
    steps = result.steps[result.steps[:, 0] >= first]
    series = result.depot.series[result.depot.series[:, 0] >= first]
    busy = steps[:, 1] >= np.quantile(steps[:, 1], 0.9)
    return {
        "option": option,
        "rule": rule_name,
        "size": size,
        "seed": seed,
        "rides_served_share": served_share(steps),
        "on_road_when_busiest": float(steps[busy, 3].mean() / size),
        "grid_use": float(series[:, 1].mean() / depot.usable_kw),
        "grid_variation": float(series[:, 1].std() / max(series[:, 1].mean(), 1e-9)),
        "stranded": float(result.stranded),
    }


def sweep_v2(sizes: list[int], seeds: list[int], start: str, workers: int = 5) -> list[dict]:
    """Run every option, rule, size and seed, and return one averaged row per option, rule and size."""
    jobs = [(o, r, size, seed, start) for o in OPTIONS for r in RULES_V2 for size in sizes for seed in seeds]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(run_one_v2, jobs))
    rows = []
    for option in OPTIONS:
        for rule in RULES_V2:
            for size in sizes:
                group = [r for r in runs if (r["option"], r["rule"], r["size"]) == (option, rule, size)]
                row = {"option": option, "rule": rule, "size": size, "chargers": chargers_for(size)}
                for key in ("rides_served_share", "on_road_when_busiest", "grid_use", "grid_variation", "stranded"):
                    row[key] = round(float(np.mean([r[key] for r in group])), 4)
                rows.append(row)
    return rows
