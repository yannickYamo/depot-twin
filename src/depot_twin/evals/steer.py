"""What the plan's cheaper energy costs in margin.

In the capacity test the plan serves its rides at 600 vehicles and is not counted as carrying them: half
its depot visits start at the low-battery level, and its fleet rides at under a third of a charge where
the threshold's rides at two thirds. One setting is the likely cause. Through the tariff's evening peak
the plan calls a vehicle in only below 15% charge, three points above the level at which a vehicle is
called in whatever the plan says. E29 raises that level and reads both sides of the trade: the visits that
start low, and the price paid for energy. It also runs the plan with a 12-hour and a 36-hour view, which
no test has varied.

The runs are `cadence.capacity_run` under the plan, on the capacity test's four fortnights with three of
its ten seeds. The settings are handed to the plan in the test's own processes; the simulator's code is
not changed.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from functools import partial
from pathlib import Path

import numpy as np

from depot_twin.data import data_dir
from depot_twin.evals.common import E12_SETTINGS, _write

E29_PEAK_LEVELS = (0.15, 0.25, 0.35)  # the charge below which the plan calls a vehicle in during the tariff's peak
E29_SIZES = (500, 600, 650)
E29_HORIZONS = (12, 36)  # hours the plan looks ahead; the capacity test's plan looks 24
E29_HORIZON_SIZE = 600
E29_RESERVES = (0.5,)  # the charge the plan is asked to keep in hand across the road fleet; 0.3 as tested
E29_RESERVE_SIZES = (500, 600)
E29_KEEPS = 0.5  # the share of the energy saving a higher level must keep
E29_SAME_RIDES = 0.001
E29_SAME_LOW = 0.05


def _settings(peak_call_below: float, horizon: int | None, reserve_soc: float | None = None) -> None:
    """In this process, give the capacity test's plan another peak level and, when asked, another horizon or reserve."""
    from depot_twin import evals

    moved = E12_SETTINGS | {"peak_call_below": peak_call_below} | ({} if horizon is None else {"horizon": horizon})
    moved |= {} if reserve_soc is None else {"reserve_soc": reserve_soc}
    setattr(evals, "E12_SETTINGS", moved)  # noqa: B010


def _pool(jobs: list[tuple], workers: int, initializer) -> list[dict]:
    from depot_twin import cadence

    with ProcessPoolExecutor(max_workers=workers, initializer=initializer) as pool:
        runs = list(pool.map(cadence.capacity_run, jobs, chunksize=1))
    return [{key: value for key, value in run.items() if key != "per_day"} for run in runs]


def _arm(runs: list[dict], sizes: tuple[int, ...], usable_kwh_a_day: float) -> dict:
    """One setting's fleets, read as the capacity tests read them, with the charge the fleet rides at and what its energy costs."""
    from depot_twin.evals import parked

    rows = {}
    for size in sizes:
        mine = [r for r in runs if r["size"] == size]
        rows[str(size)] = parked._row(runs, size, usable_kwh_a_day) | {
            "charge_on_the_road": round(float(np.median([r["charge_on_the_road"] for r in mine])), 4),
            "cost_per_kwh": round(float(np.mean([r["cost_per_kwh"] for r in mine])), 4),
        }
    return {
        "by_size": rows,
        "carried": parked._carried(rows, sizes, every_fortnight=False),
        "carried_in_every_fortnight": parked._carried(rows, sizes, every_fortnight=True),
    }


def _bars(levels: dict, horizons: dict, threshold_cost: float) -> dict:
    """The three bars, read from the arms."""
    first, raised = levels[f"{E29_PEAK_LEVELS[0]:g}"], levels[f"{E29_PEAK_LEVELS[1]:g}"]
    small = str(E29_SIZES[0])
    saving = lambda arm: 1.0 - arm["by_size"][small]["cost_per_kwh"] / threshold_cost  # noqa: E731
    at = str(E29_HORIZON_SIZE)
    base = first["by_size"][at]
    return {
        "1_called_in_below_25pct_at_the_peak_the_plan_carries_600_in_every_fortnight": all(
            raised["by_size"]["600"]["carried_by_fortnight"].values()
        ),
        "2_at_that_level_it_keeps_half_its_energy_saving_at_500": saving(raised) >= E29_KEEPS * saving(first),
        "3_a_12_or_36_hour_view_moves_rides_by_under_a_tenth_of_a_point_and_low_visits_by_under_5_points": all(
            abs(arm["by_size"][at]["served_median"] - base["served_median"]) < E29_SAME_RIDES
            and abs(arm["by_size"][at]["arrived_at_floor_share"] - base["arrived_at_floor_share"]) < E29_SAME_LOW
            for arm in horizons.values()
        ),
    }


