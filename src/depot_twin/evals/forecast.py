"""The forecasts: E7 and E7b, E13 and E15 for a site with no history, the first-hour study, and the forecast chapter E16 to E18.

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
    E8_SIZES,
    E8_START,
    E8_WARMUP_DAYS,
    E9_LEDGER,
    E9_START,
    _e8_rule,
    _sf_counts,
    _sf_counts_cached,
    _sf_describe,
    _weather_frame,
    _write,
    replay_curves,
)
from depot_twin.evals.control import E14_START, e8_run, e12_run
from depot_twin.fleet import served_share


def _e7_bars(report: dict) -> dict:
    bars = {}
    for horizon, result in report.items():
        bars[f"{horizon}_1_removes_15pct_of_best_baseline_error"] = result["error_removed"] >= 0.15
        bars[f"{horizon}_2_upper_bound_holds_93_to_97pct"] = 0.93 <= result["upper_95_coverage"] <= 0.97
        bars[f"{horizon}_3_not_low_by_more_than_3pct_at_peak"] = result["peak_signed_error"] >= -0.03
    return bars


def e7_forecasts() -> Path:
    """E7: forecasts at 1, 6 and 24 hours on San Francisco taxi rides, with calibrated bounds."""
    import pandas as pd

    from depot_twin.data import chicago
    from depot_twin.models import short_horizon

    counts, rides = _sf_counts()
    _sf_describe(counts, rides)
    forecasts, report = short_horizon.run(
        counts, 12, _weather_frame("san_francisco", counts.index.min(), counts.index.max())
    )
    for horizon, forecast in forecasts.items():
        forecast.model.save_model(str(data_dir() / "derived" / f"forecast_{horizon}h.json"))
    bounds = {
        f"{h}h": {"upper_95": f.upper_95, "lower_05": f.lower_05, "features": f.features} for h, f in forecasts.items()
    }
    _write("forecast_bounds.json", bounds)

    # The same pipeline on another city, at hourly steps. Reported, not held to a bar.
    rows = chicago.fetch_hours(last=date(2026, 8, 31))
    frame = pd.DataFrame(rows)
    times = pd.to_datetime(frame["day"]) + pd.to_timedelta(frame["hour"], unit="h")
    city = pd.Series(frame["trips"].to_numpy(), index=times).resample("h").sum().astype(float)
    _, second_city = short_horizon.run(city, 1, _weather_frame("chicago", city.index.min(), city.index.max()))
    return _write(
        "e7_forecasts.json",
        {
            "eval": "E7",
            "san_francisco": report,
            "chicago": {
                h: {
                    k: r[k]
                    for k in (
                        "model_wape",
                        "baseline",
                        "baseline_wape",
                        "error_removed",
                        "upper_95_coverage",
                        "peak_signed_error",
                    )
                }
                for h, r in second_city.items()
            },
            "bars": _e7_bars(report),
            "run": date.today().isoformat(),
        },
    )


def e7b_scale_free() -> Path:
    """E7b: E7 again with the ratio to last week as the target, to test why E7 failed."""
    from depot_twin.models import short_horizon

    counts, _ = _sf_counts()
    weather = _weather_frame("san_francisco", counts.index.min(), counts.index.max())
    forecasts, report = short_horizon.run(counts, 12, weather, scale_free=True)
    for horizon, forecast in forecasts.items():
        forecast.model.save_model(str(data_dir() / "derived" / f"forecast_ratio_{horizon}h.json"))
    bounds = {
        f"{h}h": {"upper_95": f.upper_95, "lower_05": f.lower_05, "features": f.features} for h, f in forecasts.items()
    }
    _write("forecast_ratio_bounds.json", bounds)
    return _write(
        "e7b_scale_free.json",
        {"eval": "E7b", "san_francisco": report, "bars": _e7_bars(report), "run": date.today().isoformat()},
    )


E13_HORIZONS = (1, 6, 24)
E13_SCENARIOS, E13_SEEDS, E13_SIZES = 10, (501, 502, 503), (500, 1000)
E13_TARGETS = ("nyc_ridehail_city", "chicago_ridehail_city", "sf_taxi_city")
E13_REAL_START = "2024-04-15"
E13_DEPOT_SCALE = 500.0  # rides an hour: about what a 500-vehicle fleet is offered


def _e13_cell(job: tuple[str, int, bool, float | None]) -> dict:
    """Score every arm for one held-out city at one horizon, at its own size or thinned to a depot's."""
    from depot_twin import newsite

    name, horizon, development, rides_per_hour = job
    sources = newsite.Sources.load()
    target = next(d for d in sources.donors if d.name == name)
    return newsite.leave_city_out(sources, target, horizon, development, rides_per_hour)


