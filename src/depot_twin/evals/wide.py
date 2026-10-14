"""The fleet between two steps of the capacity test, and the side studies across more seeds.

E23 measures what one feeder carries in steps of a hundred vehicles, and puts the answer between two of
them. E25 runs the fleet halfway, on the same fortnights and seeds, and asks how far the verdict leans on
where the low-battery line is drawn. The side studies (staffing, session length, the inputs moved one at a
time, and the design sweep E19) are run here across more seeds than a first look needs, so that each
figure they are quoted for comes with a spread. The runs themselves are the ones in `control`, `money` and
`cadence`; this module only chooses how many and reads them.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np

from depot_twin.data import data_dir
from depot_twin.evals.common import E8_DEV_START, E8_START, _write, replay_curves

SIDE_SEEDS = tuple(range(31, 41))
FEW_SIDE_SEEDS = SIDE_SEEDS[:5]
E19_WIDE_SEEDS = (1901, 1902, 1903, 1904, 1905)
E25_SIZE = 650
E25_LINES = (0.25, 0.5, 0.75)  # where the low-battery line could be drawn


def _spread(values: list[float], places: int = 4) -> dict:
    array = np.asarray(values, dtype=float)
    return {
        "median": round(float(np.median(array)), places),
        "p10": round(float(np.quantile(array, 0.1)), places),
        "p90": round(float(np.quantile(array, 0.9)), places),
        "runs": len(array),
    }


def _pool(run, jobs: list, workers: int) -> list[dict]:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, jobs, chunksize=2))


def _verdict(runs: list[dict], floor: float, confidence: float, line: float) -> bool:
    """Whether one fleet's runs serve the floor often enough with the calling rule still in charge."""
    at_floor = float(np.mean([r["served"] >= floor for r in runs]))
    return at_floor >= confidence and float(np.median([r["arrived_at_floor_share"] for r in runs])) <= line


