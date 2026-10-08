"""The model workbench: the same forecast built many ways, each scored and each handed to the plan.

A forecast is not good or bad in itself; it is good or bad for the decision it feeds. This module builds a
reference forecast and a set of variants that each change one thing about it: how long it trains, what it
is given, how much history it sees, what it is asked to predict, whether it has seen the city at all,
whether it is a model at all, and whether its output reaches the plan intact. Every variant is scored the
same way on the same held-out days, and the depot is then run on each one's forecasts.

One thing changes at a time. Tree depth and the other settings stay at the reference's, so that a
difference between two variants has one cause.

Nothing here is a registered test. The days the depot runs on (from 15 April 2024) have been used before.
The output is a file the front end reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from depot_twin import replay
from depot_twin.data import data_dir
from depot_twin.features import BASELINES, FEATURES, SERIES_FEATURES, build
from depot_twin.fleet import served_share
from depot_twin.models import short_horizon
from depot_twin.models.short_horizon import Forecast, wape

START = "2024-04-15"
DAYS, WARMUP_DAYS = 14, 7
FLEET = 500
SEEDS = (901, 902, 903)
HORIZONS = short_horizon.HORIZONS
# Tree settings chosen for the reference by cross-validation in E7b; every variant keeps them.
SETTINGS = {
    1: {"max_depth": 6, "min_child_weight": 1},
    6: {"max_depth": 4, "min_child_weight": 1},
    24: {"max_depth": 4, "min_child_weight": 1},
}
CHECKPOINTS = (1, 2, 5, 10, 20, 50, 100, 200, 400, 700, 1000, 1500, 2000, 3000)
CALENDAR = ["hour", "weekday", "weekend", "holiday", "month", "minute_of_day"]
FAULT_FACTOR = 0.33  # a broken feed reports a third of the rides the model forecast, as in E10


@dataclass(frozen=True)
class Variant:
    """One way of building the forecast. Fields left alone are the reference's."""

    ident: str
    dial: str
    label: str
    note: str
    features: tuple[str, ...] = tuple(FEATURES)
    trees: int | None = None  # None stops when the stop block stops improving
    months: int | None = None  # None trains on all the history there is
    target: str = "ratio"
    kind: str = "trained"  # "trained", "last_week", "no_local" or "pretrained"
    fault: str | None = None  # None, "open" (nothing watching) or "guarded"
    trace: bool = False  # also record a run the front end can replay


