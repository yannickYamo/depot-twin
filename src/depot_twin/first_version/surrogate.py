"""A fast stand-in for the simulator, and the depot design it recommends.

The simulator answers one design in seconds. Choosing a design means asking about thousands: how many fast
and slow chargers, at what power, with what battery, for which fleet on which grid connection. So the
simulator is run once over a wide spread of designs, and gradient-boosted trees learn to predict its
answers. The trees then search the design space, and the simulator confirms the design they pick.

The inputs are the parameters a depot planner works with: the fleet and its demand, the chargers, the grid,
the people, and the levels at which vehicles are called in and released. Prices are deliberately not
inputs. The trees predict physical outcomes (rides served, energy by tariff period, peak draw), and money
is computed from those, so a price can change without retraining anything.

Guarding against overfitting is most of the work here:

- Designs are split by design point, so two runs of the same design never sit on both sides of a split.
- A band of fleet sizes is withheld from training and validation entirely, to test interpolation across a
  gap the trees have never seen.
- Hyperparameters are chosen by cross-validation inside the training set; the number of trees is set by
  early stopping on the validation set; the test set is scored once.
- Where physics fixes the direction of an effect (more grid power never serves fewer rides), the trees are
  constrained to respect it. Where it does not, they are left free.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from depot_twin.economics import Prices, daily_contribution, energy_by_period
from depot_twin.resources import Buffer, ChargerBank, DepotConfig

TEMPLATE = "scenarios/east_oakland_200.toml"
SHAPE = "data/derived/weekly_shape.json"
RUN_DAYS = 3.0
WARMUP_DAYS = 1.0  # the fleet starts with random charge levels; the first day is not measured
AC_KW = 11.0
EFFICIENCY = 0.93

# The design space: each input and the range it is drawn from.
RANGES: dict[str, tuple[float, float]] = {
    "size": (150.0, 2200.0),  # drawn on a log scale
    "site_limit_kw": (1000.0, 9000.0),
    "dc_per_100": (4.0, 24.0),  # fast chargers per 100 vehicles
    "dc_kw": (50.0, 150.0),
    "ac_per_100": (0.0, 15.0),  # slow chargers per 100 vehicles
    "buffer_kwh": (0.0, 6000.0),
    "rides_per_vehicle_day": (18.0, 32.0),
    "peak_gamma": (0.7, 1.5),  # sharpens (above 1) or flattens (below 1) the weekly demand shape
    "kwh_per_mile": (0.30, 0.55),
    "staff_per_100": (1.5, 4.0),
    "top_up_below": (0.40, 0.80),  # vehicles under this level may be called in when the road can spare them
    "full_target": (0.70, 0.95),  # the level vehicles are released at
}
INPUTS = list(RANGES)
DERIVED = ["site_kw_per_vehicle", "charger_kw_per_vehicle", "energy_ratio"]
# Two more ratios, used by the planner in planner.py and not by the models of evaluation E3.
EXTRA_DERIVED = ["ports_per_vehicle", "buffer_kwh_per_vehicle"]
FEATURES = INPUTS + DERIVED
TARGETS = ["served_share", "kwh_per_vehicle_day", "peak_kw_share", "peak_period_share"]

# Fleet sizes in this band are withheld from training and validation.
GAP_BAND = (900.0, 1150.0)

# Direction of an input's effect on rides served, where physics fixes it: +1 means more never hurts.
# Only grid power and the battery qualify. More chargers can hurt under the headroom rule, which fills
# every free charger and so takes more vehicles off the road at once.
MONOTONE_SERVED = {"site_limit_kw": 1, "site_kw_per_vehicle": 1, "buffer_kwh": 1}


def sample_designs(count: int, seed: int = 0) -> list[dict[str, float]]:
    """Draw designs uniformly from the design space; fleet size on a log scale."""
    rng = np.random.default_rng(seed)
    designs = []
    for index in range(count):
        design = {name: float(rng.uniform(low, high)) for name, (low, high) in RANGES.items()}
        low, high = RANGES["size"]
        design["size"] = float(round(math.exp(rng.uniform(math.log(low), math.log(high)))))
        design["id"] = index
        designs.append(design)
    return designs


def estimated_kwh_per_vehicle_day(design: dict[str, float]) -> float:
    """Return the planner's estimate of a vehicle's daily energy, from the filed miles per ride."""
    miles = design["rides_per_vehicle_day"] * 6.67
    return miles * design["kwh_per_mile"] + 1.5 * 22.0


def derive(design: dict[str, float]) -> dict[str, float]:
    """Add the ratios a planner would compute by hand. They use inputs only, never simulation results."""
    size = design["size"]
    charger_kw = (design["dc_per_100"] * design["dc_kw"] + design["ac_per_100"] * AC_KW) * size / 100.0
    deliverable = min(design["site_limit_kw"] * EFFICIENCY, charger_kw) * 24.0
    return {
        **design,
        "site_kw_per_vehicle": design["site_limit_kw"] / size,
        "charger_kw_per_vehicle": charger_kw / size,
        "energy_ratio": deliverable / (size * estimated_kwh_per_vehicle_day(design)),
        # The same charger power can be a few large plugs or many small ones; the count is what queues form at.
        "ports_per_vehicle": (design["dc_per_100"] + design["ac_per_100"]) / 100.0,
        "buffer_kwh_per_vehicle": design["buffer_kwh"] / size,
    }


def hand_estimate(design: dict[str, float]) -> float:
    """Return the spreadsheet answer for rides served: energy the site can deliver over energy wanted."""
    return min(1.0, derive(design)["energy_ratio"])


def equipment(design: dict[str, float]) -> dict:
    """Return the chargers, battery and headcount a design buys."""
    size = int(design["size"])
    banks = [ChargerBank("dc", max(1, round(design["dc_per_100"] * size / 100.0)), round(design["dc_kw"], 1))]
    slow = round(design["ac_per_100"] * size / 100.0)
    if slow:
        banks.append(ChargerBank("ac", slow, AC_KW))
    energy = design["buffer_kwh"]
    people = max(3, round(design["staff_per_100"] * size / 100.0))
    return {
        "site_limit_kw": design["site_limit_kw"],
        "chargers": tuple(banks),
        "buffer": Buffer(energy_kwh=energy, power_kw=energy / 2.0) if energy >= 200.0 else None,
        "staff": people,
        "cleaning_bays": people,
    }


def build(design: dict[str, float]):
    """Return the fleet, the depot and the recall rule for a design."""
    from depot_twin.dispatch import HeadroomRecall
    from depot_twin.fleet import load_fleet_scenario

    fleet, depot = load_fleet_scenario(TEMPLATE)
    depot = replace(depot, name="design", **equipment(design))
    fleet = replace(
        fleet,
        size=int(design["size"]),
        rides_per_vehicle_day=design["rides_per_vehicle_day"],
        kwh_per_mile=design["kwh_per_mile"],
    )
    full = design["full_target"]
    rule = HeadroomRecall(top_up_below=design["top_up_below"], full=full, quick=max(0.5, full - 0.2))
    return fleet, depot, rule


WEEK_RUN_DAYS = 8.0  # a warm-up day, then every day of the week once


def simulate(design: dict[str, float], seed: int = 0, run_days: float = RUN_DAYS) -> dict[str, float]:
    """Run one design and return its measured outcomes, after the warm-up day.

    The default three days measure a Tuesday and a Wednesday only, which is how evaluation E3 was run and
    why its money figures were off. Pass WEEK_RUN_DAYS to measure a whole week.
    """
    from depot_twin.fleet import FleetSim, load_weekly_shape, served_share

    fleet, depot, rule = build(design)
    shape = load_weekly_shape(SHAPE) ** design["peak_gamma"]
    result = FleetSim(fleet, depot, shape / shape.sum(), rule, seed=seed).run(run_days)
    steps = result.steps[result.steps[:, 0] >= WARMUP_DAYS * 1440.0]
    measured_days = run_days - WARMUP_DAYS
    energy = energy_by_period(result.depot.series, skip_days=WARMUP_DAYS)
    total = sum(energy.values())
    return {
        "served_share": served_share(steps),
        "rides_per_day": float(steps[:, 2].sum() / measured_days),
        "kwh_per_vehicle_day": total / measured_days / fleet.size,
        "peak_kw_share": float(result.depot.series[:, 1].max() / depot.site_limit_kw),
        "peak_period_share": energy["peak"] / total if total else 0.0,
        "stranded": float(result.stranded),
    }


def _run(task: tuple[dict[str, float], int, float]) -> dict[str, float]:
    design, seed, run_days = task
    return {**derive(design), "seed": seed, **simulate(design, seed, run_days)}


def run_designs(
    designs: list[dict[str, float]], seeds: list[int], workers: int = 5, run_days: float = RUN_DAYS
) -> list[dict[str, float]]:
    """Simulate every design under every seed, in parallel."""
    tasks = [(design, seed, run_days) for seed in seeds for design in designs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_run, tasks, chunksize=4))


def split(rows: list[dict[str, float]], seed: int = 0) -> dict[str, list[dict[str, float]]]:
    """Split rows by design point: gap band out first, then 70/15/15 at random.

    The split is on the design's id, so a design simulated under two seeds lands on one side only.
    """
    in_gap = [r for r in rows if GAP_BAND[0] <= r["size"] <= GAP_BAND[1]]
    rest = [r for r in rows if not GAP_BAND[0] <= r["size"] <= GAP_BAND[1]]
    ids = sorted({r["id"] for r in rest})
    np.random.default_rng(seed).shuffle(ids)
    cut_train, cut_valid = int(0.70 * len(ids)), int(0.85 * len(ids))
    train, valid = set(ids[:cut_train]), set(ids[cut_train:cut_valid])
    return {
        "train": [r for r in rest if r["id"] in train],
        "valid": [r for r in rest if r["id"] in valid],
        "test": [r for r in rest if r["id"] not in train and r["id"] not in valid],
        "gap": in_gap,
    }


def matrix(rows: list[dict[str, float]], target: str | None = None):
    """Return the feature matrix for rows, and the target vector when one is named."""
    x = np.array([[r[name] for name in FEATURES] for r in rows], dtype=float)
    if target is None:
        return x
    return x, np.array([r[target] for r in rows], dtype=float)


# Small on purpose: a few thousand rows do not justify a wide search, and every extra option is another
# chance to fit noise.
GRID = [
    {"max_depth": depth, "min_child_weight": weight, "reg_lambda": reg}
    for depth in (3, 4, 6)
    for weight in (1, 5)
    for reg in (1.0, 5.0)
]
FIXED = {"learning_rate": 0.05, "subsample": 0.8, "colsample_bytree": 0.8, "random_state": 7, "n_jobs": 4}
MAX_TREES = 3000
PATIENCE = 60


def _constraints(target: str) -> str | None:
    if target != "served_share":
        return None
    return "(" + ",".join(str(MONOTONE_SERVED.get(name, 0)) for name in FEATURES) + ")"


def _fit(params: dict, target: str, train, valid):
    """Fit one model, stopping when the validation error has not improved for PATIENCE rounds."""
    import xgboost as xgb

    model = xgb.XGBRegressor(
        **FIXED,
        **params,
        n_estimators=MAX_TREES,
        early_stopping_rounds=PATIENCE,
        eval_metric="mae",
        monotone_constraints=_constraints(target),
    )
    model.fit(*train, eval_set=[valid], verbose=False)
    return model


def choose_params(rows: list[dict[str, float]], target: str, folds: int = 5, seed: int = 0) -> tuple[dict, float]:
    """Pick hyperparameters by cross-validation on the training rows only. Returns them with their error."""
    ids = sorted({r["id"] for r in rows})
    np.random.default_rng(seed).shuffle(ids)
    fold_of = {ident: n % folds for n, ident in enumerate(ids)}
    best: tuple[dict, float] = ({}, float("inf"))
    for params in GRID:
        errors = []
        for fold in range(folds):
            inside = [r for r in rows if fold_of[r["id"]] != fold]
            held = [r for r in rows if fold_of[r["id"]] == fold]
            model = _fit(params, target, matrix(inside, target), matrix(held, target))
            errors.append(float(np.abs(model.predict(matrix(held)) - matrix(held, target)[1]).mean()))
        mean = float(np.mean(errors))
        if mean < best[1]:
            best = (params, mean)
    return best


def mae(model, rows: list[dict[str, float]], target: str) -> float:
    """Return the mean absolute error of a model on rows."""
    x, y = matrix(rows, target)
    return float(np.abs(model.predict(x) - y).mean())


def train_all(parts: dict[str, list[dict[str, float]]]) -> tuple[dict, dict]:
    """Train one model per target. Returns the models and, per target, the errors on every split."""
    models, report = {}, {}
    for target in TARGETS:
        params, cv_error = choose_params(parts["train"], target)
        model = _fit(params, target, matrix(parts["train"], target), matrix(parts["valid"], target))
        models[target] = model
        report[target] = {
            "params": params,
            "trees": int(model.best_iteration) + 1,
            "cv_mae": round(cv_error, 5),
            **{f"{name}_mae": round(mae(model, rows, target), 5) for name, rows in parts.items()},
        }
    return models, report


def noise_floor(rows: list[dict[str, float]], target: str) -> float:
    """Return how far two runs of the same design differ, on average: the error no model can get under."""
    by_id: dict[float, list[float]] = {}
    for row in rows:
        by_id.setdefault(row["id"], []).append(row[target])
    pairs = [values for values in by_id.values() if len(values) >= 2]
    return float(np.mean([abs(v[0] - v[1]) for v in pairs])) if pairs else float("nan")


def save_models(models: dict, folder: str | Path) -> None:
    """Write each model next to a manifest of the features it expects."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for target, model in models.items():
        model.save_model(str(folder / f"{target}.json"))
    (folder / "features.json").write_text(json.dumps({"features": FEATURES, "targets": TARGETS}, indent=2) + "\n")