def e25_between(workers: int = 5) -> Path:
    """E25: is the fleet halfway between the one E23 carried and the one it only served carried too?"""
    from depot_twin import cadence

    record = json.loads((data_dir() / "derived" / "e23_capacity.json").read_text())
    chosen, best = record["setting"], record["best_rule"]
    for window in cadence.E23_WINDOWS:
        replay_curves(window)
    jobs = [
        ("between", best, "slot_power", E25_SIZE, window, seed, chosen, {})
        for window in cadence.E23_WINDOWS
        for seed in cadence.E23_SEEDS
    ]
    runs = _pool(cadence.capacity_run, jobs, workers)
    whole = cadence.carried(runs, (E25_SIZE,))
    by_window = {
        window: cadence.carried([r for r in runs if r["window"] == window], (E25_SIZE,))["capacity"] == E25_SIZE
        for window in cadence.E23_WINDOWS
    }
    floor, confidence = record["floor"], record["confidence"]
    neighbours = {
        str(size): [r for r in record["runs"] if (r["label"], r["rule"], r["size"]) == ("base", best, size)]
        for size in (record["capacity"], record["largest_serving_the_floor"][best])
    } | {str(E25_SIZE): runs}
    lines = {
        size: {str(line): _verdict(mine, floor, confidence, line) for line in E25_LINES}
        for size, mine in sorted(neighbours.items())
    }
    low = [r["arrived_at_floor_share"] for r in runs]
    bars = {
        "1_serves_the_floor_in_nine_runs_in_ten": whole["by_size"][str(E25_SIZE)]["runs_at_floor"] >= confidence,
        "2_at_most_half_the_vehicles_arrive_on_a_low_battery_in_the_median_run": float(np.median(low))
        <= cadence.E23_RULE_IN_CHARGE,
        "3_carried_in_each_of_the_four_fortnights": all(by_window.values()),
        "4_the_verdict_is_the_same_wherever_the_low_battery_line_is_drawn": len(set(lines[str(E25_SIZE)].values()))
        == 1,
    }
    return _write(
        "e25_between.json",
        {
            "eval": "E25",
            "size": E25_SIZE,
            "rule": best,
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(cadence.E23_SEEDS),
            "rides_per_day": E25_SIZE * record["rides_per_vehicle_day"],
            "carried": whole["capacity"] == E25_SIZE,
            "by_size": whole["by_size"],
            "carried_by_fortnight": by_window,
            "low_battery_arrivals": _spread(low) | {"mean": round(float(np.mean(low)), 4)},
            "runs_under_the_line": round(float(np.mean([v <= cadence.E23_RULE_IN_CHARGE for v in low])), 3),
            "carried_by_where_the_line_is_drawn": lines,
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def staffing_study(workers: int = 5) -> Path:
    """Why does in-order feeding win? The two power rules at 1,000 vehicles, with more and more depot staff."""
    from depot_twin.evals.control import _staffing_run

    replay_curves(E8_DEV_START)
    levels, rules = (25, 50, 100, 200), ("need_first", "slot_power")
    runs = _pool(
        _staffing_run, [(staff, power, seed) for staff in levels for power in rules for seed in SIDE_SEEDS], workers
    )
    rows, gains = [], {}
    for staff in levels:
        for power in rules:
            group = [r for r in runs if (r["staff"], r["power"]) == (staff, power)]
            row = {"staff": staff, "power": power, "runs": len(group)}
            for name in ("served", "grid_kw", "charging", "between_stations", "queued"):
                row[name] = round(float(np.mean([r[name] for r in group])), 4 if name == "served" else 1)
            row["served_spread"] = _spread([r["served"] for r in group])
            rows.append(row)
        # In order less emptiest first: the runs are in seed order within each arm.
        pair = {power: [r["served"] for r in runs if (r["staff"], r["power"]) == (staff, power)] for power in rules}
        gains[str(staff)] = _spread([a - b for a, b in zip(pair["slot_power"], pair["need_first"], strict=True)])
    return _write(
        "staffing.json",
        {
            "start": E8_DEV_START,
            "size": 1000,
            "seeds": list(SIDE_SEEDS),
            "rows": rows,
            "in_order_gain": gains,
            "run": date.today().isoformat(),
        },
    )


def session_length_study(workers: int = 5) -> Path:
    """When do short charging sessions win? Slot length against depot distance and charger power."""
    from depot_twin.evals.control import _session_run

    replay_curves(E8_DEV_START)
    legs, powers, beats, sizes = (5.0, 10.0, 15.0), (60.0, 150.0), (20.0, 30.0, 45.0, 60.0), (500, 1000)
    jobs = [
        (leg, kw, beat, size, seed)
        for leg in legs
        for kw in powers
        for beat in beats
        for size in sizes
        for seed in FEW_SIDE_SEEDS
    ]
    # The run does not return its seed; the jobs are in seed order within each cell, so it is put back here.
    runs = [run | {"seed": job[-1]} for run, job in zip(_pool(_session_run, jobs, workers), jobs, strict=True)]
    rows = []
    for leg in legs:
        for kw in powers:
            for size in sizes:
                cell = {"leg_minutes": leg, "charger_kw": kw, "size": size, "runs_per_slot": len(FEW_SIDE_SEEDS)}
                mine = [r for r in runs if (r["leg_minutes"], r["charger_kw"], r["size"]) == (leg, kw, size)]
                for beat in beats:
                    group = [r for r in mine if r["beat"] == beat]
                    cell[f"served_{int(beat)}min"] = round(float(np.mean([r["served"] for r in group])), 4)
                    cell[f"kwh_{int(beat)}min"] = round(float(np.mean([r["kwh_per_session"] for r in group])), 1)
                served = {beat: cell[f"served_{int(beat)}min"] for beat in beats}
                cell["best_beat_min"] = max(served, key=lambda beat: served[beat])
                # Seed by seed: how often the slot that is best on average is also best in the run.
                best_in_run = [
                    max((r for r in mine if r["seed"] == seed), key=lambda r: r["served"])["beat"]
                    for seed in FEW_SIDE_SEEDS
                ]
                cell["runs_agreeing_on_best"] = round(
                    float(np.mean([b == cell["best_beat_min"] for b in best_in_run])), 2
                )
                ordered = sorted(served.values())
                cell["best_less_second"] = round(ordered[-1] - ordered[-2], 4)
                cell["stranded"] = sum(r["stranded"] for r in mine)
                rows.append(cell)
    return _write(
        "session_length.json",
        {"start": E8_DEV_START, "seeds": list(FEW_SIDE_SEEDS), "rows": rows, "run": date.today().isoformat()},
    )


def sensitivity_study(workers: int = 5) -> Path:
    """How far do the site's capacity figures move when an uncertain input is moved within public figures?"""
    from depot_twin.evals.control import SENSITIVITY_CASES, _sensitivity_run

    replay_curves(E8_DEV_START)
    sizes = (600, 700, 800, 1000)
    jobs = [(case, size, seed) for case in SENSITIVITY_CASES for size in sizes for seed in FEW_SIDE_SEEDS]
    runs = _pool(_sensitivity_run, jobs, workers)
    rows = []
    for case in SENSITIVITY_CASES:
        row = {"case": case, "runs_per_fleet": len(FEW_SIDE_SEEDS)}
        for size in sizes:
            group = [r["served"] for r in runs if (r["case"], r["size"]) == (case, size)]
            row[f"served_{size}"] = round(float(np.mean(group)), 4)
            row[f"served_{size}_range"] = [round(min(group), 4), round(max(group), 4)]
        mine = [r for r in runs if r["case"] == case and r["size"] == 700]
        row["kwh_per_mile"] = round(float(np.mean([r["kwh_per_mile"] for r in mine])), 3)
        row["visits_per_day"] = round(float(np.mean([r["visits_per_day"] for r in mine])), 2)
        rows.append(row)
    return _write(
        "sensitivity.json",
        {"start": E8_DEV_START, "seeds": list(FEW_SIDE_SEEDS), "rows": rows, "run": date.today().isoformat()},
    )


def e19_sweet_spot(workers: int = 5) -> Path:
    """E19: the design that earns most at the required service on the frozen fortnight, and what binds around it."""
    from depot_twin import finance
    from depot_twin.evals import money

    replay_curves(E8_START)
    money._e19_prices()
    jobs = [
        (f, fe, c, ctl, s)
        for f in money.E19_FLEETS
        for fe in money.E19_FEEDERS
        for c in money.E19_CHARGERS
        for ctl in money.E19_CONTROLS
        for s in E19_WIDE_SEEDS
    ]
    runs = _pool(money._e19_run, jobs, workers)
    rows = money._e19_rows(runs)
    for row in rows:
        group = [
            r["contribution_per_day"]
            for r in runs
            if (r["fleet"], r["feeder"], r["chargers"], r["control"])
            == (row["fleet"], row["feeder"], row["chargers"], row["control"])
        ]
        row["contribution_per_day_range"] = [round(min(group), 0), round(max(group), 0)]
        row["runs"] = len(group)
    return _write(
        "e19_sweet_spot.json",
        {
            "eval": "E19",
            "window": "sf_e8",
            "seeds": list(E19_WIDE_SEEDS),
            "assumptions": finance.Assumptions().describe(),
            "rows": rows,
            "bars": money._e19_bars(rows),
            "run": date.today().isoformat(),
        },
    )
