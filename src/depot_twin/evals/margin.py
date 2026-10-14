"""What one feeder carries when the vehicles' energy use is off the estimate, and the fleet to plan for.

E23 and E25 put the carried fleet at 650 vehicles with the feeder drawing nearly all its usable power.
The energy a vehicle uses on the road is assumed, and neither test moved it. E26 runs the capacity test
again with that energy 10% lower and 10% higher, in steps of 25 and 50 vehicles around the carried fleet,
and puts the plain calling rule on the same 50-vehicle steps as the rule that waits for a free charger.
The fleet to plan for is the largest one carried both as assumed and with 10% more energy use.

It also measures what the scoring leaves out at the edges of the scored week: riders offered before the
week who are served or lost inside it, and riders still waiting when the run ends.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from depot_twin.data import data_dir
from depot_twin.evals.common import _write, replay_curves

E26_ENERGY = (0.9, 1.0, 1.1)  # the vehicles' energy use on the road, against the estimate
# The fleets run at each level of energy use, under the rule that waits for a free charger.
E26_SIZES = {
    0.9: (650, 700, 725, 750, 800),
    1.0: (550, 600, 625, 650, 675, 700),
    1.1: (550, 575, 600, 625, 650),
}
E26_PLAIN_SIZES = (500, 550, 600, 650)  # the plain rule, as assumed, on the same steps
E26_MARGIN = 1.1  # a planned fleet is also carried at this much more energy use
E26_PHYSICS_WITHIN = 50  # vehicles: how far carried fleet times energy use may sit from the fleet carried as assumed
E26_EDGE_SEEDS = (2301, 2302, 2303)
E26_EDGE_SIZES = (650, 800)  # the carried fleet, and one that loses rides
E26_EDGE_MOST = 0.001  # the largest share of a scored week's rides the edges of the week may leave unsettled


def _models(fleet, energy: float) -> tuple:
    """The fleet's vehicle types with their driving energy and always-on load scaled."""
    return tuple(
        replace(m, drive_kwh_per_mile=m.drive_kwh_per_mile * energy, always_on_kw=m.always_on_kw * energy)
        for m in fleet.models
    )


def _label(energy: float) -> str:
    return f"energy_{energy:g}"


def _recorded(derived: Path) -> list[dict]:
    """The runs E23 and E25 already hold at the estimate: the same fortnights, draws and setting."""
    capacity = json.loads((derived / "e23_capacity.json").read_text())
    between = json.loads((derived / "e25_between.json").read_text())
    return [r for r in capacity["runs"] if r["label"] == "base"] + between["runs"]


class _Waiting:
    """Reads the rides waiting for a vehicle off a run, step by step."""

    def __init__(self) -> None:
        self.rows: list[tuple[float, float]] = []

    def tick(self, sim) -> None:
        self.rows.append((sim.env.now, float(sum(rides for _, rides in sim._riders))))

    def at(self, minute: float) -> float:
        """The rides waiting after the last step before a minute."""
        before = [waiting for now, waiting in self.rows if now < minute]
        return before[-1] if before else 0.0


def edge_run(job: tuple) -> dict:
    """One run of the carried fleet: the rides waiting as the scored week opens and as the run ends."""
    from depot_twin import cadence
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape

    size, window, seed, chosen = job
    passes = cadence.E23_PASSES[0]
    fleet, depot = cadence._fleet_and_depot(size, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    demand = cadence._replayed(replay_curves(window), size, fleet.rides_per_vehicle_day, passes)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    rule = ThresholdRecall(chosen["call_below"], 0.85, wait_for_charger=True)
    total = E8_DAYS * passes
    skip = total - (E8_DAYS - E8_WARMUP_DAYS)
    sim = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand)
    waiting = sim.observer = _Waiting()
    result = sim.run(total)
    scored = result.steps[result.steps[:, 0] >= skip * 1440.0]
    settled = float(scored[:, 2].sum() + scored[:, 5].sum())
    opening, closing = waiting.at(skip * 1440.0), waiting.at(total * 1440.0 + 1.0)
    return {
        "size": size,
        "window": window,
        "seed": seed,
        "rides_scored": round(settled, 1),
        "waiting_as_the_week_opens": round(opening, 2),
        "waiting_as_the_run_ends": round(closing, 2),
        "share_of_rides_scored": round((opening + closing) / settled, 6),
    }


def _verdict(runs: list[dict], sizes: tuple[int, ...], usable_kwh_a_day: float) -> dict:
    """The capacity test's verdict on a set of runs, with what each fleet drew from the feeder.

    Runs read back from a record no longer carry their account line by line, so the verdict is taken on
    the figures every run keeps, and the feeder's side is added here.
    """
    from depot_twin import cadence

    verdict = cadence.carried([{k: v for k, v in r.items() if k != "window"} for r in runs], sizes)
    for size, row in verdict["by_size"].items():
        mine = [r for r in runs if r["size"] == int(size)]

        def middle(key: str, mine: list[dict] = mine) -> float:
            return round(float(np.median([r[key] for r in mine])), 4)

        row["grid_share_used"] = middle("grid_share_used")
        row["grid_at_limit_share"] = middle("grid_at_limit_share")
        row["feeder_kwh_per_vehicle_day"] = round(row["grid_share_used"] * usable_kwh_a_day / int(size), 1)
        row["rides_lost_per_day"] = middle("rides_lost_per_day")
        row["contribution_per_day"] = middle("contribution_per_day")
        row["runs_settled"] = round(float(np.mean([r["settled"] for r in mine])), 3)
        row["carried_by_fortnight"] = {
            window: cadence.carried(
                [{k: v for k, v in r.items() if k != "window"} for r in mine if r["window"] == window], (int(size),)
            )["capacity"]
            == int(size)
            for window in sorted({r["window"] for r in mine})
        }
    return verdict


