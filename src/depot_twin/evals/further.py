"""How far the plan of 600 holds: more energy than E26 tried, a busier fleet, a sharper peak, and other cadence settings.

E26 and E27 moved the energy estimate by 10% and counted the parked load. Four things they left alone
could each move what one feeder carries. E28 moves them, one at a time, around the fleets E26 carried:

- energy on the road 20% and 30% above the estimate, to see whether the carried fleet keeps following the
  arithmetic further out than 10%;
- 10% and 20% more rides a vehicle a day;
- the busiest fifth of the week's hours made 10% and 20% busier at the same weekly total, since the ride
  records count rides served and a real peak may have been higher than the one recorded;
- every call-in level and cleaning interval that matches the filed visit pattern as well as the one E22
  chose, since two settings were fitted to one pair of counts.

The runs are `cadence.capacity_run`, the capacity test's own, on its four fortnights with three of its ten
seeds: the draws of a fortnight are near copies and the fortnights are the sample. A control arm runs the
estimate on the same seeds. The simulator's code is not changed; the sharper peak replaces the demand
curve in the test's own processes.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from functools import partial
from pathlib import Path

import numpy as np

from depot_twin.data import data_dir
from depot_twin.evals.common import _write, replay_curves

E28_PLAN = 600
E28_STEP = 25
E28_ENERGY = {1.2: (525, 550, 575, 600), 1.3: (475, 500, 525, 550)}
E28_RIDES = {1.1: (575, 600, 625, 650), 1.2: (525, 550, 575, 600)}  # rides a vehicle a day, against the estimate
E28_PEAK = {1.1: (600, 650, 675, 700), 1.2: (600, 650, 675, 700)}
E28_CONTROL = (600, 650, 675, 700)
E28_BUSIEST_SHARE = 0.2  # the share of the week's hours that count as its peak
E28_CALL_BELOW = (0.45, 0.50, 0.55, 0.60, 0.65)
E28_CLEAN_EVERY = (3, 4, 5, 6)
E28_CADENCE_SIZES = (600, 650, 675)
STEPS_AN_HOUR = 12


def sharper(counts: np.ndarray, factor: float, share: float = E28_BUSIEST_SHARE) -> np.ndarray:
    """A fortnight's counts with the busiest hours of its week raised by `factor` and the total unchanged.

    An hour of the week is busy by its mean over the fortnight's two weeks, so the same hours are raised in
    both, and every step of a raised hour is raised alike.
    """
    counts = np.asarray(counts, dtype=float)
    hours = counts.reshape(2, 168, STEPS_AN_HOUR)
    by_hour = hours.sum(axis=(0, 2))
    busiest = by_hour >= np.quantile(by_hour, 1.0 - share)
    raised = hours * np.where(busiest, factor, 1.0)[None, :, None]
    return (raised * counts.sum() / raised.sum()).reshape(counts.shape)


def _sharpen_demand(factor: float) -> None:
    """In this process, hand every capacity run the fortnight's demand with its peak hours raised."""
    from depot_twin import evals

    def curves(start: str) -> dict:
        got = dict(replay_curves(start))
        got["counts"] = sharper(got["counts"], factor)
        return got

    setattr(evals, "replay_curves", curves)  # noqa: B010


def _pool(jobs: list[tuple], workers: int, initializer=None) -> list[dict]:
    from depot_twin import cadence

    with ProcessPoolExecutor(max_workers=workers, initializer=initializer) as pool:
        runs = list(pool.map(cadence.capacity_run, jobs, chunksize=2))
    return [{key: value for key, value in run.items() if key != "per_day"} for run in runs]


def _arm(runs: list[dict], sizes: tuple[int, ...], usable_kwh_a_day: float) -> dict:
    """One arm's fleets: each fleet's runs, the fleet carried over all runs, and the one carried in every fortnight."""
    from depot_twin.evals import parked

    rows = {str(size): parked._row(runs, size, usable_kwh_a_day) for size in sizes}
    return {
        "by_size": rows,
        "carried": parked._carried(rows, sizes, every_fortnight=False),
        "carried_in_every_fortnight": parked._carried(rows, sizes, every_fortnight=True),
        "plan_carried_in_every_fortnight": all(rows[str(E28_PLAN)]["carried_by_fortnight"].values())
        if str(E28_PLAN) in rows
        else None,
    }


def cadence_matches(workers: int) -> list[dict]:
    """Every call-in level and cleaning interval tried at 500 vehicles, with the cadence it gives and whether it matches the filings."""
    from depot_twin import cadence

    jobs = [
        (5, clean_every, call_below, "rule", seed)
        for clean_every in E28_CLEAN_EVERY
        for call_below in E28_CALL_BELOW
        for seed in cadence.E22_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(cadence.cadence_run, jobs, chunksize=2))
    out = []
    for clean_every in E28_CLEAN_EVERY:
        for call_below in E28_CALL_BELOW:
            mine = [r for r in runs if r["clean_every"] == clean_every and r["call_below"] == call_below]
            row = {
                "clean_every": clean_every,
                "call_below": call_below,
                "trips_per_visit": round(float(np.mean([r["trips_per_visit"] for r in mine])), 2),
                "visits_per_charger_day": round(float(np.mean([r["visits_per_charger_day"] for r in mine])), 2),
                "served": round(float(np.mean([r["served"] for r in mine])), 4),
            }
            out.append(row | {"matches_the_filings": cadence._matches(row)})
    return out