def e29_steer(workers: int = 5) -> Path:
    """E29: the plan with its peak call-in level raised, and with a shorter and a longer view."""
    from depot_twin import cadence, provenance

    started_on = provenance.stamp("e29_steer.json")
    record = json.loads((data_dir() / "derived" / "e23_capacity.json").read_text())
    chosen = record["setting"]
    seeds, windows = cadence.E23_FEW_SEEDS, cadence.E23_WINDOWS
    _, depot = cadence._fleet_and_depot(E29_HORIZON_SIZE, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    usable_kwh_a_day = depot.usable_kw * 24.0

    def jobs(label: str, sizes: tuple[int, ...]) -> list[tuple]:
        return [
            (label, "plan", "slot_power", size, w, seed, chosen, {})
            for size in sizes
            for w in windows
            for seed in seeds
        ]

    runs: list[dict] = []
    for level in E29_PEAK_LEVELS:
        runs += _pool(jobs(f"peak_{level:g}", E29_SIZES), workers, partial(_settings, level, None))
    for horizon in E29_HORIZONS:
        runs += _pool(
            jobs(f"horizon_{horizon}", (E29_HORIZON_SIZE,)), workers, partial(_settings, E29_PEAK_LEVELS[0], horizon)
        )
    for reserve in E29_RESERVES:
        label, start = f"reserve_{reserve:g}", partial(_settings, E29_PEAK_LEVELS[0], None, reserve)
        runs += _pool(jobs(label, E29_RESERVE_SIZES), workers, start)
    reserves = {
        f"{reserve:g}": _arm(
            [r for r in runs if r["label"] == f"reserve_{reserve:g}"], E29_RESERVE_SIZES, usable_kwh_a_day
        )
        for reserve in E29_RESERVES
    }
    levels = {
        f"{level:g}": _arm([r for r in runs if r["label"] == f"peak_{level:g}"], E29_SIZES, usable_kwh_a_day)
        for level in E29_PEAK_LEVELS
    }
    horizons = {
        str(horizon): _arm(
            [r for r in runs if r["label"] == f"horizon_{horizon}"], (E29_HORIZON_SIZE,), usable_kwh_a_day
        )
        for horizon in E29_HORIZONS
    }
    # What the rule that waits for a free charger pays for energy at the smallest fleet, on the same fortnights and seeds.
    threshold_cost = float(
        np.mean(
            [
                r["cost_per_kwh"]
                for r in record["runs"]
                if r["label"] == "base"
                and r["rule"] == record["best_rule"]
                and r["size"] == E29_SIZES[0]
                and r["seed"] in seeds
            ]
        )
    )
    for arm in [*levels.values(), *reserves.values()]:
        arm["energy_saving_at_500"] = round(1.0 - arm["by_size"][str(E29_SIZES[0])]["cost_per_kwh"] / threshold_cost, 4)
    bars = _bars(levels, horizons, threshold_cost)
    if provenance.stamp("e29_steer.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E29 ran: its runs cannot be stamped")
    return _write(
        "e29_steer.json",
        {
            "eval": "E29",
            "windows": list(windows),
            "seeds": list(seeds),
            "plan_settings_in_the_capacity_test": E12_SETTINGS,
            "usable_kwh_a_day": round(usable_kwh_a_day, 0),
            "threshold_that_waits_cost_per_kwh_at_500": round(threshold_cost, 4),
            "by_peak_level": levels,
            "by_horizon": horizons,
            "by_reserve": reserves,
            "runs": runs,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