def _e13_demand(scenario: int | None):
    """Return two weeks of five-minute demand for San Francisco: real days, or generated without them."""
    import numpy as np
    import pandas as pd

    from depot_twin import newsite, replay, synth

    start = pd.Timestamp(E13_REAL_START)
    if scenario is None:
        counts = _sf_counts_cached()
        return replay.plain_curves(counts[start : start + pd.Timedelta(days=E8_DAYS) - pd.Timedelta(minutes=5)])
    sources = newsite.Sources.load()
    target = next(d for d in sources.donors if d.name == "sf_taxi_city")
    held_from = sources.series(target.name).index.max() - pd.Timedelta(days=newsite.TEST_DAYS)
    profiles = sources.profiles(newsite.eligible(sources.donors, "city", target.city), held_from)
    rng = np.random.default_rng(1300 + scenario)
    hourly = synth.generate(profiles, start, E8_DAYS // 7, 1000.0, rng, sources.weather[target.weather])
    return replay.plain_curves(synth.five_minute(hourly, rng))


def _e13_depot(job: tuple[int | None, int, int]) -> dict:
    """Run the depot on real or generated demand and return the share of rides served."""
    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.replay import ReplayDemand

    scenario, size, seed = job
    fleet, depot = load_fleet_scenario(f"scenarios/v2/east_oakland_{size}.toml")
    demand = ReplayDemand.scaled(_e13_demand(scenario), size * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(fleet, depot, shape, _e8_rule("threshold"), depot_policy="slot_power", seed=seed, demand=demand)
    steps = sim.run(E8_DAYS).steps
    steps = steps[steps[:, 0] >= E8_WARMUP_DAYS * 1440.0]
    return {"scenario": scenario, "size": size, "served": served_share(steps)}


def _e13_bars(cells: list[dict], depot: dict) -> dict:
    arm = "donors_and_generated"
    return {
        "beats_best_naive_in_all_9": all(c[arm]["wape"] < c["best_naive"] for c in cells),
        "within_1.25x_in_city_in_7_of_9": sum(c[arm]["wape"] <= 1.25 * c["in_city"] for c in cells) >= 7,
        "upper_bound_holds_90_to_99_in_all_9": all(0.90 <= c[arm]["upper_coverage"] <= 0.99 for c in cells),
        "depot_within_1.5_points": all(abs(row["generated"] - row["real"]) <= 0.015 for row in depot.values()),
    }


def e13_new_site(workers: int = 5, development: bool = False) -> Path:
    """E13: can a forecast be built for a place with no ride history? Each city is held out in turn."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    from depot_twin import newsite

    newsite.Sources.load()  # build the panel and fetch weather once, before the workers start
    jobs = [(name, horizon, development, None) for name in E13_TARGETS for horizon in E13_HORIZONS]
    # San Francisco's taxis are already at a depot's scale; the two large cities are also scored thinned to it.
    jobs += [(name, horizon, development, E13_DEPOT_SCALE) for name in E13_TARGETS[:2] for horizon in E13_HORIZONS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        scored = list(pool.map(_e13_cell, jobs))
    cells = [c for c in scored if c["rides_per_hour"] is None]
    at_depot_scale = [c for c in scored if c["rides_per_hour"] is not None]
    if development:
        return _write("e13_development.json", {"cells": cells, "run": date.today().isoformat()})
    runs = [
        (scenario, size, seed) for scenario in (None, *range(E13_SCENARIOS)) for size in E13_SIZES for seed in E13_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=2 * workers) as pool:
        served = list(pool.map(_e13_depot, runs))
    depot = {}
    for size in E13_SIZES:
        real = [r["served"] for r in served if r["size"] == size and r["scenario"] is None]
        made = [r["served"] for r in served if r["size"] == size and r["scenario"] is not None]
        by_scenario = [
            np.mean([r["served"] for r in served if r["size"] == size and r["scenario"] == k])
            for k in range(E13_SCENARIOS)
        ]
        depot[str(size)] = {
            "real": round(float(np.mean(real)), 4),
            "generated": round(float(np.mean(made)), 4),
            "generated_low": round(float(min(by_scenario)), 4),
            "generated_high": round(float(max(by_scenario)), 4),
        }
    worst = max(cells, key=lambda c: c["donors_and_generated"]["wape"] / c["best_naive"])
    return _write(
        "e13_new_site.json",
        {
            "eval": "E13",
            "cells": cells,
            "at_depot_scale": at_depot_scale,
            "depot": depot,
            "worst_cell": {"city": worst["city"], "horizon": worst["horizon"], **worst["donors_and_generated"]},
            "bars": _e13_bars(cells, depot),
            "run": date.today().isoformat(),
        },
    )


E15_TARGETS = ("chicago_ridehail_city", "nyc_ridehail_city")
E15_SEEDS = (701, 702, 703)
E15_MARGIN = 0.005


def _fortnight(name: str, scenario: int | None) -> dict:
    """Return a fortnight of five-minute demand for a city from E14's start: its real days, or generated without it."""
    import numpy as np
    import pandas as pd

    from depot_twin import newsite, replay, synth

    sources = newsite.Sources.load()
    target = next(d for d in sources.donors if d.name == name)
    start = pd.Timestamp(E14_START)
    if scenario is None:
        real = sources.series(name)[start : start + pd.Timedelta(days=E8_DAYS) - pd.Timedelta(hours=1)]
        hourly = newsite.thinned(real, 1000.0, seed=14)
        return replay.plain_curves(synth.five_minute(hourly, np.random.default_rng(15)))
    profiles = sources.profiles(newsite.eligible(sources.donors, "city", target.city), start)
    rng = np.random.default_rng(1500 + scenario)
    hourly = synth.generate(profiles, start, E8_DAYS // 7, 1000.0, rng, sources.weather[target.weather])
    return replay.plain_curves(synth.five_minute(hourly, rng))


def _e15_run(job: tuple[str, int | None, int]) -> dict:
    """Run 1,000 vehicles on one feeder on a city's real or generated fortnight; return rides served."""
    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.replay import ReplayDemand

    name, scenario, seed = job
    fleet, depot = load_fleet_scenario("scenarios/v2/east_oakland_1000.toml")
    demand = ReplayDemand.scaled(_fortnight(name, scenario), fleet.size * fleet.rides_per_vehicle_day)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(fleet, depot, shape, _e8_rule("threshold"), depot_policy="slot_power", seed=seed, demand=demand)
    steps = sim.run(E8_DAYS).steps
    steps = steps[steps[:, 0] >= E8_WARMUP_DAYS * 1440.0]
    return {"name": name, "scenario": scenario, "served": served_share(steps)}


def e15_worst_scenario(workers: int = 5) -> Path:
    """E15: is the worst of ten generated scenarios a safe reading of a constrained depot's capacity?"""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    from depot_twin import newsite

    newsite.Sources.load()
    jobs = [
        (name, scenario, seed)
        for name in E15_TARGETS
        for scenario in (None, *range(E13_SCENARIOS))
        for seed in E15_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e15_run, jobs))
    table, bars = {}, {}
    for name in E15_TARGETS:

        def mean(scenario, name=name):
            return float(np.mean([r["served"] for r in runs if r["name"] == name and r["scenario"] == scenario]))

        made = [mean(k) for k in range(E13_SCENARIOS)]
        table[name] = {
            "real": round(mean(None), 4),
            "generated_mean": round(float(np.mean(made)), 4),
            "generated_worst": round(min(made), 4),
            "generated_best": round(max(made), 4),
        }
        bars[f"{name}_real_no_worse_than_worst_scenario_less_half_a_point"] = mean(None) >= min(made) - E15_MARGIN
    return _write(
        "e15_worst_scenario.json", {"eval": "E15", "table": table, "bars": bars, "run": date.today().isoformat()}
    )


FIRST_HOUR_WINDOWS = (E8_DEV_START, E8_START, "2024-04-29", E9_START)
FIRST_HOUR_SEEDS = (801, 802, 803)


def _first_hour_quality() -> dict:
    """Score the forecast of the hour under way, both ways, over every replay window."""
    import numpy as np

    from depot_twin.replay import STEPS_PER_HOUR

    out = {}
    for name, prefix in (("interpolated", ""), ("own_model", "now:")):
        actual, mean, upper = [], [], []
        for start in FIRST_HOUR_WINDOWS:
            curves = replay_curves(prefix + start)
            hours = np.arange(0, E8_DAYS * 24 - 1) * STEPS_PER_HOUR
            actual.append(curves["actual"][hours, 0])
            mean.append(curves["mean"][hours, 0])
            upper.append(curves["upper"][hours, 0])
        actual, mean, upper = (np.concatenate(part) for part in (actual, mean, upper))
        out[name] = {
            "error": round(float(np.abs(actual - mean).sum() / actual.sum()), 4),
            "upper_bound_held": round(float((actual <= upper).mean()), 4),
        }
    return out


def _first_hour_run(job: tuple[str, str, int, int]) -> dict:
    """Run the plan, plain or with prices, on one forecast of the first hour."""
    forecast, arm, size, seed = job
    prefix = "now:" if forecast == "own_model" else ""
    if arm == "plan":
        scores = e8_run(("heartbeat", size, seed, prefix + E9_START), E9_LEDGER)
        keep = ("served", "stranded", "ledger_kept", "ledger_promised_share", "grid_variation")
    else:
        scores = e12_run(("plan_with_prices", size, seed, prefix + "2024-04-29"))
        keep = ("served", "stranded", "cost_per_kwh", "fares_less_energy_per_vehicle_day")
    return {"forecast": forecast, "arm": arm, "size": size, **{key: scores[key] for key in keep}}


def first_hour_study(workers: int = 5) -> Path:
    """Does the plan do better when the hour under way has a forecast of its own?"""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    quality = _first_hour_quality()  # also builds and stores every window's curves before the workers start
    jobs = [
        (forecast, arm, size, seed)
        for forecast in ("interpolated", "own_model")
        for arm in ("plan", "plan_with_prices")
        for size in E8_SIZES
        for seed in FIRST_HOUR_SEEDS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_first_hour_run, jobs))
    table = {}
    for forecast, arm, size, _ in jobs:
        group = [r for r in runs if (r["forecast"], r["arm"], r["size"]) == (forecast, arm, size)]
        keys = [key for key in group[0] if key not in ("forecast", "arm", "size")]
        table[f"{arm}_{size}_{forecast}"] = {key: round(float(np.mean([r[key] for r in group])), 4) for key in keys}
    return _write("first_hour.json", {"forecast": quality, "table": table, "run": date.today().isoformat()})


E16_ARMS = ("perfect_foresight", "model", "last_week", "broken_feed")
E16_REGIMES = {"slack": (500, 25.0), "edge": (700, 25.0), "energy_bound": (1000, 25.0), "vehicles_bound": (500, 32.0)}
E16_SEEDS = (1001, 1002, 1003)


def _e16_curves(arm: str) -> dict:
    """Return the replay curves an arm feeds the plan, on the sf_e8 window."""
    import numpy as np
    import pandas as pd

    from depot_twin import replay, workbench

    if arm == "perfect_foresight":
        counts = _sf_counts_cached()
        start = pd.Timestamp(workbench.START)
        return replay.plain_curves(counts[start : start + pd.Timedelta(days=E8_DAYS) - pd.Timedelta(minutes=5)])
    source = "last_week" if arm == "last_week" else "reference"
    return dict(np.load(data_dir() / "derived" / "workbench" / f"{source}.npz"))


def _e16_run(job: tuple[str, str, int]) -> dict:
    """Run the price-aware plan on one arm's forecasts in one regime and score the second week."""
    from dataclasses import replace as with_changes

    import numpy as np

    from depot_twin import growth, workbench
    from depot_twin.fleet import FleetSim, load_weekly_shape
    from depot_twin.replay import ReplayDemand
    from depot_twin.twin import EnergyIdentifier

    arm, regime, seed = job
    size, rides = E16_REGIMES[regime]
    fleet, depot = growth.scaled_v2(size, **growth.OPTIONS["one_feeder"])
    fleet = with_changes(fleet, rides_per_vehicle_day=rides)
    demand = ReplayDemand.scaled(_e16_curves(arm), size * rides)
    first = E8_WARMUP_DAYS * 1440.0
    if arm == "broken_feed":
        demand = with_changes(demand, fault_from_minute=first, fault_factor=workbench.FAULT_FACTOR)
    rule = workbench._rule(workbench.VARIANTS[0])
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand)
    drive = np.array([m.drive_kwh_per_mile for m in fleet.models])[sim.model_of]
    load = np.array([m.always_on_kw for m in fleet.models])[sim.model_of]
    sim.telemetry = EnergyIdentifier(drive, load, sim.capacity, seed=seed)
    rule.energy = sim.telemetry
    result = sim.run(E8_DAYS)
    factor = workbench.FAULT_FACTOR if arm == "broken_feed" else 1.0
    return {"arm": arm, "regime": regime, **_e16_scores(result, rule, demand, fleet, size, factor)}