LAGS = tuple(SERIES_FEATURES)
VARIANTS = (
    Variant(
        "reference",
        "reference",
        "Reference",
        "All features, trees stopped early, all history, ratio target.",
        trace=True,
    ),
    Variant("trees_10", "rounds", "10", "Ten trees: the model has barely begun to fit.", trees=10, trace=True),
    Variant(
        "trees_50",
        "rounds",
        "50",
        "Fifty trees. On the held-out days this scores better than the reference, which stops later on its validation block.",
        trees=50,
    ),
    Variant(
        "trees_200",
        "rounds",
        "200",
        "Two hundred trees: still short of where the reference stops, and ahead of it on the held-out days.",
        trees=200,
    ),
    Variant(
        "trees_3000",
        "rounds",
        "3,000",
        "No early stopping: training error keeps falling after validation error has stopped.",
        trees=3000,
    ),
    Variant(
        "lags_only",
        "features",
        "Lags only",
        "Only the ride series against its own past. No clock, no weather.",
        features=LAGS,
    ),
    Variant(
        "lags_calendar",
        "features",
        "Plus calendar",
        "Lags and the calendar of the hour forecast. No weather.",
        features=LAGS + tuple(CALENDAR),
    ),
    Variant("months_1", "history", "1 month", "Trained on the last month before the stop block.", months=1),
    Variant("months_3", "history", "3 months", "Trained on the last three months.", months=3),
    Variant("months_6", "history", "6 months", "Trained on the last six months.", months=6),
    Variant(
        "counts",
        "target",
        "Ride counts",
        "Asked for rides, not for the ratio to last week. Trees extrapolate poorly beyond the count levels in their training rows.",
        target="count",
    ),
    Variant(
        "no_local",
        "local",
        "None",
        "Trained on other cities and generated demand. It has never seen San Francisco.",
        kind="no_local",
    ),
    Variant(
        "last_week",
        "model",
        "No model",
        "Same hour last week, with a bound sized the same way. The bar a model must beat.",
        kind="last_week",
        trace=True,
    ),
    Variant(
        "chronos",
        "model",
        "Pretrained (Chronos-2)",
        "Amazon's pretrained time-series model, used with no local fitting, with a bound sized the same way. E18's result, on this city.",
        kind="pretrained",
    ),
    Variant(
        "fault_open",
        "feed",
        "Broken, unwatched",
        "The reference model, but the plan is fed a third of its forecast: from the second week in the scored run, from noon on the first day in the recording.",
        fault="open",
        trace=True,
    ),
    Variant(
        "fault_guarded",
        "feed",
        "Broken, guarded",
        "The same broken feed, with a guard that hands control to a simple rule when the bound keeps breaking.",
        fault="guarded",
        trace=True,
    ),
)
DIALS = (
    ("rounds", "Boosting rounds", "Stopped early"),
    ("features", "Features", "All, with weather"),
    ("history", "Training history", "All of it"),
    ("target", "What it predicts", "Ratio to last week"),
    ("local", "Local history", "This city"),
    ("model", "Model", "Trained here"),
    ("feed", "Forecast feed", "Intact"),
)


class Pretrained(Forecast):
    """Chronos-2's hourly forecasts, read for five-minute rows without looking ahead.

    The pretrained model forecasts whole clock hours from whole clock hours. A five-minute row knows the
    rides up to the end of its own step, and its label is the hour that starts `horizon` hours after that,
    which straddles two clock hours unless the step ends on the hour. So the forecast used is the one made
    from the last clock hour that had finished by then, and it is the two clock-hour forecasts the label
    straddles, each weighted by the share of the label that falls in it.
    """

    table: pd.DataFrame | None = None

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Rides forecast for each row's label hour, from the last forecast the row could have had."""
        known = rows.index + pd.Timedelta(minutes=replay.STEP_MIN)  # a row knows its own step's rides
        top = known.floor("h")
        origin = top - pd.Timedelta(hours=1)  # the last clock hour complete at that moment
        late = np.asarray((known - top) / pd.Timedelta(hours=1), dtype=float)
        first = self.table.reindex(origin)[self.horizon_hours].to_numpy(dtype=float)
        second = self.table.reindex(origin)[self.horizon_hours + 1].to_numpy(dtype=float)
        return (1.0 - late) * first + late * second


class LastWeek(Forecast):
    """No model: the forecast is the same hour last week. Its bound is sized the way a model's is."""

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Return last week's rides for the target hour."""
        return rows[short_horizon.REFERENCE].to_numpy().astype(float)


def _counts_and_weather():
    from depot_twin import evals

    counts = evals._sf_counts_cached()
    return counts, evals._weather_frame("san_francisco", counts.index.min(), counts.index.max())


def _recent(train: pd.DataFrame, months: int | None) -> pd.DataFrame:
    """Keep only the last so many months of the training block."""
    if months is None:
        return train
    return train[train.index > train.index.max() - pd.Timedelta(days=30 * months)]


def pretrained_horizons() -> tuple[int, ...]:
    """Each horizon and the clock hour after it: a five-minute row's label straddles the two."""
    return tuple(sorted({h + extra for h in HORIZONS for extra in (0, 1)}))


