"""The controller and the depot's rules: E8 to E12, the session-length and staffing studies, E14 and the sensitivity study.

Each function corresponds to one entry in EVALS.md; the registration there fixes the data, the split, the
metric and the bar before the run it reports, and this module only executes it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from depot_twin.data import data_dir
from depot_twin.evals.common import (
    E8_DAYS,
    E8_DEV_START,
    E8_RULES,
    E8_SEEDS,
    E8_SIZES,
    E8_START,
    E8_WARMUP_DAYS,
    E9_LEDGER,
    E9_SEEDS,
    E9_START,
    E12_ARMS,
    E12_SEEDS,
    E12_SETTINGS,
    E12_START,
    _chicago_curves,
    _e8_rule,
    _e8_scores,
    _write,
    replay_curves,
    what_ran,
)
from depot_twin.fleet import served_share


def e8_run(job: tuple[str, int, int, str], settings: dict | None = None) -> dict:
    """Run one rule at one fleet size and seed against replayed demand, and score it.

    settings overrides the heartbeat's defaults; it is used in development only.
    """
    import numpy as np

    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.replay import ReplayDemand
    from depot_twin.twin import EnergyIdentifier

    rule_name, size, seed, start = job
    fleet, depot = load_fleet_scenario(f"scenarios/v2/east_oakland_{size}.toml")
    demand = ReplayDemand.scaled(replay_curves(start), size * fleet.rides_per_vehicle_day)
    rule = _e8_rule(rule_name, settings)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    policy = "slot_power" if rule_name == "heartbeat" else "need_first"
    sim = FleetSim(fleet, depot, shape, rule, depot_policy=policy, seed=seed, demand=demand)
    # Every rule runs with the same telemetry stream; only the heartbeat plans with what it identifies.
    nominal_drive = np.array([m.drive_kwh_per_mile for m in fleet.models])[sim.model_of]
    nominal_load = np.array([m.always_on_kw for m in fleet.models])[sim.model_of]
    sim.telemetry = EnergyIdentifier(nominal_drive, nominal_load, sim.capacity, seed=seed)
    if rule_name == "heartbeat":
        rule.energy = sim.telemetry
    result = sim.run(E8_DAYS)
    return {"rule": rule_name, "size": size, "seed": seed, **_e8_scores(sim, result, rule, demand, depot)}


def e8_heartbeat(workers: int = 5) -> Path:
    """E8: the heartbeat controller against the headroom rule and the threshold, on replayed demand."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E8_START)  # built once here so the workers only read it
    jobs = [(rule, size, seed, E8_START) for rule in E8_RULES for size in E8_SIZES for seed in E8_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(e8_run, jobs))
    table = {}
    for rule in E8_RULES:
        for size in E8_SIZES:
            group = [r for r in runs if r["rule"] == rule and r["size"] == size]
            keys = [k for k in group[0] if k not in ("rule", "size", "seed")]
            table[f"{rule}_{size}"] = {k: round(float(np.mean([r[k] for r in group])), 4) for k in keys}
    beat_500, beat_1000 = table["heartbeat_500"], table["heartbeat_1000"]
    bars = {
        "1_serves_1pt_more_at_1000_and_no_worse_at_500": beat_1000["served"] >= table["headroom_1000"]["served"] + 0.01
        and beat_500["served"] >= table["headroom_500"]["served"] - 0.002,
        "2_ledger_kept_95pct_of_hours": beat_500["ledger_kept"] >= 0.95 and beat_1000["ledger_kept"] >= 0.95,
        "3_no_vehicle_stranded": beat_500["stranded"] == 0 and beat_1000["stranded"] == 0,
        "4_grid_variation_at_most_half_of_headroom_at_500": beat_500["grid_variation"]
        <= 0.5 * table["headroom_500"]["grid_variation"],
        "5_tick_under_50ms_median_and_500ms_p99": max(beat_500["tick_ms_median"], beat_1000["tick_ms_median"]) <= 50.0
        and max(beat_500["tick_ms_p99"], beat_1000["tick_ms_p99"]) <= 500.0,
    }
    return _write(
        "e8_heartbeat.json",
        {
            "eval": "E8",
            "start": E8_START,
            "seeds": list(E8_SEEDS),
            "table": table,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def growth_study_v2() -> Path:
    """The growth study again: per-vehicle energy, replayed demand, heartbeat against headroom."""
    from depot_twin import growth

    replay_curves(E8_START)
    sizes = [200, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000]
    rows = growth.sweep_v2(sizes, seeds=[11, 12, 13], start=E8_START)
    limits = {}
    for option in growth.OPTIONS:
        for rule in growth.RULES_V2:
            mine = [r for r in rows if r["option"] == option and r["rule"] == rule]
            limits[f"{option}_{rule}"] = {
                "serves_99pct_up_to": growth.largest_fleet(mine, option, 0.99),
                "serves_95pct_up_to": growth.largest_fleet(mine, option, 0.95),
            }
    return _write(
        "growth_v2.json", {"start": E8_START, "rows": rows, "limits": limits, "run": date.today().isoformat()}
    )


def _e9_run(job: tuple[str, int, int]) -> dict:
    rule, size, seed = job
    return e8_run((rule, size, seed, E9_START), E9_LEDGER if rule == "heartbeat" else None)


def e9_ledger(workers: int = 5) -> Path:
    """E9: the ledger built from the fleet's present state, and E8's comparison repeated, on days not used before."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E9_START)
    jobs = [(rule, size, seed) for rule in ("headroom", "heartbeat") for size in E8_SIZES for seed in E9_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e9_run, jobs))
    table = {}
    for rule in ("headroom", "heartbeat"):
        for size in E8_SIZES:
            group = [r for r in runs if r["rule"] == rule and r["size"] == size]
            keys = [k for k in group[0] if k not in ("rule", "size", "seed")]
            table[f"{rule}_{size}"] = {k: round(float(np.mean([r[k] for r in group])), 4) for k in keys}
    beat_500, beat_1000 = table["heartbeat_500"], table["heartbeat_1000"]
    bars = {
        "1_ledger_kept_95pct_of_hours": beat_500["ledger_kept"] >= 0.95 and beat_1000["ledger_kept"] >= 0.95,
        "2_promises_at_least_90pct_of_what_was_delivered": min(
            beat_500["ledger_promised_share"], beat_1000["ledger_promised_share"]
        )
        >= 0.90,
        "3_serves_1pt_more_at_1000_and_no_worse_at_500": beat_1000["served"] >= table["headroom_1000"]["served"] + 0.01
        and beat_500["served"] >= table["headroom_500"]["served"] - 0.002,
        "4_no_vehicle_stranded": beat_500["stranded"] == 0 and beat_1000["stranded"] == 0,
    }
    return _write(
        "e9_ledger.json",
        {
            "eval": "E9",
            "start": E9_START,
            "seeds": list(E9_SEEDS),
            "table": table,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


E10_SEEDS = (311, 312, 313)
E10_FAULT_MINUTE = E8_WARMUP_DAYS * 1440.0
E10_FAULT_FACTOR = 0.33
E10_ARMS = ("sound", "sound_guarded", "fault", "fault_guarded", "threshold")


def _e10_run(job: tuple[str, int, int]) -> dict:
    """Run one arm of the guard test: a sound or faulty forecast, with or without the guard."""
    from dataclasses import replace as with_changes

    from depot_twin.fleet import FleetSim, ThresholdRecall, load_fleet_scenario, load_weekly_shape
    from depot_twin.guard import Guarded
    from depot_twin.heartbeat import Heartbeat
    from depot_twin.replay import ReplayDemand

    arm, size, seed = job
    fleet, depot = load_fleet_scenario(f"scenarios/v2/east_oakland_{size}.toml")
    demand = ReplayDemand.scaled(replay_curves(E9_START), size * fleet.rides_per_vehicle_day)
    if arm.startswith("fault"):
        demand = with_changes(demand, fault_from_minute=E10_FAULT_MINUTE, fault_factor=E10_FAULT_FACTOR)
    if arm == "threshold":
        rule = ThresholdRecall()
    elif arm.endswith("guarded"):
        rule = Guarded(Heartbeat(**E9_LEDGER), ThresholdRecall())
    else:
        rule = Heartbeat(**E9_LEDGER)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand)
    result = sim.run(E8_DAYS)
    steps = result.steps[result.steps[:, 0] >= E10_FAULT_MINUTE]
    events = getattr(rule, "events", [])
    fell_back = [e["hour"] for e in events if e["event"] == "fell back"]
    return {
        "arm": arm,
        "size": size,
        "seed": seed,
        "served": served_share(steps),
        "stranded": float(result.stranded),
        "fell_back": len(fell_back),
        "hours_to_fall_back": (fell_back[0] - E10_FAULT_MINUTE / 60.0) if fell_back else None,
    }


def e10_guard(workers: int = 5) -> Path:
    """E10: the forecast guard under a sound forecast and under a stale one."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E9_START)
    jobs = [(arm, size, seed) for arm in E10_ARMS for size in E8_SIZES for seed in E10_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e10_run, jobs))
    table = {}
    for arm in E10_ARMS:
        for size in E8_SIZES:
            group = [r for r in runs if r["arm"] == arm and r["size"] == size]
            delays = [r["hours_to_fall_back"] for r in group if r["hours_to_fall_back"] is not None]
            table[f"{arm}_{size}"] = {
                "served": round(float(np.mean([r["served"] for r in group])), 4),
                "stranded": sum(r["stranded"] for r in group),
                "runs_that_fell_back": sum(r["fell_back"] > 0 for r in group),
                "hours_to_fall_back_worst": max(delays) if delays else None,
            }
    bars = {
        "1_no_false_alarm": all(table[f"sound_guarded_{size}"]["runs_that_fell_back"] == 0 for size in E8_SIZES),
        "2_falls_back_within_12_hours_every_run": all(
            table[f"fault_guarded_{size}"]["runs_that_fell_back"] == len(E10_SEEDS)
            and table[f"fault_guarded_{size}"]["hours_to_fall_back_worst"] <= 12
            for size in E8_SIZES
        ),
        "3_guarded_serves_at_least_as_many_under_the_fault": all(
            table[f"fault_guarded_{size}"]["served"] >= table[f"fault_{size}"]["served"] - 0.002 for size in E8_SIZES
        ),
    }
    return _write(
        "e10_guard.json",
        {
            "eval": "E10",
            "start": E9_START,
            "seeds": list(E10_SEEDS),
            "table": table,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


E11_SEEDS = (321, 322, 323)
E11_RECALL = ("threshold", "headroom", "heartbeat")
E11_POWER = ("need_first", "slot_power")


def _e11_run(job: tuple[str, str, int, int]) -> dict:
    """Run one cell of the grid: a way of calling vehicles in with a way of sharing power."""
    import numpy as np

    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.replay import ReplayDemand

    recall, power, size, seed = job
    fleet, depot = load_fleet_scenario(f"scenarios/v2/east_oakland_{size}.toml")
    demand = ReplayDemand.scaled(replay_curves(E9_START), size * fleet.rides_per_vehicle_day)
    rule = _e8_rule(recall, E9_LEDGER if recall == "heartbeat" else None)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    result = FleetSim(fleet, depot, shape, rule, depot_policy=power, seed=seed, demand=demand).run(E8_DAYS)
    first = E8_WARMUP_DAYS * 1440.0
    steps = result.steps[result.steps[:, 0] >= first]
    series = result.depot.series[result.depot.series[:, 0] >= first]
    busy = steps[:, 1] >= np.quantile(steps[:, 1], 0.9)
    return {
        "recall": recall,
        "power": power,
        "size": size,
        "served": served_share(steps),
        "on_road_when_busiest": float(steps[busy, 3].mean() / size),
        "grid_variation": float(series[:, 1].std() / series[:, 1].mean()),
        "stranded": float(result.stranded),
    }


def e11_apart(workers: int = 5) -> Path:
    """E11: every way of calling vehicles in with every way of sharing power."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E9_START)
    jobs = [(r, p, size, seed) for r in E11_RECALL for p in E11_POWER for size in E8_SIZES for seed in E11_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e11_run, jobs))
    table = {}
    for recall in E11_RECALL:
        for power in E11_POWER:
            for size in E8_SIZES:
                group = [r for r in runs if (r["recall"], r["power"], r["size"]) == (recall, power, size)]
                table[f"{recall}+{power}_{size}"] = {
                    key: round(float(np.mean([r[key] for r in group])), 4)
                    for key in ("served", "on_road_when_busiest", "grid_variation", "stranded")
                }
    return _write(
        "e11_apart.json",
        {"eval": "E11", "start": E9_START, "seeds": list(E11_SEEDS), "table": table, "run": date.today().isoformat()},
    )


def e12_run(job: tuple[str, int, int, str], settings: dict | None = None) -> dict:
    """Run one arm of the cost test and return service, energy bought by tariff period and money."""
    from depot_twin.economics import Prices, energy_by_period
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_fleet_scenario, load_weekly_shape
    from depot_twin.heartbeat import Heartbeat
    from depot_twin.replay import ReplayDemand

    arm, size, seed, start = job
    prices = Prices()
    fleet, depot = load_fleet_scenario(f"scenarios/v2/east_oakland_{size}.toml")
    demand = ReplayDemand.scaled(replay_curves(start), size * fleet.rides_per_vehicle_day)
    if arm == "threshold":
        rule = ThresholdRecall()
    elif arm == "threshold_steered":
        from depot_twin.dispatch import SteeredThreshold

        rule = SteeredThreshold()
    else:
        chosen = E12_SETTINGS if settings is None else settings
        extra = {"prices": prices, **chosen} if arm in ("plan_with_prices", "plan_clock_only") else {}
        rule = Heartbeat(**E9_LEDGER, **extra, price_in_program=arm != "plan_clock_only")
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    result = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand).run(E8_DAYS)
    first = E8_WARMUP_DAYS * 1440.0
    days = E8_DAYS - E8_WARMUP_DAYS
    steps = result.steps[result.steps[:, 0] >= first]
    energy = energy_by_period(result.depot.series, skip_days=E8_WARMUP_DAYS)
    bought = sum(energy.values())
    cost = energy["peak"] * prices.energy_peak + energy["off_peak"] * prices.energy_off_peak
    cost += energy["super_off_peak"] * prices.energy_super_off_peak
    revenue = float(steps[:, 2].sum()) * prices.revenue_per_ride
    return {
        "arm": arm,
        "size": size,
        "seed": seed,
        "served": served_share(steps),
        "stranded": float(result.stranded),
        "cost_per_kwh": cost / bought,
        "peak_period_share": energy["peak"] / bought,
        "energy_cost_per_vehicle_day": cost / size / days,
        "fares_less_energy_per_vehicle_day": (revenue - cost) / size / days,
        "kwh_per_vehicle_day": bought / size / days,
        **what_ran(result, rule, size, sum(b.count for b in depot.chargers), first, days),
    }


def e12_cost(workers: int = 5) -> Path:
    """E12: does a plan that knows the price of energy buy it cheaper, at equal service?"""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E12_START)
    jobs = [(arm, size, seed, E12_START) for arm in E12_ARMS for size in E8_SIZES for seed in E12_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(e12_run, jobs))
    table = {}
    for arm in E12_ARMS:
        for size in E8_SIZES:
            group = [r for r in runs if r["arm"] == arm and r["size"] == size]
            keys = [k for k in group[0] if k not in ("arm", "size", "seed")]
            table[f"{arm}_{size}"] = {k: round(float(np.mean([r[k] for r in group])), 4) for k in keys}
    priced, plain = table["plan_with_prices_500"], table["threshold_500"]
    bars = {
        "1_energy_at_least_5pct_cheaper_per_kwh_at_500": priced["cost_per_kwh"] <= 0.95 * plain["cost_per_kwh"],
        "2_rides_within_0.1pt_of_threshold_at_500": priced["served"] >= plain["served"] - 0.001,
        "3_fares_less_energy_higher_than_threshold_at_500": priced["fares_less_energy_per_vehicle_day"]
        > plain["fares_less_energy_per_vehicle_day"],
        "4_no_vehicle_stranded": priced["stranded"] == 0 and table["plan_with_prices_1000"]["stranded"] == 0,
    }
    return _write(
        "e12_cost.json",
        {
            "eval": "E12",
            "start": E12_START,
            "seeds": list(E12_SEEDS),
            "table": table,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def _session_run(job: tuple[float, float, float, int, int]) -> dict:
    """Run the controller with one slot length, at one depot distance and charger power."""
    from dataclasses import replace as with_changes

    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.heartbeat import Heartbeat
    from depot_twin.replay import ReplayDemand
    from depot_twin.resources import ChargerBank

    leg_minutes, charger_kw, beat, size, seed = job
    fleet, depot = load_fleet_scenario(f"scenarios/v2/east_oakland_{size}.toml")
    # Distance scales the drive both ways: the scenario's 15 minutes is 4 miles.
    fleet = with_changes(fleet, depot_leg_minutes=leg_minutes, depot_leg_miles=4.0 * leg_minutes / 15.0)
    depot = with_changes(depot, chargers=(ChargerBank("dc", depot.chargers[0].count, charger_kw),))
    demand = ReplayDemand.scaled(replay_curves(E8_DEV_START), size * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    rule = Heartbeat(beat_min=beat, **E9_LEDGER)
    result = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand).run(E8_DAYS)
    steps = result.steps[result.steps[:, 0] >= E8_WARMUP_DAYS * 1440.0]
    sessions = [s for s in result.depot.sessions if s.charged_min and s.connected_min >= E8_WARMUP_DAYS * 1440.0]
    return {
        "leg_minutes": leg_minutes,
        "charger_kw": charger_kw,
        "beat": beat,
        "size": size,
        "served": served_share(steps),
        "kwh_per_session": float(sum(s.energy_kwh for s in sessions) / max(1, len(sessions))),
        "sessions_per_vehicle_day": len(sessions) / size / (E8_DAYS - E8_WARMUP_DAYS),
        "stranded": float(result.stranded),
    }


def session_length_study(workers: int = 5) -> Path:
    """When do short charging sessions win? Slot length against depot distance and charger power."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E8_DEV_START)
    legs, powers, beats, sizes, seeds = (
        (5.0, 10.0, 15.0),
        (60.0, 150.0),
        (20.0, 30.0, 45.0, 60.0),
        (500, 1000),
        (31, 32),
    )
    jobs = [
        (leg, kw, beat, size, seed)
        for leg in legs
        for kw in powers
        for beat in beats
        for size in sizes
        for seed in seeds
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_session_run, jobs))
    rows = []
    for leg in legs:
        for kw in powers:
            for size in sizes:
                cell = {"leg_minutes": leg, "charger_kw": kw, "size": size}
                for beat in beats:
                    group = [
                        r
                        for r in runs
                        if (r["leg_minutes"], r["charger_kw"], r["beat"], r["size"]) == (leg, kw, beat, size)
                    ]
                    cell[f"served_{int(beat)}min"] = round(float(np.mean([r["served"] for r in group])), 4)
                    cell[f"kwh_{int(beat)}min"] = round(float(np.mean([r["kwh_per_session"] for r in group])), 1)
                served = {beat: cell[f"served_{int(beat)}min"] for beat in beats}
                cell["best_beat_min"] = max(served, key=served.get)
                cell["stranded"] = sum(
                    r["stranded"] for r in runs if (r["leg_minutes"], r["charger_kw"], r["size"]) == (leg, kw, size)
                )
                rows.append(cell)
    return _write("session_length.json", {"start": E8_DEV_START, "rows": rows, "run": date.today().isoformat()})


def _staffing_run(job: tuple[int, str, int]) -> dict:
    """Run a threshold rule with one power rule and one number of depot staff, recording where vehicles wait."""
    from dataclasses import replace as with_changes

    import numpy as np

    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.replay import ReplayDemand
    from depot_twin.trace import TraceRecorder

    staff, power, seed = job
    size = 1000
    fleet, depot = load_fleet_scenario(f"scenarios/v2/east_oakland_{size}.toml")
    depot = with_changes(depot, staff=staff)
    demand = ReplayDemand.scaled(replay_curves(E8_DEV_START), size * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(fleet, depot, shape, _e8_rule("threshold"), depot_policy=power, seed=seed, demand=demand)
    recorder = TraceRecorder(sim)
    sim.run(E8_DAYS)
    kept = np.array(recorder.steps["minute"]) >= E8_WARMUP_DAYS * 1440.0

    def mean(name: str) -> float:
        return float(np.array(recorder.steps[name], dtype=float)[kept].mean())

    offered, served = (np.array(recorder.steps[name], dtype=float)[kept].sum() for name in ("offered", "served"))
    return {
        "staff": staff,
        "power": power,
        "served": float(served / offered),
        "grid_kw": mean("grid_kw"),
        "charging": mean("charging"),
        "between_stations": mean("handling"),
        "queued": mean("queued"),
    }


def staffing_study(workers: int = 5) -> Path:
    """Why does in-order feeding win? The two power rules at 1,000 vehicles, with more and more depot staff."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E8_DEV_START)
    levels, rules, seeds = (25, 50, 100, 200), ("need_first", "slot_power"), (31, 32)
    jobs = [(staff, power, seed) for staff in levels for power in rules for seed in seeds]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_staffing_run, jobs))
    rows = []
    for staff in levels:
        for power in rules:
            group = [r for r in runs if (r["staff"], r["power"]) == (staff, power)]
            row = {"staff": staff, "power": power}
            for name in ("served", "grid_kw", "charging", "between_stations", "queued"):
                row[name] = round(float(np.mean([r[name] for r in group])), 4 if name == "served" else 1)
            rows.append(row)
    return _write("staffing.json", {"start": E8_DEV_START, "size": 1000, "rows": rows, "run": date.today().isoformat()})


E14_START = "2026-03-02"  # a Monday in Chicago's ride-hail record; no depot has been run on Chicago before
E14_SEEDS = (601, 602, 603, 604, 605)
E14_POWER = ("need_first", "slot_power", "least_left")
E14_STAFF = (25, 100)


def power_rule_run(job: tuple[str, int, int, str]) -> dict:
    """Run a threshold with one power rule and staffing level at 1,000 vehicles; return service and where vehicles wait."""
    from dataclasses import replace as with_changes

    import numpy as np

    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.replay import ReplayDemand
    from depot_twin.trace import TraceRecorder

    power, staff, seed, days = job
    fleet, depot = load_fleet_scenario("scenarios/v2/east_oakland_1000.toml")
    depot = with_changes(depot, staff=staff)
    curves = replay_curves(days) if days.startswith("2024") else _chicago_curves(days)
    demand = ReplayDemand.scaled(curves, fleet.size * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(fleet, depot, shape, _e8_rule("threshold"), depot_policy=power, seed=seed, demand=demand)
    recorder = TraceRecorder(sim)
    result = sim.run(E8_DAYS)
    kept = np.array(recorder.steps["minute"]) >= E8_WARMUP_DAYS * 1440.0

    def column(name: str) -> np.ndarray:
        return np.array(recorder.steps[name], dtype=float)[kept]

    return {
        "power": power,
        "staff": staff,
        "served": float(column("served").sum() / column("offered").sum()),
        "grid_share_used": float(column("grid_kw").mean() / depot.usable_kw),
        "between_stations": float(column("handling").mean()),
        "stranded": float(result.stranded),
    }


def _power_table(runs: list[dict]) -> dict:
    import numpy as np

    table = {}
    for power in E14_POWER:
        for staff in E14_STAFF:
            group = [r for r in runs if (r["power"], r["staff"]) == (power, staff)]
            if group:
                table[f"{power}_{staff}"] = {
                    key: round(float(np.mean([r[key] for r in group])), 4)
                    for key in ("served", "grid_share_used", "between_stations", "stranded")
                }
    return table


def e14_power_rules(
    workers: int = 5, days: str = E14_START, seeds: tuple = E14_SEEDS, name: str = "e14_power_rules.json"
) -> Path:
    """E14: the three power rules on fresh days from another city, at two staffing levels."""
    from concurrent.futures import ProcessPoolExecutor

    _chicago_curves(E14_START) if not days.startswith("2024") else replay_curves(days)
    jobs = [(power, staff, seed, days) for power in E14_POWER for staff in E14_STAFF for seed in seeds]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        table = _power_table(list(pool.map(power_rule_run, jobs)))
    gap = {
        staff: table[f"slot_power_{staff}"]["served"] - table[f"need_first_{staff}"]["served"] for staff in E14_STAFF
    }
    bars = {
        "in_order_beats_emptiest_by_2_points_at_25_staff": gap[25] >= 0.02,
        "gap_smaller_but_positive_at_100_staff": 0.0 < gap[100] < gap[25],
        "emptiest_leaves_4pct_of_power_unused_in_order_under_1pct": (
            table["need_first_25"]["grid_share_used"] <= 0.96 and table["slot_power_25"]["grid_share_used"] >= 0.99
        ),
        "least_left_serves_no_fewer_than_in_order": all(
            table[f"least_left_{staff}"]["served"] >= table[f"slot_power_{staff}"]["served"] - 0.001
            for staff in E14_STAFF
        ),
    }
    return _write(name, {"eval": "E14", "days": days, "table": table, "bars": bars, "run": date.today().isoformat()})


SENSITIVITY_CASES = {
    "as modelled": {},
    "rides per vehicle: 21.5": {"rides": 21.5},
    "rides per vehicle: 18": {"rides": 18.0},
    "energy per mile: 10% lower": {"energy": 0.9},
    "energy per mile: 10% higher": {"energy": 1.1},
    "called in at 40% charge": {"recall_soc": 0.40},
    "called in at 55% charge": {"recall_soc": 0.55},
    "twice the people": {"people": 2.0},
}


def _sensitivity_run(job: tuple[str, int, int]) -> dict:
    """Run a threshold with in-order feeding at one fleet size, with one input moved off its modelled value."""
    from dataclasses import replace as with_changes

    from depot_twin import growth
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape
    from depot_twin.replay import ReplayDemand

    case, size, seed = job
    change = SENSITIVITY_CASES[case]
    fleet, depot = growth.scaled_v2(size, **growth.OPTIONS["one_feeder"])
    energy = change.get("energy", 1.0)
    models = tuple(
        with_changes(m, drive_kwh_per_mile=m.drive_kwh_per_mile * energy, always_on_kw=m.always_on_kw * energy)
        for m in fleet.models
    )
    fleet = with_changes(fleet, models=models, rides_per_vehicle_day=change.get("rides", fleet.rides_per_vehicle_day))
    depot = with_changes(depot, staff=int(depot.staff * change.get("people", 1.0)))
    demand = ReplayDemand.scaled(replay_curves(E8_DEV_START), size * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    rule = ThresholdRecall(recall_soc=change.get("recall_soc", 0.20))
    result = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand).run(E8_DAYS)
    # Scored like every other test on replayed days: the first week is warm-up, the second is measured.
    first, days = E8_WARMUP_DAYS * 1440.0, E8_DAYS - E8_WARMUP_DAYS
    summary = result.summary()
    return {
        "case": case,
        "size": size,
        "served": served_share(result.steps[result.steps[:, 0] >= first]),
        "kwh_per_mile": summary["kwh_per_vehicle_day"] / summary["miles_per_vehicle_day"],
        "visits_per_day": sum(1 for s in result.depot.sessions if s.visit.arrive_min >= first) / size / days,
    }


def sensitivity_study(workers: int = 5) -> Path:
    """How far do the site's capacity figures move when an uncertain input is moved within public figures?"""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E8_DEV_START)
    sizes, seeds = (600, 700, 800, 1000), (31, 32)
    jobs = [(case, size, seed) for case in SENSITIVITY_CASES for size in sizes for seed in seeds]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_sensitivity_run, jobs))
    rows = []
    for case in SENSITIVITY_CASES:
        row = {"case": case}
        for size in sizes:
            group = [r for r in runs if (r["case"], r["size"]) == (case, size)]
            row[f"served_{size}"] = round(float(np.mean([r["served"] for r in group])), 4)
        mine = [r for r in runs if r["case"] == case and r["size"] == 700]
        row["kwh_per_mile"] = round(float(np.mean([r["kwh_per_mile"] for r in mine])), 3)
        row["visits_per_day"] = round(float(np.mean([r["visits_per_day"] for r in mine])), 2)
        rows.append(row)
    return _write("sensitivity.json", {"start": E8_DEV_START, "rows": rows, "run": date.today().isoformat()})
