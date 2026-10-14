"""The account: E19, the sweet spot, and E20, a plan that follows an hourly price.

Each function corresponds to one entry in EVALS.md; the registration there fixes the data, the split, the
metric and the bar before the run it reports, and this module only executes it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from depot_twin.data import data_dir
from depot_twin.evals.common import E8_DAYS, E8_START, E8_WARMUP_DAYS, E9_LEDGER, E12_SETTINGS, _write, replay_curves

E19_FLEETS = (400, 500, 600, 700, 800, 1000, 1200)
E19_FEEDERS = {"one_feeder": 2750.0, "two_feeders": 5500.0}
E19_CHARGERS = (1.0, 1.5)
E19_CONTROLS = ("threshold", "plan_tariff", "plan_day_ahead")
E19_SEEDS = (1901, 1902)


def _e19_prices() -> dict:
    """The frozen fortnight's wholesale prices, as price curves from the run's first minute."""
    from datetime import date

    from depot_twin import finance
    from depot_twin.data import caiso_prices

    week = caiso_prices.fetch_week(date(2024, 4, 15), days=E8_DAYS)
    adder = finance.Assumptions().delivery_adder_usd_per_kwh
    return {
        "day_ahead": finance.wholesale_curve(week["day_ahead_usd_per_mwh"], 60, adder),
        "real_time": finance.wholesale_curve(week["real_time_usd_per_mwh"], 5, adder),
    }


def _e19_design(fleet: int, feeder: str, chargers: float):
    """Build a design: the second-version depot at a size and connection, with its charger count scaled."""
    from dataclasses import replace as with_changes

    from depot_twin import growth
    from depot_twin.resources import ChargerBank

    config, depot = growth.scaled_v2(fleet, site_limit_kw=E19_FEEDERS[feeder])
    count = int(round(growth.chargers_for(fleet) * chargers))
    return config, with_changes(depot, chargers=(ChargerBank("dc", count, 60.0),))


def _e19_binding(result, depot, skip_days: int) -> dict:
    """Shares of the scored steps in which each resource was the one that was short."""
    import numpy as np

    first = skip_days * 1440.0
    series = result.depot.series[result.depot.series[:, 0] >= first]
    steps = result.steps[result.steps[:, 0] >= first]
    at_limit = series[:, 1] >= 0.98 * depot.usable_kw
    queued = series[:, 4] > 0
    # Rides lost with no one waiting for a charger and the grid under its limit: the fleet itself was short.
    minute_of = {int(row[0]): k for k, row in enumerate(series)}
    short = []
    for row in steps:
        k = minute_of.get(int(row[0]))
        lost = row[1] - row[2] > 0.5
        short.append(bool(lost and k is not None and not queued[k] and not at_limit[k]))
    return {
        "grid_at_limit_share": round(float(at_limit.mean()), 4),
        "vehicles_waiting_share": round(float(queued.mean()), 4),
        "vehicles_short_share": round(float(np.mean(short)), 4),
    }


def _e19_run(job: tuple[int, str, float, str, int]) -> dict:
    """Run one design under one control on the frozen fortnight and return its account and what bound."""
    import numpy as np

    from depot_twin import finance
    from depot_twin.economics import Prices
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape
    from depot_twin.heartbeat import Heartbeat
    from depot_twin.replay import ReplayDemand
    from depot_twin.twin import EnergyIdentifier

    fleet_size, feeder, chargers, control, seed = job
    config, depot = _e19_design(fleet_size, feeder, chargers)
    demand = ReplayDemand.scaled(replay_curves(E8_START), fleet_size * config.rides_per_vehicle_day)
    wholesale = _e19_prices()
    if control == "threshold":
        rule = ThresholdRecall()
    else:
        rule = Heartbeat(**E9_LEDGER, prices=Prices(), **E12_SETTINGS)
        if control == "plan_day_ahead":
            rule.price_at = wholesale["day_ahead"]
        elif control == "plan_tariff_curve":
            rule.price_at = finance.tariff_curve(Prices())
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(config, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand)
    drive = np.array([m.drive_kwh_per_mile for m in config.models])[sim.model_of]
    load = np.array([m.always_on_kw for m in config.models])[sim.model_of]
    sim.telemetry = EnergyIdentifier(drive, load, sim.capacity, seed=seed)
    if control != "threshold":
        rule.energy = sim.telemetry
    result = sim.run(E8_DAYS)
    books = finance.account(result, depot, fleet_size, E8_DAYS, E8_WARMUP_DAYS, wholesale=wholesale)
    ledger = [e for e in getattr(rule, "ledger", []) if e["hour"] >= E8_WARMUP_DAYS * 24]
    return {
        "fleet": fleet_size,
        "feeder": feeder,
        "chargers": chargers,
        "control": control,
        "seed": seed,
        "promises_kept": float(np.mean([e["kept"] for e in ledger])) if ledger else None,
        "stranded": float(result.stranded),
        **books,
        **_e19_binding(result, depot, E8_WARMUP_DAYS),
    }


def _e19_rows(runs: list[dict]) -> list[dict]:
    """Average the seeds of each design and control into one row."""
    import numpy as np

    rows = []
    keys = [(f, fe, c, ctl) for f in E19_FLEETS for fe in E19_FEEDERS for c in E19_CHARGERS for ctl in E19_CONTROLS]
    for fleet, feeder, chargers, control in keys:
        group = [
            r
            for r in runs
            if (r["fleet"], r["feeder"], r["chargers"], r["control"]) == (fleet, feeder, chargers, control)
        ]
        row = {"fleet": fleet, "feeder": feeder, "chargers": chargers, "control": control}
        for name in group[0]:
            values = [r[name] for r in group]
            if isinstance(values[0], bool):
                row[name] = all(values)
            elif isinstance(values[0], (int, float, type(None))) and name not in row:
                # A seed with no figure (a payback that never comes) drops out of the mean; none left means none.
                known = [v for v in values if v is not None]
                row[name] = round(float(np.mean(known)), 4) if known else None
            elif isinstance(values[0], dict):
                row[name] = {k: round(float(np.mean([v[k] for v in values])), 2) for k in values[0]}
        rows.append(row)
    return rows


def _e19_meets(row: dict) -> bool:
    return row["meets_service"] and (row["control"] == "threshold" or (row["promises_kept"] or 0.0) >= 0.95)


def _e19_bars(rows: list[dict]) -> dict:
    one = [r for r in rows if r["feeder"] == "one_feeder"]
    good = [r for r in one if _e19_meets(r)]
    best = max(good, key=lambda r: r["contribution_per_day"]) if good else None
    above = [
        r
        for r in one
        if best and r["control"] == best["control"] and r["chargers"] == best["chargers"] and r["fleet"] > best["fleet"]
    ]
    pairs = [
        (t, p)
        for t in rows
        if t["control"] == "threshold" and _e19_meets(t)
        for p in rows
        if p["control"] == "plan_tariff"
        and (p["fleet"], p["feeder"], p["chargers"]) == (t["fleet"], t["feeder"], t["chargers"])
        and _e19_meets(p)
    ]
    plain = [r for r in one if r["control"] == "threshold" and r["chargers"] == 1.0]
    failing = [r for r in plain if not r["meets_service"]]
    passing = [r for r in plain if r["meets_service"]]
    at500 = {r["control"]: r for r in one if r["fleet"] == 500 and r["chargers"] == 1.0}
    return {
        "1_sweet_spot_inside_the_range_on_one_feeder": bool(
            best
            and best["fleet"] < 1200
            and above
            and all(r["contribution_per_day"] < best["contribution_per_day"] for r in above)
        ),
        "2_plan_beats_threshold_wherever_both_meet_service": bool(pairs)
        and all(p["contribution_per_day"] > t["contribution_per_day"] for t, p in pairs),
        "3_grid_binds_where_service_breaks_on_one_feeder": bool(failing and passing)
        and min(failing, key=lambda r: r["fleet"])["grid_at_limit_share"] > 0.5
        and max(passing, key=lambda r: r["fleet"])["grid_at_limit_share"] < 0.2,
        "4_plan_on_day_ahead_prices_buys_10pct_cheaper_under_that_scenario_at_500": (
            at500["plan_day_ahead"]["energy_cost_per_kwh_day_ahead"]
            <= 0.9 * at500["plan_tariff"]["energy_cost_per_kwh_day_ahead"]
            and abs(at500["plan_day_ahead"]["rides_served_share"] - at500["plan_tariff"]["rides_served_share"]) <= 0.002
        ),
    }


def e19_sweet_spot(workers: int = 5) -> Path:
    """E19: the design that earns most at the required service on the frozen fortnight, and what binds around it."""
    from concurrent.futures import ProcessPoolExecutor

    from depot_twin import finance

    replay_curves(E8_START)
    _e19_prices()
    jobs = [
        (f, fe, c, ctl, s)
        for f in E19_FLEETS
        for fe in E19_FEEDERS
        for c in E19_CHARGERS
        for ctl in E19_CONTROLS
        for s in E19_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e19_run, jobs))
    rows = _e19_rows(runs)
    return _write(
        "e19_sweet_spot.json",
        {
            "eval": "E19",
            "window": "sf_e8",
            "assumptions": finance.Assumptions().describe(),
            "rows": rows,
            "bars": _e19_bars(rows),
            "run": date.today().isoformat(),
        },
    )


E20_SEEDS = (2001, 2002, 2003)
E20_CONTROLS = ("plan_tariff", "plan_day_ahead", "plan_tariff_curve")


def e20_price_steering(workers: int = 5) -> Path:
    """E20: can the plan follow an hourly price? The steering rewritten to find the dearest quarter of the day."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    replay_curves(E8_START)
    _e19_prices()
    jobs = [(500, "one_feeder", 1.0, control, seed) for control in E20_CONTROLS for seed in E20_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e19_run, jobs))
    table = {}
    for control in E20_CONTROLS:
        group = [r for r in runs if r["control"] == control]
        keys = (
            "rides_served_share",
            "promises_kept",
            "energy_cost_per_kwh_tariff",
            "energy_cost_per_kwh_day_ahead",
            "contribution_per_day",
            "contribution_per_day_day_ahead",
        )
        table[control] = {k: round(float(np.mean([r[k] for r in group])), 4) for k in keys}
    tariff, day_ahead, curve = table["plan_tariff"], table["plan_day_ahead"], table["plan_tariff_curve"]
    bars = {
        "1_day_ahead_steering_buys_10pct_cheaper_under_day_ahead_prices_rides_within_0.2": (
            day_ahead["energy_cost_per_kwh_day_ahead"] <= 0.9 * tariff["energy_cost_per_kwh_day_ahead"]
            and abs(day_ahead["rides_served_share"] - tariff["rides_served_share"]) <= 0.002
        ),
        "2_tariff_as_a_curve_matches_the_tariff_path": (
            abs(curve["energy_cost_per_kwh_tariff"] / tariff["energy_cost_per_kwh_tariff"] - 1.0) <= 0.02
            and abs(curve["rides_served_share"] - tariff["rides_served_share"]) <= 0.002
        ),
        "3_promises_kept_95pct_in_every_arm": all(table[c]["promises_kept"] >= 0.95 for c in E20_CONTROLS),
    }
    return _write(
        "e20_price_steering.json",
        {"eval": "E20", "window": "sf_e8", "table": table, "bars": bars, "run": date.today().isoformat()},
    )