def _pretrained_table(counts: pd.Series, first: pd.Timestamp) -> pd.DataFrame:
    """Chronos-2's forecasts at every hour from `first` to the end of the series, on the hourly series."""
    from depot_twin.models import reserve

    hourly = counts.resample("h").sum()
    # The hour in progress is left out of the series handed over: a forecast is made from complete hours only.
    origins = hourly.index[hourly.index >= first.floor("h") - pd.Timedelta(hours=2)]
    return reserve.chronos_points(hourly, origins, horizons=pretrained_horizons())


def _fit(variant: Variant, parts: dict, horizon: int, pretrained: pd.DataFrame | None = None):
    """Fit one variant at one horizon and size its bound on the calibration block."""
    scale_free = variant.target == "ratio"
    features = list(variant.features)
    if variant.kind == "pretrained":
        forecast = Pretrained(horizon, None, features, {})
        forecast.table = pretrained
    elif variant.kind == "last_week":
        forecast = LastWeek(horizon, None, features, {})
    else:
        early = variant.trees is None
        model = short_horizon._model(SETTINGS[horizon], variant.trees or short_horizon.MAX_TREES, early, scale_free)
        train = _recent(parts["train"], variant.months)
        short_horizon._train(model, train, features, scale_free, stop=parts["stop"] if early else None)
        forecast = Forecast(horizon, model, features, SETTINGS[horizon], scale_free=scale_free)
    predicted = forecast.predict(parts["calibrate"])
    scaled = (parts["calibrate"]["label"].to_numpy() - predicted) / np.sqrt(predicted + 1.0)
    forecast.upper_95, forecast.lower_05 = float(np.quantile(scaled, 0.95)), float(np.quantile(scaled, 0.05))
    return forecast


def _trees(forecast: Forecast) -> int:
    """Return how many trees a fitted model uses."""
    booster = forecast.model.get_booster()
    best = getattr(forecast.model, "best_iteration", None)
    return int(best) + 1 if best is not None else booster.num_boosted_rounds()


def learning_curve(forecast: Forecast, parts: dict, months: int | None) -> dict:
    """Return error on training rows and on the stop block as trees are added.

    Error is in rides, as a share of rides, whatever the model predicts, so that every variant's curve is
    on one scale. The stop block is the validation set: it decides when to stop and is never trained on.
    """
    train = _recent(parts["train"], months).iloc[::8]
    total = forecast.model.get_booster().num_boosted_rounds()
    points = [k for k in CHECKPOINTS if k <= total]
    out = {"trees": points, "train": [], "validation": []}
    for k in points:
        for name, rows in (("train", train), ("validation", parts["stop"])):
            x = short_horizon._inputs(rows, forecast.features, forecast.scale_free)
            raw = forecast.model.predict(x, iteration_range=(0, k))
            predicted = np.maximum(0.0, raw * short_horizon._reference(rows)) if forecast.scale_free else raw
            out[name].append(round(wape(rows["label"].to_numpy(), predicted), 4))
    return out


def _importance(forecast: Forecast) -> list[list]:
    """Return the features that did most to reduce error, as shares of the total gain."""
    gains = forecast.model.get_booster().get_score(importance_type="gain")
    total = sum(gains.values())
    top = sorted(gains.items(), key=lambda item: -item[1])[:8]
    return [[name, round(gain / total, 3)] for name, gain in top]


def _score(forecast: Forecast, parts: dict) -> dict:
    """Score a forecast on the held-out block: error, the naive rule's error, and how often the bound held."""
    held = parts["holdout"]
    actual, predicted = held["label"].to_numpy(), forecast.predict(held)
    by_hour = [round(wape(actual[held.index.hour == h], predicted[held.index.hour == h]), 4) for h in range(24)]
    return {
        "error": round(wape(actual, predicted), 4),
        "same_hour_last_week": round(wape(actual, held[BASELINES["same_time_last_week"]].to_numpy()), 4),
        "upper_bound_held": round(float((actual <= forecast.upper(held)).mean()), 4),
        "by_hour": by_hour,
    }


