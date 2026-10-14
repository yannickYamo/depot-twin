"""What one feeder carries if a vehicle's always-on load keeps running inside the depot.

The fleet model drains a vehicle's always-on load, its computers, sensors and climate control, on the road
and on the drive to and from the depot. A vehicle waiting, charging or being cleaned draws nothing. That
is a choice the estimate makes, and it flatters the feeder: a parked vehicle that stays switched on takes
energy the feeder has to give back. E27 runs the capacity test with that load counted for every minute a
vehicle spends in the depot, taken from its battery as it leaves, at the estimated energy use and with
10% more on the road, around the fleets E26 carried.

The runs are `cadence.capacity_run` with one method of the fleet model replaced in the worker processes;
the simulator's own code is not changed, and every other record keeps the model it was measured on.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np

from depot_twin.data import data_dir
from depot_twin.evals.common import _write, replay_curves

E27_ENERGY = (1.0, 1.1)
E27_SIZES = {1.0: (600, 625, 650, 675), 1.1: (550, 575, 600)}
E27_MOST_LOST = 50  # vehicles: the most the parked load may take off the carried fleet at the estimate


def _count_parked_load() -> None:
    """In this process, charge every vehicle leaving the depot for the always-on load of its minutes inside."""
    from depot_twin import fleet

    if getattr(fleet.FleetSim, "_parked_load_counted", False):
        return
    hand_back = fleet.FleetSim._released

    def released(self, session) -> None:
        vehicle = int(session.visit.vehicle_id)
        hours = max(self.env.now - session.visit.arrive_min, 0.0) / 60.0
        used = min(float(self.always_on_kw[vehicle]) * hours, session.soc * float(self.capacity[vehicle]))
        session.soc -= used / float(self.capacity[vehicle])
        self.energy_kwh += used
        hand_back(self, session)

    setattr(fleet.FleetSim, "_released", released)  # noqa: B010
    setattr(fleet.FleetSim, "_parked_load_counted", True)  # noqa: B010


def _row(runs: list[dict], size: int, usable_kwh_a_day: float) -> dict:
    """One fleet's forty runs: rides, low-battery arrivals over all runs and in the worst fortnight, and the feeder."""
    from depot_twin import cadence

    mine = [r for r in runs if r["size"] == size]
    by_window = {window: [r for r in mine if r["window"] == window] for window in sorted({r["window"] for r in mine})}
    low = {
        window: float(np.median([r["arrived_at_floor_share"] for r in group])) for window, group in by_window.items()
    }
    at_floor = {
        window: float(np.mean([r["served"] >= cadence.E23_FLOOR for r in group])) for window, group in by_window.items()
    }
    share = float(np.median([r["grid_share_used"] for r in mine]))
    return {
        "runs": len(mine),
        "served_median": round(float(np.median([r["served"] for r in mine])), 4),
        "served_lowest_run": round(min(r["served"] for r in mine), 4),
        "runs_at_floor": round(float(np.mean([r["served"] >= cadence.E23_FLOOR for r in mine])), 3),
        "arrived_at_floor_share": round(float(np.median([r["arrived_at_floor_share"] for r in mine])), 4),
        "arrived_at_floor_share_by_fortnight": {window: round(value, 4) for window, value in low.items()},
        "arrived_at_floor_share_worst_fortnight": round(max(low.values()), 4),
        "grid_share_used": round(share, 4),
        "grid_at_limit_share": round(float(np.median([r["grid_at_limit_share"] for r in mine])), 4),
        "feeder_kwh_per_vehicle_day": round(share * usable_kwh_a_day / size, 1),
        "runs_settled": round(float(np.mean([r["settled"] for r in mine])), 3),
        "carried_by_fortnight": {
            window: at_floor[window] >= cadence.E23_CONFIDENCE and low[window] <= cadence.E23_RULE_IN_CHARGE
            for window in by_window
        },
    }