def e26_margin(workers: int = 5) -> Path:
    """E26: the fleet one feeder carries with energy use 10% either side of the estimate, and both rules on one set of steps."""
    from depot_twin import cadence

    derived = data_dir() / "derived"
    record = json.loads((derived / "e23_capacity.json").read_text())
    chosen, best = record["setting"], record["best_rule"]
    for window in cadence.E23_WINDOWS:
        replay_curves(window)
    held = _recorded(derived)
    have = {(r["rule"], r["size"]) for r in held}
    fleet, depot = cadence._fleet_and_depot(600, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    cells = [(best, energy, size) for energy in E26_ENERGY for size in E26_SIZES[energy]]
    cells += [("threshold", 1.0, size) for size in E26_PLAIN_SIZES]
    jobs = [
        (_label(energy), rule, "slot_power", size, window, seed, chosen, {"models": _models(fleet, energy)})
        for rule, energy, size in cells
        if energy != 1.0 or (rule, size) not in have
        for window in cadence.E23_WINDOWS
        for seed in cadence.E23_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(cadence.capacity_run, jobs, chunksize=4))
        edges = list(
            pool.map(
                edge_run,
                [
                    (size, window, seed, chosen)
                    for size in E26_EDGE_SIZES
                    for window in cadence.E23_WINDOWS
                    for seed in E26_EDGE_SEEDS
                ],
            )
        )
    # The runs already held at the estimate join the new ones under the same label.
    runs += [
        {**r, "label": _label(1.0), "from": "E25" if r["size"] == 650 else "E23"}
        for r in held
        if (r["rule"] == best and r["size"] in E26_SIZES[1.0])
        or (r["rule"] == "threshold" and r["size"] in E26_PLAIN_SIZES)
    ]
    usable_kwh_a_day = depot.usable_kw * 24.0
    by_energy = {
        f"{energy:g}": _verdict(
            [r for r in runs if r["label"] == _label(energy) and r["rule"] == best], E26_SIZES[energy], usable_kwh_a_day
        )
        for energy in E26_ENERGY
    }
    plain = _verdict(
        [r for r in runs if r["label"] == _label(1.0) and r["rule"] == "threshold"], E26_PLAIN_SIZES, usable_kwh_a_day
    )
    carried = {energy: verdict["capacity"] for energy, verdict in by_energy.items()}
    # The fleet to plan for: the largest carried as assumed and at the margin, among fleets run at both.
    both = [size for size in E26_SIZES[1.0] if size in E26_SIZES[E26_MARGIN]]
    planned = max(
        (size for size in both if size <= (carried["1"] or 0) and size <= (carried[f"{E26_MARGIN:g}"] or 0)),
        default=None,
    )
    # On the steps both rules were run on: what each carries.
    shared = E26_PLAIN_SIZES
    waits_on_shared = max((size for size in shared if size <= (carried["1"] or 0)), default=None)
    at_estimate = carried["1"] or 0
    scaled = {energy: (fleet_ or 0) * float(energy) for energy, fleet_ in carried.items()}
    bars = {
        "1_600_vehicles_are_carried_with_10pct_more_energy_use": (carried["1.1"] or 0) >= 600,
        "2_the_carried_fleet_does_not_rise_as_energy_use_rises": (carried["0.9"] or 0)
        >= at_estimate
        >= (carried["1.1"] or 0),
        "3_carried_fleet_times_energy_use_stays_within_50_vehicles": all(
            abs(value - at_estimate) <= E26_PHYSICS_WITHIN for value in scaled.values()
        ),
        "4_waiting_for_a_charger_carries_50_vehicles_more_than_the_plain_rule_on_the_same_steps": (waits_on_shared or 0)
        - (plain["capacity"] or 0)
        >= 50,
        "5_the_edges_of_the_scored_week_leave_under_a_thousandth_of_its_rides_unsettled": max(
            e["share_of_rides_scored"] for e in edges
        )
        <= E26_EDGE_MOST,
    }
    return _write(
        "e26_margin.json",
        {
            "eval": "E26",
            "rule": best,
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(cadence.E23_SEEDS),
            "energy_use_against_the_estimate": list(E26_ENERGY),
            "sizes": {f"{energy:g}": list(sizes) for energy, sizes in E26_SIZES.items()},
            "usable_kwh_a_day": round(usable_kwh_a_day, 0),
            "by_energy": by_energy,
            "carried": carried,
            "carried_times_energy_use": {energy: round(value, 0) for energy, value in scaled.items()},
            "planned_fleet": planned,
            "planned_rides_per_day": (planned or 0) * record["rides_per_vehicle_day"],
            "margin": E26_MARGIN,
            "plain_rule": plain,
            "on_the_same_steps": {
                "steps": list(shared),
                "waits_for_a_charger": waits_on_shared,
                "plain": plain["capacity"],
            },
            "edges_of_the_scored_week": {
                "runs": edges,
                "largest_share_of_rides_scored": max(e["share_of_rides_scored"] for e in edges),
            },
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