def _without_local_history(horizon: int):
    """Return the forecast trained with no San Francisco data, as E13 builds it."""
    from depot_twin import newsite

    sources = newsite.Sources.load()
    target = next(d for d in sources.donors if d.name == "sf_taxi_city")
    return newsite.forecast_without(sources, target, horizon)


def build_variant(ident: str) -> Path:
    """Train one variant at every horizon, score it, and store its forecasts for the depot's days."""
    from depot_twin import replay

    variant = next(v for v in VARIANTS if v.ident == ident)
    folder = data_dir() / "derived" / "workbench"
    folder.mkdir(parents=True, exist_ok=True)
    counts, weather = _counts_and_weather()
    forecasts, record = {}, {"horizons": {}}
    pretrained = None
    if variant.kind == "pretrained":
        from depot_twin.models import reserve

        first = short_horizon.blocks(build(counts, 1, 12, weather), 1)["calibrate"].index.min()
        pretrained = _pretrained_table(counts, first)
        record["versions"] = reserve.pinned_versions()
    for horizon in HORIZONS:
        parts = short_horizon.blocks(build(counts, horizon, 12, weather), horizon)
        forecast = (
            _without_local_history(horizon) if variant.kind == "no_local" else _fit(variant, parts, horizon, pretrained)
        )
        forecasts[horizon] = forecast
        record["horizons"][str(horizon)] = _score(forecast, parts)
        if horizon == 1 and variant.kind == "trained":
            record["trees"] = _trees(forecast)
            record["curve"] = learning_curve(forecast, parts, variant.months)
            record["importance"] = _importance(forecast)
            record["training_rows"] = len(_recent(parts["train"], variant.months))
    curves = replay.forecast_curves(forecasts, counts, weather, pd.Timestamp(START), DAYS)
    np.savez_compressed(folder / f"{ident}.npz", **curves)
    hourly = slice(None, None, replay.STEPS_PER_HOUR)
    record["days"] = {
        name: np.round(curves[name][hourly, 1]).astype(int).tolist() for name in ("mean", "upper", "actual")
    }
    path = folder / f"{ident}.json"
    path.write_text(json.dumps(record))
    return path


def _rule(variant: Variant):
    from depot_twin import evals
    from depot_twin.economics import Prices
    from depot_twin.fleet import ThresholdRecall
    from depot_twin.guard import Guarded
    from depot_twin.heartbeat import Heartbeat

    plan = Heartbeat(**evals.E9_LEDGER, prices=Prices(), **evals.E12_SETTINGS)
    return Guarded(plan, ThresholdRecall()) if variant.fault == "guarded" else plan


def _simulation(variant: Variant, seed: int, fault_from_minute: float, size: int = FLEET):
    """Return the fleet simulation for a variant: the price-aware plan on that variant's forecasts."""
    from dataclasses import replace as with_changes

    from depot_twin import growth
    from depot_twin.fleet import FleetSim, load_weekly_shape
    from depot_twin.replay import ReplayDemand
    from depot_twin.twin import EnergyIdentifier

    source = "reference" if variant.fault else variant.ident
    curves = dict(np.load(data_dir() / "derived" / "workbench" / f"{source}.npz"))
    fleet, depot = growth.scaled_v2(size, **growth.OPTIONS["one_feeder"])
    demand = ReplayDemand.scaled(curves, size * fleet.rides_per_vehicle_day)
    if variant.fault:
        demand = with_changes(demand, fault_from_minute=fault_from_minute, fault_factor=FAULT_FACTOR)
    rule = _rule(variant)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed, demand=demand)
    drive = np.array([m.drive_kwh_per_mile for m in fleet.models])[sim.model_of]
    load = np.array([m.always_on_kw for m in fleet.models])[sim.model_of]
    sim.telemetry = EnergyIdentifier(drive, load, sim.capacity, seed=seed)
    getattr(rule, "primary", rule).energy = sim.telemetry
    return sim, rule, demand


