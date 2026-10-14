"""Plan one feeder at any site from a site file: how many vehicles it carries, with what margin, and what to change first.

The study in this repository answers that for one East Oakland parcel. This module asks the same questions
of a site described in a file: its grid connection, its vehicles and what they use, its depot, its rules,
the demand it is offered and the service it has to hold. It runs the same simulator and reads the runs the
same way, and nothing in it is specific to a place.

The answer comes in three steps. Arithmetic first: one short run measures what a vehicle takes from the
feeder in a day, and the feeder's daily energy divided by that is where the fleet has to end up. Then a
sweep of fleets around that figure, on every demand window in the file, under each way the energy estimate
could be wrong: the largest fleet carried in every window, and the fleet to plan for, which holds under
each case alone. Then one change at a time at the edge, to say what each is worth in vehicles.

A demand window is fourteen days of ride counts. Each is replayed until the fleet has settled, and its
last week is scored. Two draws a window are enough: the draws of a window are near copies of each other,
and the windows are the sample.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tomllib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

PASSES = (2, 4, 8)
SETTLED = {"arrived_at_floor_share": 0.02, "served": 0.002}  # the most each may move between passes
CONFIDENCE = 0.9  # the share of a window's runs that must serve the floor
DEFAULTS: dict[str, dict] = {
    "grid": {"services": 1, "usable_share": 0.95},
    "depot": {
        "chargers_per_vehicle": 0.132,
        "charger_kw": 60.0,
        "people_per_vehicle": 0.025,
        "plug_minutes": 2.0,
        "clean_minutes": 8.0,
        "clean_every": 4,
        "inspect_minutes": 20.0,
        "inspect_every": 10,
        "charger_efficiency": 0.93,
    },
    "fleet": {
        "rides_per_vehicle_day": 25.0,
        "ride_minutes": 23.0,
        "max_wait_minutes": 10.0,
        "depot_leg_minutes": 5.0,
        "depot_leg_miles": 1.2,
        "vehicle_spread": 0.08,
        "parked_load": "unknown",  # "off", "on" or "unknown": whether the always-on load runs in the depot
    },
    "rules": {"calling": "threshold_waits", "call_below": 0.55, "charge_to": 0.85, "power": "slot_power"},
    "policy": {"service_floor": 0.99, "low_battery_visits_at_most": 0.5, "energy_margin": 1.1},
    "sweep": {"step": 25, "draws": 2, "start": 0.9, "changes": True},
}
# What a field can plausibly be. A value outside is nearly always a slip of units, so it is refused by name.
USUAL: dict[str, dict[str, tuple[float, float, str]]] = {
    "grid": {"kw": (50.0, 50_000.0, "kW, not MW or W")},
    "depot": {"charger_kw": (3.0, 500.0, "kW, not W")},
    "fleet": {
        "rides_per_vehicle_day": (1.0, 60.0, "rides a vehicle a day, not the fleet's"),
        "ride_minutes": (5.0, 90.0, "minutes, not hours or seconds"),
    },
    "vehicle": {
        "drive_kwh_per_mile": (0.15, 0.8, "kWh a mile, not Wh a mile or kWh per 100 miles"),
        "always_on_kw": (0.0, 6.0, "kW, not W"),
        "capacity_kwh": (20.0, 250.0, "kWh, not Wh"),
        "max_dc_kw": (7.0, 500.0, "kW, not W"),
    },
}
RECORDED = ("2024-03-18", "2024-04-15", "2024-04-29", "2024-05-13")  # the fortnights committed with the study
REQUIRED = {"site": ("name",), "grid": ("kw",), "vehicles": (), "demand": ("windows",)}
OPTIONAL = ("sources",)
SOURCES = ("grid", "energy", "parked_load", "rides", "ride", "demand", "policy")
VEHICLE = (
    "share",
    "capacity_kwh",
    "max_dc_kw",
    "max_ac_kw",
    "taper_start_soc",
    "taper_floor",
    "dc_curve",
    "drive_kwh_per_mile",
    "always_on_kw",
)


class SiteError(ValueError):
    """A site file that cannot be planned, with the field and what is wrong with it."""


def _read(path: Path) -> dict:
    """The site file as TOML tables, refused when it is not there, is not TOML, or holds a value where a table goes."""
    if not path.is_file():
        raise SiteError(f"no site file at {path}")
    try:
        site = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as fault:
        raise SiteError(f"{path}: not valid TOML: {fault}") from fault
    stray = [f"[{table}] must be a table" for table, value in site.items() if not isinstance(value, dict)]
    if stray:
        raise SiteError(f"{path}: " + "; ".join(stray))
    return site


def _names(site: dict) -> tuple[list[str], list[str]]:
    """What a site file lacks, and every table and field in it that the planner does not know."""
    lacking = []
    for table, fields in REQUIRED.items():
        if table not in site:
            lacking.append(f"[{table}] is missing")
            continue
        lacking += [f"[{table}] has no {field}" for field in fields if field not in site[table]]
    known = set(REQUIRED) | set(DEFAULTS) | set(OPTIONAL)
    unknown = [
        f"[{table}] is not a table the planner knows ({', '.join(sorted(known))})"
        for table in sorted(set(site) - known)
    ]
    fields = {table: set(defaults) | set(REQUIRED.get(table, ())) for table, defaults in DEFAULTS.items()}
    fields |= {"site": {"name"}, "demand": {"windows"}, "sources": set(SOURCES)}
    fields |= {
        f"vehicles.{name}": set(VEHICLE) for name, spec in site.get("vehicles", {}).items() if isinstance(spec, dict)
    }
    for table, allowed in fields.items():
        given = site.get("vehicles", {}).get(table[9:], {}) if table.startswith("vehicles.") else site.get(table, {})
        unknown += [f"[{table}] has an unknown field {name!r}" for name in sorted(set(given) - allowed)]
    return lacking, unknown


def load(path: str | Path, allow_unusual: bool = False) -> dict:
    """Read a site file, fill in the defaults and check it, naming every problem found.

    A file that is not there, is not TOML, or lacks a required table or field is refused at once, and so
    is a value of the wrong kind. After that every other problem is reported together: unknown tables and
    fields, values out of range, and demand windows that cannot be replayed (the first fault of each file).
    A value outside its usual range is refused, unless `allow_unusual` is set: then it is kept, and listed
    under `_unusual` so the brief can say so.
    """
    path = Path(path)
    site = _read(path)
    lacking, problems = _names(site)
    for table, defaults in DEFAULTS.items():
        site[table] = {**defaults, **site.get(table, {})}
    site["_folder"] = str(path.parent)
    stop = lacking or _wrong_kind(site)
    if stop:
        raise SiteError(f"{path}: " + "; ".join(lacking + problems + (stop if not lacking else [])))
    problems += _out_of_range(site) + _windows(site)
    site["_unusual"] = _unusual(site)
    if not allow_unusual:
        problems += [f"{slip}; pass --allow-unusual if it is meant" for slip in site["_unusual"]]
    if problems:
        raise SiteError(f"{path}: " + "; ".join(problems))
    return site


NUMBERS = {
    "grid": ("kw", "services", "usable_share"),
    "depot": tuple(k for k, v in DEFAULTS["depot"].items() if isinstance(v, int | float)),
    "fleet": tuple(k for k, v in DEFAULTS["fleet"].items() if isinstance(v, int | float)),
    "rules": ("call_below", "charge_to"),
    "policy": tuple(DEFAULTS["policy"]),
    "sweep": ("step", "draws", "start"),
}


def _wrong_kind(site: dict) -> list[str]:
    """Every value that is not the kind of thing its field holds: a number, a list of windows, a table of vehicle types."""
    # A number, and a finite one: TOML has nan and inf, and no fleet passes a test against either.
    number = lambda v: isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)  # noqa: E731
    found = [
        f"[{table}] {field} must be a number, not {site[table][field]!r}"
        for table, fields in NUMBERS.items()
        for field in fields
        if field in site[table] and not number(site[table][field])
    ]
    windows = site["demand"].get("windows")
    if not isinstance(windows, list) or not all(isinstance(w, str) for w in windows):
        found.append('[demand] windows must be a list of dates or files, such as ["2024-03-18"]')
    for name, spec in site["vehicles"].items():
        if not isinstance(spec, dict):
            found.append(f"[vehicles.{name}] must be a table")
            continue
        found += [
            f"[vehicles.{name}] {field} must be a number, not {value!r}"
            for field, value in spec.items()
            if field in VEHICLE and field != "dc_curve" and not number(value)
        ]
    return found


def _unusual(site: dict) -> list[str]:
    """Every value outside its usual range, with the field and the likely slip of units."""
    found = []
    tables = [(f"[{t}]", site[t], USUAL[t]) for t in ("grid", "depot", "fleet")]
    tables += [(f"[vehicles.{name}]", spec, USUAL["vehicle"]) for name, spec in site["vehicles"].items()]
    for label, values, usual in tables:
        for field, (low, high, unit) in usual.items():
            value = values.get(field)
            if isinstance(value, int | float) and not low <= value <= high:
                found.append(f"{label} {field} = {value:g} is outside {low:g} to {high:g}: it is in {unit}")
    for name, spec in site["vehicles"].items():
        curve = [tuple(point) for point in spec.get("dc_curve", ())]
        charge = [point[0] for point in curve]
        if curve and (charge != sorted(set(charge)) or charge[0] < 0 or charge[-1] > 1 or min(p[1] for p in curve) < 0):
            found.append(f"[vehicles.{name}] dc_curve must rise in charge from 0 to 1, with no power below zero")
    return found


def _windows(site: dict) -> list[str]:
    """Every demand window that is neither a recorded fortnight nor a file of counts that can be replayed."""
    problems = []
    for window in site["demand"].get("windows", ()):
        if str(window).endswith(".csv"):
            file = (Path(site["_folder"]) / window).resolve()
            if not file.exists():
                problems.append(f"[demand] window {window!r}: no file at {file}")
                continue
            try:
                _counts(file)
            except SiteError as fault:
                problems.append(f"[demand] window {fault}")
        elif window not in RECORDED:
            problems.append(
                f"[demand] window {window!r} is not a recorded fortnight ({', '.join(RECORDED)}) or a .csv file"
            )
    return problems


def _counts(file: Path):
    """A file of counts as a series, refused with its line number where the times do not run evenly from a Monday."""
    import pandas as pd

    try:
        frame = pd.read_csv(file)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError, OSError) as fault:
        raise SiteError(f"{file.name}: cannot be read as a CSV ({fault})") from fault
    missing = [column for column in ("time", "rides") if column not in frame.columns]
    if missing:
        raise SiteError(f"{file.name}, line 1: no {' or '.join(missing)} column; the header is time,rides")
    if len(frame) < 2:
        raise SiteError(f"{file.name}: a window is fourteen days of counts, and this file has {len(frame)} row(s)")
    times = pd.to_datetime(frame["time"], errors="coerce")
    rides = pd.to_numeric(frame["rides"], errors="coerce")
    for column, bad, what in (
        ("time", times.isna(), "is not a time"),
        ("rides", rides.isna(), "is not a count"),
        ("rides", rides < 0, "is below zero"),
    ):
        if bad.any():
            row = int(bad.idxmax())
            raise SiteError(f"{file.name}, line {row + 2}: {column} {str(frame[column][row])!r} {what}")
    step = times.diff().dt.total_seconds().div(60.0)
    if step.iloc[1] not in (5.0, 60.0):
        raise SiteError(f"{file.name}: counts must be five minutes or one hour apart, not {step.iloc[1]:g} minutes")
    uneven = step.iloc[1:][step.iloc[1:] != step.iloc[1]]
    if len(uneven):
        row = int(uneven.index[0])
        raise SiteError(
            f"{file.name}, line {row + 2}: {times[row]} follows {times[row - 1]}, and every row must be "
            f"{step.iloc[1]:g} minutes after the one before, with no gap, repeat or clock change"
        )
    if times[0].weekday() != 0 or times[0] != times[0].normalize():
        raise SiteError(f"{file.name}, line 2: a window starts on a Monday at 00:00, and this one starts {times[0]}")
    days = len(frame) * step.iloc[1] / 1440.0
    if days != 14:
        raise SiteError(f"{file.name}: a window is fourteen days of counts, and this file holds {days:g}")
    return pd.Series(rides.to_numpy(dtype=float), index=pd.DatetimeIndex(times, name="time"), name="rides")


def _out_of_range(site: dict) -> list[str]:
    grid, fleet, policy, vehicles = site["grid"], site["fleet"], site["policy"], site["vehicles"]
    checks = [
        (grid["kw"] > 0, "[grid] kw must be above zero"),
        (0.5 <= grid["usable_share"] <= 1.0, "[grid] usable_share must be between 0.5 and 1"),
        (grid["services"] >= 1, "[grid] services must be at least 1"),
        (bool(vehicles), "[vehicles] needs at least one vehicle type"),
        (
            abs(sum(v.get("share", 0.0) for v in vehicles.values()) - 1.0) < 1e-6,
            f"[vehicles] shares must add to 1, and they add to {sum(v.get('share', 0.0) for v in vehicles.values()):g}",
        ),
        *(
            (
                v.get(field, 0) > 0 if field != "always_on_kw" else field in v,
                f"[vehicles.{name}] needs {field}",
            )
            for name, v in vehicles.items()
            for field in ("capacity_kwh", "drive_kwh_per_mile", "always_on_kw", "max_dc_kw", "max_ac_kw")
        ),
        (site["sweep"]["step"] >= 1, "[sweep] step must be at least 1"),
        (site["sweep"]["draws"] >= 1, "[sweep] draws must be at least 1"),
        (fleet["rides_per_vehicle_day"] > 0, "[fleet] rides_per_vehicle_day must be above zero"),
        (fleet["parked_load"] in ("off", "on", "unknown"), '[fleet] parked_load must be "off", "on" or "unknown"'),
        (
            0.5 < policy["service_floor"] < 1.0,
            f"[policy] service_floor = {policy['service_floor']:g} must be between 0.5 and 1 (a share, not a percentage)",
        ),
        (1.0 <= policy["energy_margin"] <= 1.5, "[policy] energy_margin must be between 1 and 1.5"),
        (
            0 < policy["low_battery_visits_at_most"] <= 1,
            "[policy] low_battery_visits_at_most must be a share between 0 and 1",
        ),
        (
            site["rules"]["calling"] in ("threshold", "threshold_waits"),
            '[rules] calling must be "threshold" or "threshold_waits"',
        ),
        (site["rules"]["power"] in ("slot_power", "need_first"), '[rules] power must be "slot_power" or "need_first"'),
        (len(site["demand"]["windows"]) >= 1, "[demand] needs at least one window"),
    ]
    return [message for ok, message in checks if not ok]


def curves(site: dict, window: str) -> dict:
    """One demand window as the simulator replays it: a recorded fortnight by its start date, or a file of counts.

    A file is a CSV with a `time` and a `rides` column, fourteen days at five minutes or at one hour; an
    hour's rides are spread evenly over its twelve steps. Its times start on a Monday at 00:00 and run evenly
    with no gap, repeat or clock change. Only the shape is used: the level is the fleet's rides a vehicle a day.
    """
    import pandas as pd

    from depot_twin import replay
    from depot_twin.evals.common import replay_curves

    if not window.endswith(".csv"):
        return replay_curves(window)
    frame = _counts(Path(site["_folder"]) / window)
    if frame.index[1] - frame.index[0] == pd.Timedelta(hours=1):
        index = pd.date_range(frame.index[0], periods=len(frame) * 12, freq="5min")
        frame = pd.Series(np.repeat(frame.to_numpy() / 12.0, 12), index=index)
    return replay.plain_curves(frame)


def build(site: dict, size: int, energy: float = 1.0, change: dict | None = None):
    """The fleet and depot of a site at one fleet size, with energy use scaled and one thing changed."""
    from depot_twin.fleet import FleetConfig
    from depot_twin.resources import ChargerBank, DepotConfig, VehicleModel

    change = change or {}
    grid, depot, fleet = site["grid"], site["depot"], site["fleet"]
    models, mix = [], []
    for name, spec in site["vehicles"].items():
        spec = dict(spec)
        mix.append(spec.pop("share"))
        curve = tuple(tuple(point) for point in spec.pop("dc_curve", ()))
        model = VehicleModel(name=name, dc_curve=curve, **spec)
        models.append(
            replace(
                model, drive_kwh_per_mile=model.drive_kwh_per_mile * energy, always_on_kw=model.always_on_kw * energy
            )
        )
    people = max(4, int(size * depot["people_per_vehicle"] * change.get("people", 1.0)))
    chargers = int(np.ceil(size * depot["chargers_per_vehicle"] * change.get("chargers", 1.0)))
    return (
        FleetConfig(
            size=size,
            models=tuple(models),
            mix=tuple(mix),
            step_min=5.0,
            **{
                k: fleet[k]
                for k in (
                    "rides_per_vehicle_day",
                    "ride_minutes",
                    "max_wait_minutes",
                    "depot_leg_minutes",
                    "depot_leg_miles",
                    "vehicle_spread",
                )
            },
        ),
        DepotConfig(
            name=site["site"]["name"],
            site_limit_kw=grid["kw"] * grid["services"] * change.get("grid", 1.0),
            chargers=(ChargerBank("dc", chargers, depot["charger_kw"]),),
            staff=people,
            cleaning_bays=people,
            usable_share=grid["usable_share"],
            **{
                k: depot[k]
                for k in (
                    "plug_minutes",
                    "clean_minutes",
                    "clean_every",
                    "inspect_minutes",
                    "inspect_every",
                    "charger_efficiency",
                )
            },
        ),
    )


def _once(site: dict, size: int, window: str, seed: int, energy: float, change: dict, passes: int) -> dict:
    from depot_twin import cadence
    from depot_twin.data import data_dir
    from depot_twin.dispatch import HARD_FLOOR_SOC
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape, served_share

    fleet, depot = build(site, size, energy, change)
    rules = {**site["rules"], **change.get("rules", {})}
    demand = cadence._replayed(curves(site, window), size, fleet.rides_per_vehicle_day, passes)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")  # unused under replayed demand
    rule = ThresholdRecall(
        rules["call_below"], rules["charge_to"], wait_for_charger=rules["calling"] == "threshold_waits"
    )
    total = E8_DAYS * passes
    skip = total - (E8_DAYS - E8_WARMUP_DAYS)
    result = FleetSim(fleet, depot, shape, rule, depot_policy=rules["power"], seed=seed, demand=demand).run(total)
    measured = cadence._measure(result, rule, depot, size, total, skip)
    series = result.depot.series[result.depot.series[:, 0] >= skip * 1440.0]
    earlier = [
        s.visit.soc_in <= HARD_FLOOR_SOC
        for s in result.depot.sessions
        if (skip - E8_DAYS) * 1440.0 <= s.visit.arrive_min < (total - E8_DAYS) * 1440.0
    ]
    clock = result.steps[:, 0]
    before = result.steps[(clock >= (skip - E8_DAYS) * 1440.0) & (clock < (total - E8_DAYS) * 1440.0)]
    share = float(series[:, 1].mean()) / depot.usable_kw
    return {
        "size": size,
        "window": window,
        "seed": seed,
        "passes": passes,
        "served": round(float(measured["served"]), 5),
        "arrived_at_floor_share": round(float(measured["arrived_at_floor_share"]), 5),
        "arrived_at_floor_share_a_pass_earlier": round(float(np.mean(earlier)) if earlier else 0.0, 5),
        "served_a_pass_earlier": round(float(served_share(before)) if len(before) else 0.0, 5),
        "waiting_for_a_charger_share": round(float(measured["waiting_share"]), 4),
        "grid_share_used": round(share, 4),
        "grid_at_limit_share": round(float((series[:, 1] >= 0.98 * depot.usable_kw).mean()), 4),
        "feeder_kwh_per_vehicle_day": round(share * depot.usable_kw * 24.0 / size, 1),
    }


def run(job: tuple) -> dict:
    """One fleet on one window, replayed until its scored week has settled. `job` is (site, case, size, window, seed, energy, change).

    A run that is far from carried after the first replays is not replayed further: how far past the
    edge it sits does not change the verdict.
    """
    site, case, size, window, seed, energy, change = job
    policy = site["policy"]
    out: dict = {}
    for passes in PASSES:
        out = _once(site, size, window, seed, energy, change, passes)
        out["settled"] = all(abs(out[key] - out[f"{key}_a_pass_earlier"]) <= most for key, most in SETTLED.items())
        lost = out["served"] < policy["service_floor"] - 0.02 or out["arrived_at_floor_share"] >= 0.9
        if out["settled"] or lost:
            break
    return out | {"case": case}


def _count_parked_load() -> None:
    from depot_twin.evals.parked import _count_parked_load as count

    count()


def verdict(runs: list[dict], sizes: list[int], policy: dict) -> dict:
    """By fleet: rides, low-battery visits and the feeder, window by window; and the largest fleet carried in every window.

    A fleet is carried in a window when nine of its runs in ten serve the floor and no more than the
    allowed share of depot visits start on a low battery in the median run, and every run has settled:
    a run still moving after its last replay decides nothing. The fleet carried is the
    largest for which that holds in every window, with every smaller fleet run holding too.
    """
    rows, carried = {}, None
    still = True
    for size in sorted(sizes):
        mine = [r for r in runs if r["size"] == size]
        if not mine:
            still = False
            continue
        windows = {}
        for window in sorted({r["window"] for r in mine}):
            group = [r for r in mine if r["window"] == window]
            at_floor = float(np.mean([r["served"] >= policy["service_floor"] for r in group]))
            low = float(np.median([r["arrived_at_floor_share"] for r in group]))
            windows[window] = {
                "served": round(float(np.median([r["served"] for r in group])), 4),
                "low_battery_visits": round(low, 4),
                "settled": all(r.get("settled", True) for r in group),
                "carried": at_floor >= CONFIDENCE and low <= policy["low_battery_visits_at_most"],
            }
            # A run still moving after its last replay decides nothing: its window is not carried.
            windows[window]["held_back_unsettled"] = windows[window]["carried"] and not windows[window]["settled"]
            windows[window]["carried"] = windows[window]["carried"] and windows[window]["settled"]
        middle = lambda key: round(float(np.median([r[key] for r in mine])), 4)  # noqa: E731, B023
        rows[str(size)] = {
            "served_lowest_window": min(w["served"] for w in windows.values()),
            "low_battery_visits_worst_window": max(w["low_battery_visits"] for w in windows.values()),
            "grid_share_used": middle("grid_share_used"),
            "grid_at_limit_share": middle("grid_at_limit_share"),
            "waiting_for_a_charger_share": middle("waiting_for_a_charger_share"),
            "feeder_kwh_per_vehicle_day": middle("feeder_kwh_per_vehicle_day"),
            "windows_carried": sum(w["carried"] for w in windows.values()),
            "windows": windows,
            "runs_settled": round(float(np.mean([r.get("settled", True) for r in mine])), 3),
        }
        still = still and rows[str(size)]["windows_carried"] == len(windows)
        if still:
            carried = size
    return {"by_size": rows, "carried": carried}


def _pool(jobs: list[tuple], workers: int, parked: bool = False) -> list[dict]:
    if not jobs:
        return []
    with ProcessPoolExecutor(max_workers=workers, initializer=_count_parked_load if parked else None) as pool:
        return list(pool.map(run, jobs, chunksize=2))


def search(site: dict, case: str, energy: float, parked: bool, start: float, workers: int) -> tuple[dict, list[dict]]:
    """Find the largest fleet carried in every window under one case, two fleets at a time, starting near the arithmetic.

    Upward from the start while fleets are carried, and downward from it when the start itself is not.
    The fleets run are returned with the verdict, so the answer is bracketed by a fleet that passed and
    one that did not, unless the search ran out of room.
    """
    step, policy = site["sweep"]["step"], site["policy"]
    windows, seeds = list(site["demand"]["windows"]), list(range(1, site["sweep"]["draws"] + 1))
    runs: list[dict] = []
    first = max(step, int(round(start / step)) * step)

    def carried_among(sizes: list[int]) -> dict[int, bool]:
        jobs = [(site, case, size, w, seed, energy, {}) for size in sizes for w in windows for seed in seeds]
        print(f"{case}: fleets of {' and '.join(map(str, sizes))}, {len(jobs)} runs", file=sys.stderr, flush=True)
        new = _pool(jobs, workers, parked)
        runs.extend(new)
        return {size: verdict(new, [size], policy)["carried"] == size for size in sizes}

    ok = carried_among([first, first + step])
    low, high = first, first + step
    while all(ok.values()) and high < first + 16 * step:  # upward, until a pair holds a failure
        ok |= carried_among([high + step, high + 2 * step])
        high += 2 * step
    while not ok[low] and low > step:  # downward, when the start itself was not carried
        fleets = [size for size in (low - 2 * step, low - step) if size > 0]
        ok |= carried_among(fleets)
        low = fleets[0]
    return verdict(runs, sorted(ok), policy), runs


CHANGES = (
    # (name, what it changes, fleets to try relative to the carried fleet in steps, added or taken away)
    ("a quarter more chargers", {"chargers": 1.25}, (1, 2), "add"),
    ("a quarter more people and bays", {"people": 1.25}, (1, 2), "add"),
    ("call a vehicle in whether or not a charger is free", {"rules": {"calling": "threshold"}}, (0, -2, -4), "remove"),
    ("feed the emptiest vehicle first", {"rules": {"power": "need_first"}}, (0, -2, -4), "remove"),
)


def plan(site: dict, workers: int = 5) -> dict:
    """Plan the site: the arithmetic, the sweep under each energy case, the fleet to plan for, and what each change is worth."""
    policy, sweep, fleet = site["policy"], site["sweep"], site["fleet"]
    windows, seeds = list(site["demand"]["windows"]), list(range(1, sweep["draws"] + 1))
    usable_kwh_a_day = site["grid"]["kw"] * site["grid"]["services"] * site["grid"]["usable_share"] * 24.0
    # Arithmetic: what a vehicle takes from the feeder in a day, measured on a fleet with power to spare.
    probe = int(max(50, round(0.3 * usable_kwh_a_day / 100.0 / sweep["step"]) * sweep["step"]))
    taken = float(
        np.median(
            [
                r["feeder_kwh_per_vehicle_day"]
                for r in _pool([(site, "probe", probe, w, 1, 1.0, {}) for w in windows], workers)
            ]
        )
    )
    by_arithmetic = usable_kwh_a_day / taken
    margin = policy["energy_margin"]
    cases = {"as entered": (1.0, fleet["parked_load"] == "on")}
    if margin > 1.0:
        cases[f"{margin - 1:.0%} more energy on the road"] = (margin, fleet["parked_load"] == "on")
    if fleet["parked_load"] == "unknown":
        cases["systems on while parked"] = (1.0, True)
    results, runs, fleets = {}, [], set()
    for name, (energy, parked) in cases.items():
        # A case that asks more of the feeder starts its search lower.
        start = by_arithmetic * sweep["start"] / energy * (0.95 if parked else 1.0)
        results[name], mine = search(site, name, energy, parked, start, workers)
        runs += mine
        fleets |= {r["size"] for r in mine}
    sizes = sorted(fleets)
    carried = results["as entered"]["carried"]
    holds = [r["carried"] for r in results.values()]
    planned = None if any(c is None for c in holds) else min(holds)
    skipped = None if carried and sweep["changes"] else "no fleet carried" if sweep["changes"] else "switched off"
    changes = [] if skipped else _changes(site, carried, sweep["step"], windows, seeds, workers)
    edge = results["as entered"]["by_size"].get(str((carried or sizes[0]) + sweep["step"]))
    return {
        "site": site["site"]["name"],
        "usable_kwh_a_day": round(usable_kwh_a_day, 0),
        "feeder_kwh_per_vehicle_day": round(taken, 1),
        "fleet_by_arithmetic": int(by_arithmetic),
        "fleets_run": sizes,
        "windows": windows,
        "draws_a_window": len(seeds),
        "cases": results,
        "carried": carried,
        "planned": planned,
        "planned_rides_per_day": (planned or 0) * fleet["rides_per_vehicle_day"],
        "carried_against_arithmetic": round(carried / by_arithmetic, 3) if carried else None,
        "what_binds_past_the_carried_fleet": _binds(edge) if edge else None,
        "changes": changes,
        "changes_skipped": skipped,
        "unusual_inputs": list(site.get("_unusual", ())),
        "unsettled_runs_decided_a_fleet": any(
            w["held_back_unsettled"]
            for case in results.values()
            for row in case["by_size"].values()
            for w in row["windows"].values()
        ),
        "at_the_edge_of_the_fleets_run": carried is None
        or str(carried + sweep["step"]) not in results["as entered"]["by_size"],
        "runs": len(runs) + len(windows) + sum(change["runs"] for change in changes),
        "inputs": {k: v for k, v in site.items() if not k.startswith("_")},
    }


def _binds(row: dict) -> str:
    """What stops the next fleet up, read from its runs."""
    if row["grid_at_limit_share"] >= 0.9:
        return "the feeder's energy: it is at its limit nearly all week"
    if row["waiting_for_a_charger_share"] >= 0.3:
        return "chargers: vehicles wait for one much of the week while the feeder has power to give"
    return "vehicles: the fleet runs out of charged vehicles at the peak before the feeder or the chargers fill"


def _changes(site: dict, carried: int, step: int, windows: list[str], seeds: list[int], workers: int) -> list[dict]:
    """One change at a time at the edge: the largest fleet carried with it, among the fleets tried."""
    out = []
    for name, change, offsets, kind in CHANGES:
        sizes = sorted({carried + k * step for k in offsets if carried + k * step > 0})
        print(f"{name}: fleets of {', '.join(map(str, sizes))}", file=sys.stderr, flush=True)
        mine = _pool(
            [(site, name, size, w, seed, 1.0, change) for size in sizes for w in windows for seed in seeds],
            workers,
            site["fleet"]["parked_load"] == "on",
        )
        each = {size: verdict(mine, [size], site["policy"]) for size in sizes}
        ok = [size for size in sizes if each[size]["carried"] == size]
        with_it = max(ok) if ok else None
        # A fleet that met both bars and was not counted, because one of its runs had not settled.
        unsettled = [
            size
            for size in sizes
            if size > (with_it or 0)
            and all(
                w["carried"] or w["held_back_unsettled"] for w in each[size]["by_size"][str(size)]["windows"].values()
            )
        ]
        if kind == "add":
            with_it = with_it or carried
            words = f"carries {with_it}" + (" or more" if with_it == sizes[-1] else "")
        else:
            words = f"carries {with_it}" if with_it else f"carries fewer than {sizes[0]}"
        if unsettled:
            words += f"; {max(unsettled)} met both bars with a run that had not settled"
        out.append(
            {
                "change": name,
                "kind": kind,
                "fleets_tried": sizes,
                "carried_with_it": with_it,
                "vehicles": (with_it - carried) if with_it else None,
                "met_the_bars_unsettled": unsettled,
                "runs": len(mine),
                "says": words,
            }
        )
    return sorted(out, key=lambda row: -(abs(row["vehicles"]) if row["vehicles"] is not None else 10**6))


NO_CHANGES = {
    "no fleet carried": "No fleet was carried, so no change was tried.",
    "switched off": "No change was tried: the site file switches them off ([sweep] changes = false).",
}


def brief(result: dict) -> str:
    """A one-page HTML brief of a plan: the answer, the table behind it, what to change first, and which inputs are assumed."""
    inputs, cases = result["inputs"], result["cases"]
    sources = inputs.get("sources", {})
    planned, carried = result["planned"], result["carried"]
    esc = lambda text: str(text).replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    rows = "".join(
        f"<tr><th>{esc(name)}</th><td>{case['carried'] if case['carried'] else 'none of the fleets run'}</td>"
        f"<td>{case['by_size'][str(case['carried'])]['grid_share_used']:.0%}</td>"
        f"<td>{case['by_size'][str(case['carried'])]['feeder_kwh_per_vehicle_day']:.0f} kWh</td></tr>"
        if case["carried"]
        else f"<tr><th>{esc(name)}</th><td>none of the fleets run</td><td></td><td></td></tr>"
        for name, case in cases.items()
    )
    changes = "".join(
        f"<li><b>{esc(c['change'].capitalize())}</b>: {esc(c['says'])} ({'+' if (c['vehicles'] or 0) >= 0 else ''}{c['vehicles'] if c['vehicles'] is not None else 'more than the fleets tried'} vehicles)</li>"
        for c in result["changes"]
    )
    assumed = [
        (
            "Grid connection",
            f"{inputs['grid']['kw'] * inputs['grid']['services']:,.0f} kW, {inputs['grid']['usable_share']:.0%} usable",
            "grid",
        ),
        (
            "Energy on the road",
            ", ".join(
                f"{v['drive_kwh_per_mile']} kWh a mile and {v['always_on_kw']} kW always on"
                for v in inputs["vehicles"].values()
            ),
            "energy",
        ),
        ("A parked vehicle's systems", inputs["fleet"]["parked_load"], "parked_load"),
        ("Rides a vehicle a day", f"{inputs['fleet']['rides_per_vehicle_day']:g}", "rides"),
        (
            "A ride, and a rider's patience",
            f"{inputs['fleet']['ride_minutes']:g} and {inputs['fleet']['max_wait_minutes']:g} minutes",
            "ride",
        ),
        ("Demand", f"{len(result['windows'])} windows of fourteen days", "demand"),
        (
            "Service floor",
            f"{inputs['policy']['service_floor']:.0%} of rides, at most {inputs['policy']['low_battery_visits_at_most']:.0%} of visits starting on a low battery",
            "policy",
        ),
    ]
    table = "".join(
        f"<tr><th>{esc(label)}</th><td>{esc(value)}</td><td>{esc(sources.get(key, 'assumed'))}</td></tr>"
        for label, value, key in assumed
    )
    warnings = []
    if result["at_the_edge_of_the_fleets_run"]:
        warnings.append(
            "The carried fleet is the smallest or largest fleet run, or none was carried: raise or lower [sweep] start, the share of the arithmetic where the search begins, and plan again."
        )
    if any(sources.get(key, "assumed") == "assumed" for key in ("energy", "parked_load")):
        warnings.append(
            "A vehicle's energy use is assumed. The fleet moves one for one with it: meter one vehicle's whole day, on the road and parked, before signing."
        )
    warnings += [f"Kept although unusual: {slip}." for slip in result.get("unusual_inputs", ())]
    if result.get("unsettled_runs_decided_a_fleet"):
        warnings.append(
            "A fleet that served the floor was not counted as carried because a run had not settled after its last replay. The carried fleet may be a step low."
        )
    if len(result["windows"]) < 4:
        warnings.append("Fewer than four demand windows. The windows are the sample: add weeks from other seasons.")
    answer = (
        f"Plan for {planned:,} vehicles, {result['planned_rides_per_day']:,.0f} rides a day."
        if planned
        else "No fleet among those run holds under every case. Lower [sweep] start and plan again."
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(result["site"])}: one-feeder plan</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#050f1e;max-width:820px;margin:40px auto;padding:0 16px}}h1{{font-size:1.9rem;line-height:1.15;margin:0 0 4px}}h2{{font-size:1.1rem;margin:28px 0 8px}}
table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #e5e9f0;font-weight:400;vertical-align:top}}thead th{{color:#5d6e83;font-size:.85rem}}
.answer{{font-size:1.35rem;margin:14px 0}}.note{{color:#5d6e83;font-size:.9rem}}.warn{{background:#fff5e6;padding:10px 14px;border-radius:8px;margin:8px 0}}</style>
<h1>{esc(result["site"])}</h1><p class="note">A simulated plan for one grid connection. Not a connection offer and not operating advice.</p>
<p class="answer"><b>{esc(answer)}</b></p>
<p>The feeder gives {result["usable_kwh_a_day"] / 1000:,.1f} MWh a day and a vehicle takes {result["feeder_kwh_per_vehicle_day"]:.0f} kWh of it, so arithmetic puts the fleet at {result["fleet_by_arithmetic"]:,}. Simulated, the largest fleet carried in every demand window is {carried if carried else "none of those run"}{f", {result['carried_against_arithmetic']:.0%} of the arithmetic" if carried else ""}. The plan is the fleet that is still carried under each case below taken alone. Past the carried fleet, what binds is {esc(result["what_binds_past_the_carried_fleet"] or "not known")}.</p>
{"".join(f'<p class="warn">{esc(w)}</p>' for w in warnings)}
<h2>What the feeder carries, case by case</h2>
<table><thead><tr><th>Case</th><th>Largest fleet carried in every window</th><th>Usable power in use</th><th>Feeder's energy a vehicle a day</th></tr></thead><tbody>{rows}</tbody></table>
<h2>One change at a time, at the estimated energy use</h2><ul>{changes or f"<li>{NO_CHANGES[result.get('changes_skipped') or 'no fleet carried']}</li>"}</ul>
<p class="note">Each change was tried at a few fleets around the carried one; "or more" means the largest fleet tried was still carried.</p>
<h2>What the answer rests on</h2>
<table><thead><tr><th>Input</th><th>Value</th><th>Measured or assumed</th></tr></thead><tbody>{table}</tbody></table>
<p class="note">{result["runs"]} simulated runs: {len(result["windows"])} demand windows, {result["draws_a_window"]} draws each, fleets of {result["fleets_run"][0]} to {result["fleets_run"][-1]}. A fleet is carried in a window when nine runs in ten serve the floor and the low-battery limit holds in the median run, and every run of the window has settled. Draws of a window are near copies of each other, so the windows are the sample.</p>
</html>
"""


def made_from(path: str | Path, site: dict) -> dict[str, str]:
    """A hash of the site file and of each demand file it names, so a plan can be held to its inputs."""
    names = [Path(path).name] + [str(w) for w in site["demand"]["windows"] if str(w).endswith(".csv")]
    folder = Path(path).parent
    return {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()[:12] for name in names}


def write(path: str | Path, out: str | Path, workers: int = 5, allow_unusual: bool = False) -> Path:
    """Plan the site in a file and write plan.json and brief.html to a folder."""
    from depot_twin import provenance

    site = load(path, allow_unusual)
    result = plan(site, workers)
    result["made_from"] = made_from(path, site)
    result["code"] = provenance.page_stamp("sites/plans/*.json")
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.json").write_text(json.dumps(result, indent=1) + "\n")
    (folder / "brief.html").write_text(brief(result))
    return folder