def _e16_scores(result, rule, demand, fleet, size: int, factor: float) -> dict:
    """Score the second week of a plan's run: rides, money, promises, the reserve its bound asked for."""
    import numpy as np

    from depot_twin.economics import Prices, energy_by_period
    from depot_twin.replay import STEPS_PER_HOUR

    first = E8_WARMUP_DAYS * 1440.0
    steps = result.steps[result.steps[:, 0] >= first]
    series = result.depot.series[result.depot.series[:, 0] >= first]
    prices, energy = Prices(), energy_by_period(result.depot.series, skip_days=E8_WARMUP_DAYS)
    cost = energy["peak"] * prices.energy_peak + energy["off_peak"] * prices.energy_off_peak
    cost += energy["super_off_peak"] * prices.energy_super_off_peak
    days = E8_DAYS - E8_WARMUP_DAYS
    ledger = [e for e in rule.ledger if e["hour"] >= E8_WARMUP_DAYS * 24]
    hours = np.arange(E8_WARMUP_DAYS * 24, E8_DAYS * 24 - 2) * STEPS_PER_HOUR
    held = np.clip(demand.upper[hours, 1] * factor - demand.actual[hours, 1], 0, None)
    return {
        "served": served_share(steps),
        "fares_less_energy_per_vehicle_day": (float(steps[:, 2].sum()) * prices.revenue_per_ride - cost) / size / days,
        "cost_per_kwh": cost / sum(energy.values()),
        "promises_kept": float(np.mean([e["kept"] for e in ledger])) if ledger else 1.0,
        "reserve_vehicles": float(held.mean() / (60.0 / fleet.ride_minutes)),
        "peak_grid_kw": float(series[:, 1].max()),
        "stranded": float(result.stranded),
    }