def _bars(control: dict, energy: dict, rides: dict, peak: dict, by_setting: dict) -> dict:
    """The five bars, read from the arms."""
    twenty = energy["1.2"]
    return {
        "1_with_20pct_more_energy_the_carried_fleet_is_within_one_step_of_the_arithmetic": twenty["carried"] is not None
        and abs(twenty["carried"] - twenty["by_arithmetic"]) <= E28_STEP,
        "2_with_10pct_more_rides_a_vehicle_600_are_carried_in_every_fortnight": bool(
            rides["1.1"]["plan_carried_in_every_fortnight"]
        ),
        "3_with_the_peak_hours_20pct_busier_600_are_carried_in_every_fortnight": bool(
            peak["1.2"]["plan_carried_in_every_fortnight"]
        ),
        "4_with_the_peak_hours_20pct_busier_the_carried_fleet_is_within_one_step_of_the_control": peak["1.2"]["carried"]
        is not None
        and control["carried"] is not None
        and abs(peak["1.2"]["carried"] - control["carried"]) <= E28_STEP,
        "5_under_every_cadence_setting_that_matches_the_filings_600_are_carried_in_every_fortnight": bool(by_setting)
        and all(row["plan_carried_in_every_fortnight"] for row in by_setting.values()),
    }


def e28_further(workers: int = 5) -> Path:
    """E28: what one feeder carries further from the estimate than E26 and E27 went."""
    from depot_twin import cadence, provenance
    from depot_twin.evals import margin

    started_on = provenance.stamp("e28_further.json")
    derived = data_dir() / "derived"
    record = json.loads((derived / "e23_capacity.json").read_text())
    published = json.loads((derived / "e26_margin.json").read_text())["carried"]
    chosen, best = record["setting"], record["best_rule"]
    seeds, windows = cadence.E23_FEW_SEEDS, cadence.E23_WINDOWS
    fleet, depot = cadence._fleet_and_depot(E28_PLAN, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    usable_kwh_a_day = depot.usable_kw * 24.0

    def jobs(label: str, sizes: tuple[int, ...], setting: dict, moved: dict) -> list[tuple]:
        return [
            (label, best, "slot_power", size, w, seed, setting, moved)
            for size in sizes
            for w in windows
            for seed in seeds
        ]

    plain = jobs("control", E28_CONTROL, chosen, {})
    for energy, sizes in E28_ENERGY.items():
        plain += jobs(f"energy_{energy:g}", sizes, chosen, {"models": margin._models(fleet, energy)})
    for more, sizes in E28_RIDES.items():
        plain += jobs(f"rides_{more:g}", sizes, chosen, {"rides_per_vehicle_day": fleet.rides_per_vehicle_day * more})
    settings = cadence_matches(workers)
    for row in settings:
        if row["matches_the_filings"]:
            setting = chosen | {"clean_every": row["clean_every"], "call_below": row["call_below"]}
            plain += jobs(f"cadence_{row['clean_every']}_{row['call_below']:g}", E28_CADENCE_SIZES, setting, {})
    runs = _pool(plain, workers)
    for factor, sizes in E28_PEAK.items():
        runs += _pool(jobs(f"peak_{factor:g}", sizes, chosen, {}), workers, partial(_sharpen_demand, factor))

    def arm(label: str, sizes: tuple[int, ...]) -> dict:
        return _arm([r for r in runs if r["label"] == label], sizes, usable_kwh_a_day)

    control = arm("control", E28_CONTROL)
    energy = {
        f"{e:g}": arm(f"energy_{e:g}", sizes) | {"by_arithmetic": round(published["1"] / e, 1)}
        for e, sizes in E28_ENERGY.items()
    }
    rides = {
        f"{m:g}": arm(f"rides_{m:g}", sizes) | {"rides_per_vehicle_day": fleet.rides_per_vehicle_day * m}
        for m, sizes in E28_RIDES.items()
    }
    peak = {f"{f:g}": arm(f"peak_{f:g}", sizes) for f, sizes in E28_PEAK.items()}
    by_setting = {
        f"{row['clean_every']}_{row['call_below']:g}": row
        | arm(f"cadence_{row['clean_every']}_{row['call_below']:g}", E28_CADENCE_SIZES)
        for row in settings
        if row["matches_the_filings"]
    }
    bars = _bars(control, energy, rides, peak, by_setting)
    if provenance.stamp("e28_further.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E28 ran: its runs cannot be stamped")
    return _write(
        "e28_further.json",
        {
            "eval": "E28",
            "rule": best,
            "windows": list(windows),
            "seeds": list(seeds),
            "usable_kwh_a_day": round(usable_kwh_a_day, 0),
            "carried_at_the_estimate_over_forty_runs": published["1"],
            "control": control,
            "energy": energy,
            "rides": rides,
            "peak": peak | {"busiest_share_of_hours": E28_BUSIEST_SHARE},
            "cadence_settings_tried": settings,
            "cadence": by_setting,
            "runs": runs,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