def _carried(rows: dict[str, dict], sizes: tuple[int, ...], every_fortnight: bool) -> int | None:
    """The largest fleet carried with every smaller fleet run carried too: over all runs, or in each fortnight alone."""
    from depot_twin import cadence

    best = None
    for size in sizes:
        row = rows[str(size)]
        whole = (
            row["runs_at_floor"] >= cadence.E23_CONFIDENCE
            and row["arrived_at_floor_share"] <= cadence.E23_RULE_IN_CHARGE
        )
        if not (all(row["carried_by_fortnight"].values()) if every_fortnight else whole):
            break
        best = size
    return best


def e27_parked(workers: int = 4) -> Path:
    """E27: the capacity test with the always-on load counted while a vehicle is in the depot."""
    from depot_twin import cadence, provenance
    from depot_twin.evals import margin

    started_on = provenance.stamp("e27_parked.json")
    derived = data_dir() / "derived"
    record = json.loads((derived / "e23_capacity.json").read_text())
    without = json.loads((derived / "e26_margin.json").read_text())
    chosen, best = record["setting"], record["best_rule"]
    for window in cadence.E23_WINDOWS:
        replay_curves(window)
    fleet, depot = cadence._fleet_and_depot(600, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    jobs = [
        (
            f"parked_{energy:g}",
            best,
            "slot_power",
            size,
            window,
            seed,
            chosen,
            {"models": margin._models(fleet, energy)},
        )
        for energy in E27_ENERGY
        for size in E27_SIZES[energy]
        for window in cadence.E23_WINDOWS
        for seed in cadence.E23_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers, initializer=_count_parked_load) as pool:
        runs = list(pool.map(cadence.capacity_run, jobs, chunksize=4))
    usable_kwh_a_day = depot.usable_kw * 24.0
    by_energy = {}
    for energy in E27_ENERGY:
        mine = [r for r in runs if r["label"] == f"parked_{energy:g}"]
        rows = {str(size): _row(mine, size, usable_kwh_a_day) for size in E27_SIZES[energy]}
        by_energy[f"{energy:g}"] = {
            "by_size": rows,
            "carried": _carried(rows, E27_SIZES[energy], every_fortnight=False),
            "carried_in_every_fortnight": _carried(rows, E27_SIZES[energy], every_fortnight=True),
            "carried_without_the_parked_load": without["carried"][f"{energy:g}"],
        }
    at_estimate, above = by_energy["1"], by_energy["1.1"]
    # What the parked load adds to a vehicle's day at the fleets run both ways.
    added = {
        energy: {
            size: round(
                group["by_size"][size]["feeder_kwh_per_vehicle_day"]
                - without["by_energy"][energy]["by_size"][size]["feeder_kwh_per_vehicle_day"],
                1,
            )
            for size in group["by_size"]
            if size in without["by_energy"][energy]["by_size"]
        }
        for energy, group in by_energy.items()
    }
    bars = {
        "1_600_vehicles_are_carried_in_every_fortnight_at_the_estimate_with_the_parked_load": (
            at_estimate["carried_in_every_fortnight"] or 0
        )
        >= 600,
        "2_the_parked_load_takes_at_most_50_vehicles_off_the_carried_fleet_at_the_estimate": (
            at_estimate["carried"] or 0
        )
        >= at_estimate["carried_without_the_parked_load"] - E27_MOST_LOST,
        "3_550_vehicles_are_carried_in_every_fortnight_with_the_parked_load_and_10pct_more_energy_use": (
            above["carried_in_every_fortnight"] or 0
        )
        >= 550,
    }
    if provenance.stamp("e27_parked.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E27 ran: its runs cannot be stamped")
    return _write(
        "e27_parked.json",
        {
            "eval": "E27",
            "rule": best,
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(cadence.E23_SEEDS),
            "sizes": {f"{energy:g}": list(sizes) for energy, sizes in E27_SIZES.items()},
            "usable_kwh_a_day": round(usable_kwh_a_day, 0),
            "by_energy": by_energy,
            "feeder_kwh_per_vehicle_day_added_by_the_parked_load": added,
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