def e16_regret(workers: int = 5) -> Path:
    """E16: what a forecast is worth to the plan, by regime: perfect foresight against model, naive and broken."""
    from concurrent.futures import ProcessPoolExecutor

    import numpy as np

    jobs = [(arm, regime, seed) for arm in E16_ARMS for regime in E16_REGIMES for seed in E16_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e16_run, jobs))
    table = {}
    for arm in E16_ARMS:
        for regime in E16_REGIMES:
            group = [r for r in runs if (r["arm"], r["regime"]) == (arm, regime)]
            keys = [k for k in group[0] if k not in ("arm", "regime")]
            table[f"{arm}_{regime}"] = {k: round(float(np.mean([r[k] for r in group])), 4) for k in keys}
    served = lambda arm, regime: table[f"{arm}_{regime}"]["served"]  # noqa: E731
    money = lambda arm, regime: table[f"{arm}_{regime}"]["fares_less_energy_per_vehicle_day"]  # noqa: E731
    gain_oracle = served("perfect_foresight", "vehicles_bound") - served("last_week", "vehicles_bound")
    gain_model = served("model", "vehicles_bound") - served("last_week", "vehicles_bound")
    bars = {
        "1_energy_bound_rides_within_half_a_point_across_arms": (
            max(served(a, "energy_bound") for a in E16_ARMS) - min(served(a, "energy_bound") for a in E16_ARMS) < 0.005
        ),
        "2_vehicles_bound_foresight_worth_1_point_and_model_recovers_half": gain_oracle >= 0.01
        and gain_model >= 0.5 * gain_oracle,
        "3_model_money_regret_at_most_2pct_everywhere": all(
            money("model", r) >= 0.98 * money("perfect_foresight", r) for r in E16_REGIMES
        ),
        "4_broken_feed_hurts_more_where_vehicles_bind": (
            served("perfect_foresight", "vehicles_bound") - served("broken_feed", "vehicles_bound")
            > served("perfect_foresight", "energy_bound") - served("broken_feed", "energy_bound")
        ),
    }
    return _write(
        "e16_regret.json",
        {"eval": "E16", "window": "sf_e8", "table": table, "bars": bars, "run": date.today().isoformat()},
    )