def decide(job: tuple[str, int] | tuple[str, int, int]) -> dict:
    """Run the depot for a fortnight on one variant's forecasts and score the second week."""
    from depot_twin.economics import Prices, energy_by_period
    from depot_twin.replay import STEPS_PER_HOUR

    ident, seed, *rest = job
    size = rest[0] if rest else FLEET
    variant = next(v for v in VARIANTS if v.ident == ident)
    first = WARMUP_DAYS * 1440.0
    sim, rule, demand = _simulation(variant, seed, fault_from_minute=first, size=size)
    result = sim.run(DAYS)
    steps = result.steps[result.steps[:, 0] >= first]
    prices, energy = Prices(), energy_by_period(result.depot.series, skip_days=WARMUP_DAYS)
    cost = energy["peak"] * prices.energy_peak + energy["off_peak"] * prices.energy_off_peak
    cost += energy["super_off_peak"] * prices.energy_super_off_peak
    ledger = [e for e in getattr(rule, "primary", rule).ledger if e["hour"] >= WARMUP_DAYS * 24]
    hours = np.arange(WARMUP_DAYS * 24, DAYS * 24 - 2) * STEPS_PER_HOUR
    given = demand.upper[hours, 1] * (FAULT_FACTOR if variant.fault else 1.0)
    fell_back = [e for e in getattr(rule, "events", []) if e["event"] == "fell back"]
    scored_days = DAYS - WARMUP_DAYS
    return {
        "ident": ident,
        "served": served_share(steps),
        "rides_offered_per_day": float(steps[:, 1].sum() / scored_days),
        "kwh_per_day": float(sum(energy.values()) / scored_days),
        "promises_kept": float(np.mean([e["kept"] for e in ledger])) if ledger else float("nan"),
        "cost_per_kwh": cost / sum(energy.values()),
        "peak_price_share": energy["peak"] / sum(energy.values()),
        "bound_held_in_run": float((demand.actual[hours, 1] <= given).mean()),
        "guard_took_over": float(len(fell_back)),
        "stranded": float(result.stranded),
    }


def record_trace(ident: str, out: str = "web/public/traces") -> Path:
    """Record two days of a variant's run for the front end to replay. A fault starts at noon on the first day."""
    from depot_twin.trace import TraceRecorder, problems

    variant = next(v for v in VARIANTS if v.ident == ident)
    sim, _, _ = _simulation(variant, SEEDS[0], fault_from_minute=720.0)
    recorder = TraceRecorder(sim, label="heartbeat + slot_power")
    sim.run(2)
    wrong = problems(recorder.to_dict())
    if wrong:
        raise ValueError(f"trace for {ident} breaks the contract: {wrong[:3]}")
    return recorder.export(Path(out) / f"model_{ident}.json")


RIDES_PER_VEHICLE_HOUR = 60.0 / 23.0


def reserve(days: dict, fleet: int, rides_per_vehicle_day: float) -> dict:
    """Return what a forecast's upper bound asks of a fleet, hour by hour over the depot's days.

    The plan keeps enough vehicles on the road for the bound, not for the forecast. Where the bound sits
    above the rides that came, vehicles were held that could have been charging. Where rides came in
    above the bound, the plan had not provided for them. A sharper forecast with an honest bound holds
    fewer vehicles for the same cover. Figures are scaled from the source city's rides to the fleet's, and
    are taken over the week the depot's run is scored on.
    """
    actual, mean, upper = (np.array(days[name], float) for name in ("actual", "mean", "upper"))
    known = ~np.isnan(actual)
    actual, mean, upper = actual[known], mean[known], upper[known]
    scale = fleet * rides_per_vehicle_day / (actual.sum() / (len(actual) / 24.0))
    return {
        "vehicles_held_in_reserve": round(
            float(np.clip(upper - actual, 0, None).mean() * scale / RIDES_PER_VEHICLE_HOUR), 1
        ),
        "rides_above_the_bound_per_day": round(
            float(np.clip(actual - upper, 0, None).sum() * scale / (len(actual) / 24.0)), 1
        ),
        "bound_above_forecast": round(float((upper - mean).sum() / mean.sum()), 4),
    }


