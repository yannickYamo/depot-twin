"""What one feeder carries as the fleet's mix of vehicle types moves, and what the second type's unknowns and a rule that knows the type do to it.

Every capacity test before these ran one fleet, 60% I-PACE and 40% Ojai. E30 moves the share of Ojai from
none to all, at the estimated energy use and with 10% more, and reads what each type does in the depot.
E31 moves the Ojai's figures that have no public source, one at a time, on a fleet of Ojai alone. E32
replaces the rule that waits for a free charger, which calls the emptiest vehicles by share of charge, with
one that calls by range left at each vehicle's own energy use.

The runs are `cadence.capacity_run`, the capacity test's own. The simulator's code is not changed: the
worker processes keep the last run's simulator to read each type's visits off it, and for E32 the waiting
rule's choice of vehicles is replaced in those processes.
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

E30_SHARES = (0.0, 0.4, 0.7, 1.0)  # the share of the fleet that is Ojai
E30_ENERGY = (1.0, 1.1)
E30_SIZES = {
    (0.0, 1.0): (575, 600, 625, 650, 675),
    (0.0, 1.1): (525, 550, 575, 600, 625),
    (0.4, 1.0): (600, 625, 650, 675, 700),
    (0.4, 1.1): (550, 575, 600, 625, 650),
    (0.7, 1.0): (625, 650, 675, 700, 725),
    (0.7, 1.1): (575, 600, 625, 650, 675),
    (1.0, 1.0): (650, 675, 700, 725, 750),
    (1.0, 1.1): (600, 625, 650, 675, 700),
}
E30_PLAN = 600
E30_STEP = 25
E30_CARRIED_AT_THE_MIX = 675  # E26's fleet carried in every fortnight at the estimate, 40% Ojai
E30_ALL_NEW_AT_LEAST = 700

# E31: one Ojai figure moved at a time, on a fleet of Ojai alone at the estimate.
E31_SEEDS = 3
E31_VARIANTS = {
    "always_on_1.5": ({"always_on_kw": 1.5}, (725, 750, 775, 800, 825)),
    "always_on_2.5": ({"always_on_kw": 2.5}, (550, 575, 600, 625, 650)),
    # The control's own steps, so a variant that changes nothing reads the same fleet.
    "battery_85": ({"capacity_kwh": 85.0}, (650, 675, 700, 725, 750)),
    "battery_100": ({"capacity_kwh": 100.0}, (650, 675, 700, 725, 750)),
    "ipace_curve": ({"curve_of": "ipace"}, (650, 675, 700, 725, 750)),
}

E32_SIZES = (550, 600, 625, 650, 675, 700)  # E26's steps at the estimate
E32_AT_LEAST = 700

_LAST: dict = {}


def _keep_last_run() -> None:
    """In this process, keep each fleet run's simulator and result so its visits can be read by type."""
    from depot_twin import fleet

    if getattr(fleet.FleetSim, "_last_kept", False):
        return
    run = fleet.FleetSim.run

    def kept(self, days: float = 7.0):
        _LAST["sim"] = self
        result = run(self, days)
        _LAST["result"] = result
        return result

    setattr(fleet.FleetSim, "run", kept)  # noqa: B010
    setattr(fleet.FleetSim, "_last_kept", True)  # noqa: B010


def _call_by_range() -> None:
    """In this process, make the rule that waits call by hours of range left at each vehicle's own use."""
    from depot_twin import fleet

    _keep_last_run()
    if getattr(fleet.ThresholdRecall, "_by_range", False):
        return

    def recall(self, state) -> list[int]:
        sim = _LAST["sim"]
        cfg = state.fleet
        # Miles an hour on the road on average: the rides' own miles over the day, plus the idle drift.
        mph = cfg.rides_per_vehicle_day * (cfg.miles_to_pickup + cfg.miles_with_passenger) / 24.0 + cfg.idle_mph
        burn = np.asarray(sim.always_on_kw) + mph * np.asarray(sim.drive_kwh)
        hours = state.soc * state.capacity_kwh / burn
        # The waiting rule's level, 55% of a charge, in hours of range for the average vehicle.
        level = self.recall_soc * float(state.capacity_kwh.mean()) / float(burn.mean())
        on_road = state.on_road
        low = on_road[hours[on_road] <= level]
        if not self.wait_for_charger:
            return low.tolist()
        least = low[np.argsort(hours[low], kind="stable")]
        return least[: state.free_chargers].tolist()

    setattr(fleet.ThresholdRecall, "recall", recall)  # noqa: B010
    setattr(fleet.ThresholdRecall, "_by_range", True)  # noqa: B010