E17_CITIES = {"chicago": ("chicago_ridehail_city", "chicago"), "new_york": ("nyc_ridehail_city", "new_york")}
E17_WINDOW = ("2026-01-05", "2026-03-02")  # the reserved windows, scored once; the end is exclusive
E17_DEPOT_SCALE = 500.0
# A city is thinned to a depot's scale by keeping each ride at random, and one draw of that thinning can
# decide a close comparison. Every figure is the mean over these draws, and the draws that agree are counted.
E17_SEEDS = (17, 18, 19, 20, 21, 22)
E18_SEEDS = (18, 19, 20)


def _mean_over_seeds(cells: list[dict]) -> dict:
    """Average what several draws of one cell measured: numbers, lists of numbers, and dicts of either."""
    import numpy as np

    first = cells[0]
    out = {}
    for key, value in first.items():
        values = [cell[key] for cell in cells]
        if isinstance(value, dict):
            out[key] = _mean_over_seeds(values)
        elif isinstance(value, bool) or value is None or isinstance(value, str):
            out[key] = value if all(v == value for v in values) else None
        elif isinstance(value, (int, float)):
            out[key] = round(float(np.mean(values)), 4) if all(v is not None for v in values) else None
        elif isinstance(value, list) and value and isinstance(value[0], (int, float)):
            out[key] = [float(x) for x in np.mean(np.array(values, dtype=float), axis=0)]
        else:
            out[key] = value
    return out


