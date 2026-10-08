"""Shared by the registered evaluations: the result writer, the San Francisco series and weather, the replay curves, and the settings E8, E9 and E12 fixed that later tests reuse.

Each function corresponds to one entry in EVALS.md; the registration there fixes the data, the split, the
metric and the bar before the run it reports, and this module only executes it.
"""

from __future__ import annotations

import json
from pathlib import Path

from depot_twin.data import data_dir
from depot_twin.fleet import served_share


def _write(name: str, payload: dict) -> Path:
    """Write one evaluation's record under data/derived, stamped with the code it ran on, and return its path."""
    from depot_twin import provenance

    target = data_dir() / "derived" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if name in provenance.RECORDS:
        payload = {**payload, "code": provenance.stamp(name)}
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


def _sf_counts():
    """Return San Francisco taxi rides per five minutes, and the rides themselves."""
    import pandas as pd

    from depot_twin.data import sftaxi

    rides = sftaxi.fetch_rides()
    starts = pd.DatetimeIndex([ride["start"] for ride in rides])
    counts = pd.Series(1, index=starts).resample("5min").sum().astype(float)
    return counts, rides


def _sf_describe(counts, rides) -> None:
    """Write what the taxi data says about rides themselves: how long, how dear, and when in the week."""
    import numpy as np

    miles = np.array([ride["miles"] for ride in rides])
    fares = np.array([ride["fare"] for ride in rides])
    days = (counts.index.max() - counts.index.min()).days + 1
    _write(
        "sf_taxi_stats.json",
        {
            "rides": len(rides),
            "first": str(counts.index.min()),
            "last": str(counts.index.max()),
            "rides_per_day": round(len(rides) / days),
            "miles_mean": round(float(miles.mean()), 2),
            "miles_median": round(float(np.median(miles)), 2),
            "miles_p90": round(float(np.percentile(miles, 90)), 2),
            "fare_mean": round(float(fares.mean()), 2),
            "airport_pickup_share": round(float(np.mean([ride["airport"] for ride in rides])), 4),
        },
    )
    hourly = counts.resample("h").sum()
    by_slot = hourly.groupby([hourly.index.dayofweek, hourly.index.hour]).mean().to_numpy()
    shares = by_slot / by_slot.sum()
    _write("weekly_shape_sf.json", {"first_hour": "Monday 00:00", "shares": [round(float(x), 6) for x in shares]})


def _weather_frame(place: str, first, last):
    import pandas as pd

    from depot_twin.data import weather

    return pd.DataFrame(weather.fetch_hours(place, first.date(), last.date())).set_index("time")


E8_START = "2024-04-15"  # a Monday inside the block the forecasts were never trained or calibrated on
E8_DAYS, E8_WARMUP_DAYS = 14, 7
E8_DEV_START = "2024-03-18"  # development ran on these earlier days, so the evaluation days stayed unseen
E8_SEEDS = (201, 202, 203, 204, 205)
E8_SIZES = (500, 1000)
E8_RULES = ("threshold", "headroom", "heartbeat")


def _sf_counts_cached():
    """Return San Francisco taxi rides per five minutes, from disk when already built."""
    import pandas as pd

    path = data_dir() / "derived" / "sf_taxi_5min.parquet"
    if path.exists():
        return pd.read_parquet(path)["rides"]
    counts, _ = _sf_counts()
    counts.rename("rides").to_frame().to_parquet(path)
    return counts


def replay_curves(start: str):
    """Return the replay window's demand and forecasts, building and storing them on first use."""
    import numpy as np
    import pandas as pd

    from depot_twin import provenance, replay

    # "now:<day>" asks for the same window with the hour under way forecast by its own model.
    own_first_hour, start = start.startswith("now:"), start.removeprefix("now:")
    # The stored curves are named for the forecast models they were made with: new models, new curves.
    derived = data_dir() / "derived"
    models = provenance.file_hash(*sorted(derived.glob("forecast_ratio_*.json")))
    path = derived / f"replay_{'now_' if own_first_hour else ''}{start}_{models}.npz"
    if path.exists():
        return dict(np.load(path))
    counts = _sf_counts_cached()
    weather = _weather_frame("san_francisco", counts.index.min(), counts.index.max())
    forecasts = replay.load_forecasts(data_dir() / "derived")
    if own_first_hour:
        forecasts = {0: _first_hour_model(counts, weather), **forecasts}
    curves = replay.forecast_curves(forecasts, counts, weather, pd.Timestamp(start), E8_DAYS)
    np.savez_compressed(path, **curves)
    return curves


def _first_hour_model(counts, weather):
    """Return a forecast of the hour that starts now, trained and bounded like the other horizons."""
    from depot_twin.features import build
    from depot_twin.models import short_horizon

    parts = short_horizon.blocks(build(counts, 0, 12, weather), 0)
    return short_horizon.fit(parts, 0, scale_free=True)


def _e8_rule(name: str, settings: dict | None = None):
    from depot_twin.dispatch import HeadroomRecall
    from depot_twin.fleet import ThresholdRecall
    from depot_twin.heartbeat import Heartbeat

    if name == "heartbeat":
        return Heartbeat(**(settings or {}))
    return {"threshold": ThresholdRecall, "headroom": HeadroomRecall}[name]()