def _by_type(passes: int) -> dict:
    """What each vehicle type did over the last run's scored week."""
    from depot_twin.dispatch import HARD_FLOOR_SOC
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS

    sim, result = _LAST["sim"], _LAST["result"]
    total = E8_DAYS * passes
    first = (total - (E8_DAYS - E8_WARMUP_DAYS)) * 1440.0
    days = E8_DAYS - E8_WARMUP_DAYS
    names = [m.name for m in sim.config.models]
    counts = np.bincount(sim.model_of, minlength=len(names))
    out = {}
    for index, name in enumerate(names):
        vehicles = int(counts[index])
        if not vehicles:
            continue
        visits = [s for s in result.depot.sessions if s.visit.arrive_min >= first and s.visit.model.name == name]
        hours = np.bincount([int(s.visit.arrive_min // 60) % 24 for s in visits], minlength=24)
        on_charger = [s.charged_min - s.connected_min for s in visits if s.charged_min and s.connected_min]
        in_depot = [s.ready_min - s.visit.arrive_min for s in visits if s.ready_min]
        # Energy a visit over the visits whose charging finished in the window, as the browser counts it.
        finished = [s for s in visits if s.charged_min]
        energy = sum(s.energy_kwh for s in finished)
        out[name] = {
            "vehicles": vehicles,
            "visits": len(visits),
            "visits_per_vehicle_day": round(len(visits) / vehicles / days, 4),
            # The chance a vehicle of this type comes in during each hour of the day.
            "arrival_chance_by_hour": [round(float(h) / vehicles / days, 4) for h in hours],
            "kwh_per_visit": round(energy / max(len(finished), 1), 2),
            "kwh_per_vehicle_day": round(sum(s.energy_kwh for s in visits) / vehicles / days, 2),
            "minutes_on_charger": round(float(np.median(on_charger)), 1) if on_charger else None,
            "minutes_on_charger_10_90": [round(float(q), 1) for q in np.quantile(on_charger, (0.1, 0.9))]
            if on_charger
            else None,
            "minutes_in_depot": round(float(np.median(in_depot)), 1) if in_depot else None,
            "charge_in": round(float(np.median([s.visit.soc_in for s in visits])), 4) if visits else None,
            "arrived_at_floor_share": round(
                sum(s.visit.soc_in <= HARD_FLOOR_SOC for s in visits) / max(len(visits), 1), 4
            ),
        }
    return out


def mix_run(job: tuple) -> dict:
    """One capacity run, with what each vehicle type did."""
    from depot_twin import cadence

    run = cadence.capacity_run(job)
    return {**run, "by_type": _by_type(run["passes"])}


def _fleet_moves(fleet, share: float, energy: float, ojai: dict | None = None) -> dict:
    """The fleet's types and mix for a share of Ojai, with energy use scaled and any Ojai figure moved."""
    by_name = {m.name: m for m in fleet.models}
    models = []
    for name in ("ipace", "ojai"):
        model = by_name[name]
        model = replace(
            model, drive_kwh_per_mile=model.drive_kwh_per_mile * energy, always_on_kw=model.always_on_kw * energy
        )
        if name == "ojai" and ojai:
            moved = dict(ojai)
            if "curve_of" in moved:
                source = by_name[moved.pop("curve_of")]
                moved.update(dc_curve=source.dc_curve, max_dc_kw=source.max_dc_kw)
            if "always_on_kw" in moved:
                moved["always_on_kw"] = moved["always_on_kw"] * energy
            model = replace(model, **moved)
        models.append(model)
    return {"models": tuple(models), "mix": (1.0 - share, share)}


def _rows(runs: list[dict], sizes: tuple[int, ...], usable_kwh_a_day: float) -> dict:
    from depot_twin.evals import parked

    rows = {}
    for size in sizes:
        row = parked._row(runs, size, usable_kwh_a_day)
        mine = [r for r in runs if r["size"] == size]
        row["by_type"] = _types_median([r["by_type"] for r in mine])
        rows[str(size)] = row
    return rows


def _types_median(groups: list[dict]) -> dict:
    """Each type's figures, the median over runs; the hourly chances element by element."""
    names = sorted({name for group in groups for name in group})
    out = {}
    for name in names:
        mine = [g[name] for g in groups if name in g]
        figures = {}
        for key in mine[0]:
            values = [m[key] for m in mine if m[key] is not None]
            if not values:
                figures[key] = None
            elif isinstance(values[0], list):
                figures[key] = [round(float(v), 4) for v in np.median(np.asarray(values), axis=0)]
            else:
                figures[key] = round(float(np.median(values)), 4)
        out[name] = figures
    return out


def _carried(rows: dict, sizes: tuple[int, ...]) -> tuple[int | None, int | None]:
    from depot_twin.evals import parked

    return parked._carried(rows, sizes, every_fortnight=False), parked._carried(rows, sizes, every_fortnight=True)


def _exact(every: int | None, sizes: tuple[int, ...]) -> int | None:
    """The fleet carried in every fortnight when the steps pin it: None when the smallest fleet run was not
    carried or the largest was, since the fleet then lies below or above the steps and is not known."""
    return every if every is not None and every != sizes[-1] else None


def _rising(row: list[int | None]) -> bool:
    """Whether fleets never fall along a row, every one of them pinned by its steps."""
    pinned = [value for value in row if value is not None]
    return len(pinned) == len(row) and pinned == sorted(pinned)


def _setting():
    from depot_twin import cadence

    record = json.loads((data_dir() / "derived" / "e23_capacity.json").read_text())
    chosen, best = record["setting"], record["best_rule"]
    for window in cadence.E23_WINDOWS:
        replay_curves(window)
    fleet, depot = cadence._fleet_and_depot(600, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    return chosen, best, fleet, depot


def _key(share: float, energy: float) -> str:
    return f"{share:g}_{energy:g}"


def e30_mix(workers: int = 5) -> Path:
    """E30: the fleet one feeder carries at each share of Ojai, at the estimate and with 10% more energy use."""
    from depot_twin import cadence, provenance

    started_on = provenance.stamp("e30_mix.json")
    derived = data_dir() / "derived"
    chosen, best, fleet, depot = _setting()
    jobs = [
        (_key(share, energy), best, "slot_power", size, window, seed, chosen, _fleet_moves(fleet, share, energy))
        for share in E30_SHARES
        for energy in E30_ENERGY
        for size in E30_SIZES[(share, energy)]
        for window in cadence.E23_WINDOWS
        for seed in cadence.E23_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers, initializer=_keep_last_run) as pool:
        runs = list(pool.map(mix_run, jobs, chunksize=4))
    usable = depot.usable_kw * 24.0
    arms = {}
    for share in E30_SHARES:
        for energy in E30_ENERGY:
            sizes = E30_SIZES[(share, energy)]
            rows = _rows([r for r in runs if r["label"] == _key(share, energy)], sizes, usable)
            whole, every = _carried(rows, sizes)
            arms[_key(share, energy)] = {
                "share_ojai": share,
                "energy": energy,
                "by_size": rows,
                "carried": whole,
                "carried_in_every_fortnight": every,
                # The largest fleet run was carried: the fleet carried is at least this, not this.
                "at_the_top_of_the_steps": every == sizes[-1],
            }
    # Each type's energy a vehicle-day, put into its battery, at 600 vehicles and 40% Ojai: every run there
    # settles and serves all its rides with no visit starting low, so each type takes all it uses. The
    # arithmetic scales the fleet E26 carried by the energy a vehicle-day at 40% over that at each share.
    need = arms[_key(0.4, 1.0)]["by_size"][str(E30_PLAN)]["by_type"]
    kwh = {name: need[name]["kwh_per_vehicle_day"] for name in ("ipace", "ojai")}
    per_day = {f"{share:g}": (1.0 - share) * kwh["ipace"] + share * kwh["ojai"] for share in E30_SHARES}
    arithmetic = {share: E30_CARRIED_AT_THE_MIX * per_day["0.4"] / value for share, value in per_day.items()}
    every = {key: arm["carried_in_every_fortnight"] or 0 for key, arm in arms.items()}
    exact = {
        key: _exact(arm["carried_in_every_fortnight"], E30_SIZES[(arm["share_ojai"], arm["energy"])])
        for key, arm in arms.items()
    }
    # The 40% arm against E26's runs at the estimate: the same fortnights, seeds and setting.
    margin = json.loads((derived / "e26_margin.json").read_text())
    before = {
        (r["size"], r["window"], r["seed"]): r for r in margin["runs"] if r["label"] == "energy_1" and r["rule"] == best
    }
    again = [r for r in runs if r["label"] == _key(0.4, 1.0) and (r["size"], r["window"], r["seed"]) in before]
    same = sum(
        all(
            r[key] == before[(r["size"], r["window"], r["seed"])][key]
            for key in ("served", "arrived_at_floor_share", "grid_share_used")
        )
        for r in again
    )
    bars = {
        "1_all_ojai_carries_at_least_700_in_every_fortnight_at_the_estimate": every[_key(1.0, 1.0)]
        >= E30_ALL_NEW_AT_LEAST,
        "2_all_ipace_carries_600_in_every_fortnight_at_the_estimate": every[_key(0.0, 1.0)] >= E30_PLAN,
        # Bars 3 and 4 compare fleets, so each must be pinned by its steps; one that is not is a miss.
        "3_the_fleet_carried_never_falls_as_the_share_of_ojai_rises": all(
            _rising([exact[_key(s, e)] for s in E30_SHARES]) for e in E30_ENERGY
        ),
        "4_at_each_share_the_fleet_carried_is_within_one_step_of_the_arithmetic": all(
            (value := exact[_key(float(share), 1.0)]) is not None and abs(value - figure) <= E30_STEP
            for share, figure in arithmetic.items()
        ),
        "5_600_is_carried_in_every_fortnight_at_every_share_and_both_energies": all(
            v >= E30_PLAN for v in every.values()
        ),
    }
    if provenance.stamp("e30_mix.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E30 ran: its runs cannot be stamped")
    return _write(
        "e30_mix.json",
        {
            "eval": "E30",
            "rule": best,
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(cadence.E23_SEEDS),
            "usable_kwh_a_day": round(usable, 0),
            "arms": arms,
            "battery_kwh_per_vehicle_day_by_type_at_600": kwh,
            "battery_kwh_per_vehicle_day_by_share": {k: round(v, 1) for k, v in per_day.items()},
            "arithmetic": {share: round(value, 1) for share, value in arithmetic.items()},
            "planned_by_share": {
                f"{share:g}": min(
                    arms[_key(share, 1.0)]["carried_in_every_fortnight"] or 0,
                    arms[_key(share, 1.1)]["carried_in_every_fortnight"] or 0,
                )
                for share in E30_SHARES
            },
            "same_as_e26": {"runs": len(again), "identical": same},
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def e31_new_vehicle(workers: int = 5) -> Path:
    """E31: a fleet of Ojai alone with each of its unsourced figures moved, against E30's arm on the same seeds."""
    from depot_twin import cadence, provenance

    started_on = provenance.stamp("e31_new_vehicle.json")
    derived = data_dir() / "derived"
    chosen, best, fleet, depot = _setting()
    seeds = cadence.E23_SEEDS[:E31_SEEDS]
    jobs = [
        (name, best, "slot_power", size, window, seed, chosen, _fleet_moves(fleet, 1.0, 1.0, moved))
        for name, (moved, sizes) in E31_VARIANTS.items()
        for size in sizes
        for window in cadence.E23_WINDOWS
        for seed in seeds
    ]
    with ProcessPoolExecutor(max_workers=workers, initializer=_keep_last_run) as pool:
        runs = list(pool.map(mix_run, jobs, chunksize=4))
    usable = depot.usable_kw * 24.0
    mix = json.loads((derived / "e30_mix.json").read_text())
    control_sizes = E30_SIZES[(1.0, 1.0)]
    control_runs = [r for r in mix["runs"] if r["label"] == _key(1.0, 1.0) and r["seed"] in seeds]
    control_rows = _rows(control_runs, control_sizes, usable)
    control = _exact(_carried(control_rows, control_sizes)[1], control_sizes)
    variants = {}
    for name, (moved, sizes) in E31_VARIANTS.items():
        rows = _rows([r for r in runs if r["label"] == name], sizes, usable)
        whole, every = _carried(rows, sizes)
        variants[name] = {
            "moved": moved,
            "by_size": rows,
            "carried": whole,
            "carried_in_every_fortnight": every,
            "at_the_top_of_the_steps": every == sizes[-1],
        }
    every = {name: v["carried_in_every_fortnight"] or 0 for name, v in variants.items()}
    # Bars 2 to 4 compare fleets, so each must be pinned by its steps; one that is not is a miss.
    exact = {name: _exact(v["carried_in_every_fortnight"], E31_VARIANTS[name][1]) for name, v in variants.items()}

    def moved(name: str) -> bool:
        value = exact[name]
        return control is not None and value is not None and abs(value - control) <= E30_STEP

    pinned = all(exact[name] is not None for name in ("always_on_1.5", "always_on_2.5", "battery_85", "battery_100"))
    load_span = abs(every["always_on_1.5"] - every["always_on_2.5"])
    battery_span = abs(every["battery_85"] - every["battery_100"])
    bars = {
        "1_with_the_always_on_load_at_2.5_kw_600_are_carried_in_every_fortnight": every["always_on_2.5"] >= E30_PLAN,
        "2_a_battery_of_85_or_100_kwh_moves_the_fleet_by_at_most_one_step": moved("battery_85")
        and moved("battery_100"),
        "3_the_ipace_charging_curve_moves_it_by_at_most_one_step": moved("ipace_curve"),
        "4_the_always_on_load_moves_it_further_than_the_battery": pinned and load_span > battery_span,
    }
    if provenance.stamp("e31_new_vehicle.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E31 ran: its runs cannot be stamped")
    return _write(
        "e31_new_vehicle.json",
        {
            "eval": "E31",
            "rule": best,
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(seeds),
            "control": {"by_size": control_rows, "carried_in_every_fortnight": control},
            "variants": variants,
            "spans": {"always_on": load_span, "battery": battery_span, "pinned": pinned},
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def e32_range(workers: int = 5) -> Path:
    """E32: a waiting rule that calls by range left at each vehicle's own use, against E26's rule that waits."""
    from depot_twin import cadence, provenance

    started_on = provenance.stamp("e32_range.json")
    derived = data_dir() / "derived"
    chosen, best, fleet, depot = _setting()
    jobs = [
        ("range", best, "slot_power", size, window, seed, chosen, _fleet_moves(fleet, 0.4, 1.0))
        for size in E32_SIZES
        for window in cadence.E23_WINDOWS
        for seed in cadence.E23_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers, initializer=_call_by_range) as pool:
        runs = list(pool.map(mix_run, jobs, chunksize=4))
    usable = depot.usable_kw * 24.0
    from depot_twin.evals import parked

    rows = _rows(runs, E32_SIZES, usable)
    whole, every = _carried(rows, E32_SIZES)
    margin = json.loads((derived / "e26_margin.json").read_text())
    waits_runs = [
        r for r in margin["runs"] if r["label"] == "energy_1" and r["rule"] == best and r["size"] in E32_SIZES
    ]
    waits = {str(size): parked._row(waits_runs, size, usable) for size in E32_SIZES}
    waits_every = parked._carried(waits, E32_SIZES, every_fortnight=True) or 0
    bars = {
        "1_the_rule_that_knows_the_type_carries_at_least_700_in_every_fortnight": (every or 0) >= E32_AT_LEAST,
        "2_at_600_and_700_it_serves_at_least_as_many_rides_in_the_median_run": all(
            rows[str(size)]["served_median"] >= waits[str(size)]["served_median"] for size in (600, 700)
        ),
        "3_at_675_its_worst_fortnight_has_fewer_visits_starting_low": rows["675"][
            "arrived_at_floor_share_worst_fortnight"
        ]
        < waits["675"]["arrived_at_floor_share_worst_fortnight"],
    }
    if provenance.stamp("e32_range.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E32 ran: its runs cannot be stamped")
    return _write(
        "e32_range.json",
        {
            "eval": "E32",
            "rule": "range_waits",
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(cadence.E23_SEEDS),
            "by_size": rows,
            "carried": whole,
            "carried_in_every_fortnight": every,
            "the_rule_that_waits": {"by_size": waits, "carried_in_every_fortnight": waits_every},
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