def _e17_city(job: tuple[str, int]) -> dict:
    """Fit every recipe on one city's history before the reserved window and score it on the window."""
    import pandas as pd

    from depot_twin import newsite
    from depot_twin.models import lab

    city, horizon, seed = job
    name, place = E17_CITIES[city]
    sources = newsite.Sources.load()
    counts = newsite.thinned(sources.series(name), E17_DEPOT_SCALE, seed=seed)
    scores = lab.run_city(
        counts,
        sources.weather[place],
        horizons=(horizon,),
        test_from=pd.Timestamp(E17_WINDOW[0]),
        until=pd.Timestamp(E17_WINDOW[1]),
    )
    return {"city": city, "horizon": horizon, "seed": seed, "scores": scores}


def e17_fixes(workers: int = 4) -> Path:
    """E17: the model fixes, confirmed once on the reserved Chicago and New York windows."""
    from concurrent.futures import ProcessPoolExecutor

    from depot_twin import newsite
    from depot_twin.models import lab

    newsite.Sources.load()
    jobs = [(city, horizon, seed) for city in E17_CITIES for horizon in (1, 6, 24) for seed in E17_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e17_city, jobs))
    table = {}
    for city in E17_CITIES:
        for horizon in (1, 6, 24):
            draws = [run["scores"] for run in runs if run["city"] == city and run["horizon"] == horizon]
            mean = _mean_over_seeds(draws)
            reference = mean[f"reference_{horizon}h"]
            for key, score in mean.items():
                row = {k: v for k, v in score.items() if k != "daily_error"}
                row["against_reference"] = lab.paired_interval(score["daily_error"], reference["daily_error"])
                row["draws_with_lower_error_than_reference"] = sum(
                    draw[key]["error"] < draw[f"reference_{horizon}h"]["error"] for draw in draws
                )
                table[f"{city}_{key}"] = row
    one = lambda city, arm, h=1: table[f"{city}_{arm}_{h}h"]  # noqa: E731
    bars = {
        "1_all_fixes_lower_error_1h_both_cities_interval_excludes_zero": all(
            one(c, "all")["error"] < one(c, "reference")["error"] and one(c, "all")["against_reference"]["high"] < 0
            for c in E17_CITIES
        ),
        "2_all_fixes_coverage_93_to_97_both_cities": all(
            0.93 <= one(c, "all")["upper_bound_held"] <= 0.97 for c in E17_CITIES
        ),
        "3_all_fixes_fewer_reserve_vehicles_at_no_lower_coverage_both_cities": all(
            one(c, "all")["reserve_vehicles"] < one(c, "reference")["reserve_vehicles"]
            and one(c, "all")["upper_bound_held"] >= one(c, "reference")["upper_bound_held"] - 1e-9
            for c in E17_CITIES
        ),
        "4_all_fixes_lower_error_at_6h_and_24h_both_cities": all(
            one(c, "all", h)["error"] < one(c, "reference", h)["error"] for c in E17_CITIES for h in (6, 24)
        ),
    }
    return _write(
        "e17_fixes.json",
        {
            "eval": "E17",
            "window": E17_WINDOW,
            "seeds": list(E17_SEEDS),
            "table": table,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


E18_SERIES = {
    "chicago": ("chicago_ridehail_city", "chicago", "exploratory, a second look at the E17 window"),
    "nyc_ridehail": ("nyc_ridehail_city", "new_york", "exploratory, a second look at the E17 window"),
    "nyc_yellow": ("nyc_yellow_city", "new_york", "confirmation, scored once"),
}
E18_ARMS = ("A_reference_bound", "B_calibration_only", "C_chronos", "D_ensemble", "last_week")


def _e18_series(key: str) -> dict:
    """One series over every thinning draw: each figure the mean of the draws, the frontier from the first."""
    draws = [_e18_draw(key, seed) for seed in E18_SEEDS]
    mean = _mean_over_seeds(draws)
    for name, value in draws[0].items():
        if isinstance(value, dict) and "frontier" in value:
            mean[name]["frontier"] = value["frontier"]
            reached = [d[name]["reserve_at_95_achieved"] for d in draws]
            mean[name]["draws_reaching_95"] = sum(r is not None for r in reached)
    return {**mean, "seeds": list(E18_SEEDS)}


def _e18_draw(key: str, seed: int) -> dict:
    """Every arm's frontier on one series, at each horizon: the point forecasts, then the bounds."""
    import pandas as pd

    from depot_twin import newsite
    from depot_twin.models import lab, reserve

    name, place, _ = E18_SERIES[key]
    sources = newsite.Sources.load()
    counts = newsite.thinned(sources.series(name), E17_DEPOT_SCALE, seed=seed)
    test_from, until = pd.Timestamp(E17_WINDOW[0]), pd.Timestamp(E17_WINDOW[1])
    first_origin = test_from - pd.Timedelta(days=short_horizon_calibration_days() + 1)
    origins = counts.index[(counts.index >= first_origin) & (counts.index < until)]
    chronos = reserve.chronos_points(counts, origins)
    out = {}
    for horizon in (1, 6, 24):
        rows = lab.frame(counts, horizon, sources.weather[place]).dropna(
            subset=["label", "rate_7d_ago", "rate_mean_24h", "slot_four_weeks", "level"]
        )
        parts = lab.cut_before(rows, horizon, test_from, until)
        calib, held = parts["calibrate"], parts["holdout"]
        fitted = lab.fit(lab.RECIPES[0], parts, horizon)
        points = {
            "reference": (fitted.predict(calib), fitted.predict(held)),
            "chronos": (chronos.loc[calib.index, horizon].to_numpy(), chronos.loc[held.index, horizon].to_numpy()),
            "last_week": (calib["target_slot_last_week"].to_numpy(), held["target_slot_last_week"].to_numpy()),
        }
        points["ensemble"] = tuple((a + b) / 2.0 for a, b in zip(points["reference"], points["chronos"], strict=True))
        actual_c, actual = calib["label"].to_numpy(), held["label"].to_numpy()
        scale = reserve._scale(actual, 500, 25.0)
        arms = {
            "A_reference_bound": ("reference", "symmetric"),
            "B_calibration_only": ("reference", "volume"),
            "C_chronos": ("chronos", "volume"),
            "D_ensemble": ("ensemble", "volume"),
            "last_week": ("last_week", "volume"),
        }
        for arm, (point, kind) in arms.items():
            pc, pt = points[point]
            curve = reserve.frontier(actual_c, pc, actual, pt, kind, scale)
            out[f"{arm}_{horizon}h"] = {
                "point": point,
                "bound": kind,
                "error": round(lab.wape(actual, pt), 4),
                "frontier": curve,
                "reserve_at_95_achieved": reserve.reserve_at(curve, 0.95),
                "achieved_at_nominal_95": next(p["achieved"] for p in curve if p["nominal"] == 0.95),
                "reserve_at_nominal_95": next(p["reserve"] for p in curve if p["nominal"] == 0.95),
            }
        out[f"same_hour_last_week_{horizon}h_error"] = round(lab.wape(actual, points["last_week"][1]), 4)
    return {"series": key, "note": E18_SERIES[key][2], **out}


def short_horizon_calibration_days() -> int:
    """How many days the calibration block has, from the forecast module, so the two cannot drift apart."""
    from depot_twin.models import short_horizon

    return short_horizon.CALIBRATION_DAYS


def e18_reserve() -> Path:
    """E18: at a required reliability, which forecasting architecture asks the fleet to hold the fewest vehicles?"""
    from depot_twin.models import reserve

    results = {key: _e18_series(key) for key in E18_SERIES}
    yellow = results["nyc_yellow"]
    at = lambda arm: yellow[f"{arm}_1h"]  # noqa: E731
    best_pretrained = min(
        (
            v
            for v in (at("C_chronos")["reserve_at_95_achieved"], at("D_ensemble")["reserve_at_95_achieved"])
            if v is not None
        ),
        default=None,
    )
    b_reserve = at("B_calibration_only")["reserve_at_95_achieved"]
    a_reserve = at("A_reference_bound")["reserve_at_95_achieved"]
    bars = {
        "1_B_holds_fewer_vehicles_than_A_at_95_achieved": a_reserve is not None
        and b_reserve is not None
        and b_reserve < a_reserve,
        "2_best_of_C_D_within_one_vehicle_of_B_or_fewer": best_pretrained is not None
        and b_reserve is not None
        and best_pretrained <= b_reserve + 1.0,
        "3_some_arm_reaches_95_within_one_point_at_nominal_95": any(
            abs(at(arm)["achieved_at_nominal_95"] - 0.95) <= 0.01 for arm in E18_ARMS[:4]
        ),
    }
    reported = {
        "any_arm_beats_B_by_more_than_two_vehicles": any(
            at(arm)["reserve_at_95_achieved"] is not None
            and b_reserve is not None
            and at(arm)["reserve_at_95_achieved"] < b_reserve - 2.0
            for arm in ("C_chronos", "D_ensemble")
        )
    }
    return _write(
        "e18_reserve.json",
        {
            "eval": "E18",
            "window": E17_WINDOW,
            "versions": reserve.pinned_versions(),
            "series": results,
            "bars": bars,
            "reported": reported,
            "run": date.today().isoformat(),
        },
    )