def what_ran(result, rule, size: int, chargers: int, first: float, days: float) -> dict:
    """The cadence an arm actually ran at, and how much of its calling the floor did instead of the rule.

    An arm is named for the rule it was given. Whether that rule was the one deciding is measured here: a
    depot short of energy calls nearly every vehicle in at the floor, whatever rule is installed.
    """
    from depot_twin.dispatch import HARD_FLOOR_SOC

    steps = result.steps[result.steps[:, 0] >= first]
    visits = [s for s in result.depot.sessions if s.visit.arrive_min >= first]
    at_floor = sum(1 for s in visits if s.visit.soc_in <= HARD_FLOOR_SOC)
    calls = getattr(rule, "calls", 0)
    return {
        "trips_per_visit": float(steps[:, 2].sum()) / max(len(visits), 1),
        "visits_per_vehicle_day": len(visits) / size / days,
        "visits_per_charger_day": len(visits) / chargers / days,
        "arrived_at_floor_share": at_floor / max(len(visits), 1),
        # For the plan: the share of its calls the floor forced over the whole run. Zero for rules that keep no count.
        "forced_call_share": getattr(rule, "forced_calls", 0) / calls if calls else 0.0,
        "inspected_share": sum(s.inspected for s in visits) / max(len(visits), 1),
    }


def _e8_scores(sim, result, rule, demand, depot) -> dict:
    """Score the last seven days of a run."""
    import numpy as np

    from depot_twin.replay import STEPS_PER_HOUR

    first = E8_WARMUP_DAYS * 1440.0
    steps = result.steps[result.steps[:, 0] >= first]
    series = result.depot.series[result.depot.series[:, 0] >= first]
    sessions = [
        s for s in result.depot.sessions if s.connected_min is not None and s.connected_min >= first and s.charged_min
    ]
    chargers = sum(bank.count for bank in depot.chargers)
    busy = steps[:, 1] >= np.quantile(steps[:, 1], 0.9)
    hours = np.arange(E8_WARMUP_DAYS * 24, E8_DAYS * 24 - 1) * STEPS_PER_HOUR
    held = demand.actual[hours, 0] <= demand.upper[hours, 0]
    expected_busy = demand.mean[hours, 0] >= np.quantile(demand.mean[hours, 0], 0.9)
    scores = {
        "served": served_share(steps),
        "on_road_when_busiest": float(steps[busy, 3].mean() / sim.config.size),
        "stranded": float(result.stranded),
        "grid_variation": float(series[:, 1].std() / series[:, 1].mean()),
        "kwh_per_charger_hour": float(
            sum(s.energy_kwh for s in sessions) / (chargers * (E8_DAYS - E8_WARMUP_DAYS) * 24.0)
        ),
        "sessions_per_vehicle_day": len(sessions) / sim.config.size / (E8_DAYS - E8_WARMUP_DAYS),
        "kwh_per_session": float(np.mean([s.energy_kwh for s in sessions])),
        "upper_bound_held": float(held.mean()),
        "upper_bound_held_when_expected_busy": float(held[expected_busy].mean()),
        **what_ran(result, rule, sim.config.size, chargers, first, E8_DAYS - E8_WARMUP_DAYS),
    }
    ledger = [e for e in getattr(rule, "ledger", []) if e["hour"] >= E8_WARMUP_DAYS * 24]
    if ledger:
        scores["ledger_kept"] = float(np.mean([e["kept"] for e in ledger]))
        # How much of what was delivered had been promised: a ledger that promises nothing is always kept.
        scores["ledger_promised_share"] = float(sum(e["committed"] for e in ledger) / sum(e["actual"] for e in ledger))
        scores["tick_ms_median"] = float(np.median(rule.tick_seconds) * 1000.0)
        scores["tick_ms_p99"] = float(np.percentile(rule.tick_seconds, 99) * 1000.0)
    return scores


E9_START = "2024-05-13"
E9_SEEDS = (301, 302, 303, 304, 305)
E9_LEDGER = {"ledger_adapt": 0.2, "ledger_level": 0.975, "ledger_from_state": True}
E12_START = "2024-04-29"  # the last two weeks of the held-out block not yet used
E12_SEEDS = (401, 402, 403, 404, 405)
# `plan_clock_only` is the plan with its clock steering and an hourly program that cannot see prices: it
# tells how much of the plan's saving is the steering and how much is the program.
E12_ARMS = ("threshold", "threshold_steered", "plan", "plan_with_prices", "plan_clock_only")
E12_SETTINGS = {"pre_peak_hours": 4.0, "peak_call_below": 0.15}  # chosen on the development days


def _chicago_curves(start: str) -> dict:
    """Return a fortnight of real Chicago ride-hail demand as five-minute replay curves, with no forecast."""
    import numpy as np
    import pandas as pd

    from depot_twin import replay, synth
    from depot_twin.data import donors

    first = pd.Timestamp(start)
    hourly = donors.load_panel()["chicago_ridehail_city"].dropna()
    hourly = hourly[first : first + pd.Timedelta(days=E8_DAYS) - pd.Timedelta(hours=1)]
    # Thinned to a depot's scale before it is spread over five-minute steps; the fleet scales it exactly later.
    scale = 1000.0 / hourly.mean()
    counts = np.random.default_rng(14).binomial(hourly.to_numpy().astype(int), scale).astype(float)
    return replay.plain_curves(synth.five_minute(pd.Series(counts, index=hourly.index), np.random.default_rng(15)))