def _broken(days: dict) -> dict:
    """Return a fortnight's forecasts as the plan received them when the feed broke at the start of week two."""
    first = WARMUP_DAYS * 24
    scaled = {
        name: days[name][:first] + [round(v * FAULT_FACTOR) for v in days[name][first:]] for name in ("mean", "upper")
    }
    return {**scaled, "actual": days["actual"]}


def reassemble(out: str = "web/public/models.json") -> Path:
    """Write the front end's file again from the stored records, keeping the depot results already in it."""
    variants = json.loads(Path(out).read_text())["variants"]
    return assemble([{"ident": ident, **record["decision"]} for ident, record in variants.items()], out)


def _depot_figures() -> dict:
    """The chargers and the ride time of the depot the variants ran on."""
    from depot_twin import growth

    fleet, depot = growth.scaled_v2(FLEET, **growth.OPTIONS["one_feeder"])
    return {
        "chargers": sum(bank.count for bank in depot.chargers),
        "ride_minutes": fleet.ride_minutes,
        "rides_per_vehicle_day": fleet.rides_per_vehicle_day,
        "site_limit_kw": depot.site_limit_kw,
        "usable_kw": depot.usable_kw,
    }


def assemble(decisions: list[dict], out: str = "web/public/models.json") -> Path:
    """Gather every variant's scores, curves and depot results into the file the front end reads."""
    folder = data_dir() / "derived" / "workbench"
    variants = {}
    for variant in VARIANTS:
        source = "reference" if variant.fault else variant.ident
        record = json.loads((folder / f"{source}.json").read_text())
        mine = [d for d in decisions if d["ident"] == variant.ident]
        keys = [key for key in mine[0] if key != "ident"]
        means = {key: float(np.mean([d[key] for d in mine])) for key in keys}
        record["decision"] = {key: None if np.isnan(value) else round(value, 4) for key, value in means.items()}
        if variant.fault:
            record["days"] = _broken(record["days"])
        record["reserve"] = reserve({k: v[WARMUP_DAYS * 24 :] for k, v in record["days"].items()}, FLEET, 25.0)
        record.update(dial=variant.dial, label=variant.label, note=variant.note)
        record["trace"] = f"traces/model_{variant.ident}.json" if variant.trace else None
        variants[variant.ident] = record
    from depot_twin import finance
    from depot_twin.fares import PUBLISHED_AVERAGE_FARE

    assumptions = finance.Assumptions()
    page = {
        "start": START,
        "fleet": FLEET,
        "seeds": list(SEEDS),
        "money": {
            "fare_per_ride": PUBLISHED_AVERAGE_FARE,
            "lost_ride_cost": assumptions.lost_ride_cost,
            "vehicle_cost_per_year": assumptions.vehicle_cost_per_year,
        },
        "dials": [{"key": key, "name": name, "reference": reference} for key, name, reference in DIALS],
        # The depot the variants were run on, so the page can say why rides do not move with the forecast:
        # the plan serves rides with the vehicles on the road, and takes off the road at most what the
        # chargers hold; the forecast can only matter for rides when the fleet less that is near the peak's need.
        "depot": _depot_figures(),
        "variants": variants,
    }
    path = Path(out)
    path.write_text(json.dumps(page, separators=(",", ":")))
    return path


def build_all(workers: int = 4) -> Path:
    """Train every variant, run the depot on each, record the replays, and write the front end's file."""
    from concurrent.futures import ProcessPoolExecutor

    _counts_and_weather()
    trained = [v.ident for v in VARIANTS if not v.fault]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        list(pool.map(build_variant, trained))
        decisions = list(pool.map(decide, [(v.ident, seed) for v in VARIANTS for seed in SEEDS]))
        list(pool.map(record_trace, [v.ident for v in VARIANTS if v.trace]))
    return assemble(decisions)