def load_models(folder: str | Path) -> dict:
    """Read the models written by save_models."""
    import xgboost as xgb

    models = {}
    for target in TARGETS:
        model = xgb.XGBRegressor()
        model.load_model(str(Path(folder) / f"{target}.json"))
        models[target] = model
    return models


def predict(models: dict, designs: list[dict[str, float]]) -> list[dict[str, float]]:
    """Return predicted outcomes for designs."""
    rows = [derive(d) for d in designs]
    x = matrix(rows)
    columns = {target: models[target].predict(x) for target in TARGETS}
    columns["served_share"] = np.clip(columns["served_share"], 0.0, 1.0)
    return [{target: float(columns[target][n]) for target in TARGETS} for n in range(len(rows))]


def contribution(design: dict[str, float], outcome: dict[str, float], prices: Prices | None = None) -> float:
    """Return the depot's daily contribution per vehicle for a design, given its outcomes."""
    size = design["size"]
    depot = DepotConfig(name="design", **equipment(design))
    rides = outcome.get("rides_per_day", outcome["served_share"] * design["rides_per_vehicle_day"] * size)
    total = outcome["kwh_per_vehicle_day"] * size
    peak = total * outcome["peak_period_share"]
    # Outside the peak, energy splits between the two cheaper periods roughly by their length: 14 and 5 hours.
    energy = {"peak": peak, "off_peak": (total - peak) * 14.0 / 19.0, "super_off_peak": (total - peak) * 5.0 / 19.0}
    # Without a prediction of the peak, assume the site draws its full limit at some point in the month.
    peak_kw = outcome.get("peak_kw_share", 1.0) * design["site_limit_kw"]
    return daily_contribution(depot, rides, energy, peak_kw, prices)["contribution"] / size


# What the planner chooses; everything else in a design is given by the site, the fleet and the market.
CHOICES = ("dc_per_100", "dc_kw", "ac_per_100", "buffer_kwh", "staff_per_100", "top_up_below", "full_target")


def best_design(models: dict, given: dict[str, float], candidates: int = 20_000, seed: int = 0) -> dict:
    """Search the planner's choices for the design with the highest predicted contribution per vehicle."""
    rng = np.random.default_rng(seed)
    designs = []
    for index in range(candidates):
        design = {**given, "id": index}
        for name in CHOICES:
            design[name] = float(rng.uniform(*RANGES[name]))
        designs.append(design)
    outcomes = predict(models, designs)
    values = [contribution(d, o) for d, o in zip(designs, outcomes, strict=True)]
    top = int(np.argmax(values))
    return {"design": designs[top], "predicted": outcomes[top], "predicted_contribution": values[top]}
