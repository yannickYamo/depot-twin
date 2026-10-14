"""The depot planner: a surrogate that is safe to optimize against, and the search built on it.

An optimizer does not sample a model fairly. It hunts for the designs the model likes best, and a design
the model likes too much is exactly what it will find. A surrogate that is accurate on average can still
hand the planner a depot that fails. This module is built around that risk:

- Simulations are concentrated where the decision lives, on designs that barely have enough power and
  chargers, instead of being spread evenly over designs nobody would build.
- Predictions cannot leave their physical range: shares stay between 0 and 1, energy stays positive.
- The planner does not take a prediction at face value. It subtracts the model's own measured tendency to
  over-predict service before accepting that a design meets the service level.
- A design is chosen to hold the service level across a spread of demand, not only on the expected week.
- What the planner picks is always sent back to the simulator, and the gap is reported as regret.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import qmc

from depot_twin.economics import Prices
from depot_twin.first_version import surrogate
from depot_twin.first_version.surrogate import CHOICES, EFFICIENCY, FIXED, GRID, MAX_TREES, PATIENCE, RANGES

FEATURES = surrogate.FEATURES + surrogate.EXTRA_DERIVED
# The peak draw is not predicted: under every rule tried the site reaches its limit at some point, so the
# capacity subscription is costed at the full connection.
TARGETS = ("served_share", "kwh_per_vehicle_day", "peak_period_share")
SHARES = ("served_share", "peak_period_share")
MONOTONE_SERVED = {**surrogate.MONOTONE_SERVED, "buffer_kwh_per_vehicle": 1}
EPS = 5e-4  # keeps the logit finite at exactly 0% and 100%
SERVICE_LEVEL = 0.99


def _scale(unit: np.ndarray, first_id: int) -> list[dict[str, float]]:
    """Map points in the unit cube onto the design space; fleet size on a log scale."""
    designs = []
    for index, point in enumerate(unit):
        design = {
            name: low + float(u) * (high - low) for u, (name, (low, high)) in zip(point, RANGES.items(), strict=True)
        }
        low, high = RANGES["size"]
        design["size"] = float(round(math.exp(math.log(low) + float(point[0]) * (math.log(high) - math.log(low)))))
        design["id"] = first_id + index
        designs.append(design)
    return designs


def sample_sobol(count: int, seed: int = 0, first_id: int = 0) -> list[dict[str, float]]:
    """Draw space-filling designs with a scrambled Sobol sequence."""
    unit = qmc.Sobol(d=len(RANGES), scramble=True, seed=seed).random(count)
    return _scale(unit, first_id)


def sample_boundary(count: int, seed: int = 0, first_id: int = 0) -> list[dict[str, float]]:
    """Draw designs that sit near the edge of having enough: the region the planner will search.

    Each starts as a space-filling design. Its grid connection is then reset to deliver 0.8 to 1.3 times
    the energy the fleet wants, and its fast chargers to deliver 0.9 to 2.5 times that energy if they ran
    all day. Values pushed outside the design space are clipped back to its edge.
    """
    rng = np.random.default_rng(seed)
    designs = sample_sobol(count, seed=seed + 1, first_id=first_id)
    for design in designs:
        wanted_kw = design["size"] * surrogate.estimated_kwh_per_vehicle_day(design) / 24.0
        site = rng.uniform(0.8, 1.3) * wanted_kw / EFFICIENCY
        design["site_limit_kw"] = float(np.clip(site, *RANGES["site_limit_kw"]))
        charger_kw = rng.uniform(0.9, 2.5) * wanted_kw
        slow_kw = design["ac_per_100"] * surrogate.AC_KW * design["size"] / 100.0
        fast_per_100 = (charger_kw - slow_kw) / design["dc_kw"] * 100.0 / design["size"]
        design["dc_per_100"] = float(np.clip(fast_per_100, *RANGES["dc_per_100"]))
    return designs


def to_model_scale(target: str, values: np.ndarray) -> np.ndarray:
    """Transform a target so that any real-valued prediction maps back into its physical range."""
    if target in SHARES:
        clipped = np.clip(values, EPS, 1.0 - EPS)
        return np.log(clipped / (1.0 - clipped))
    return np.log(np.maximum(values, 1e-6))


def from_model_scale(target: str, values: np.ndarray) -> np.ndarray:
    """Invert to_model_scale."""
    if target in SHARES:
        return 1.0 / (1.0 + np.exp(-values))
    return np.exp(values)


def matrix(rows: list[dict[str, float]]) -> np.ndarray:
    """Return the feature matrix for rows."""
    return np.array([[r[name] for name in FEATURES] for r in rows], dtype=float)


def _fit(params: dict, target: str, train: list[dict], valid: list[dict]):
    """Fit one model on the transformed target, stopping early on the validation rows."""
    import xgboost as xgb

    constraints = None
    if target == "served_share":
        constraints = "(" + ",".join(str(MONOTONE_SERVED.get(name, 0)) for name in FEATURES) + ")"
    model = xgb.XGBRegressor(
        **FIXED,
        **params,
        n_estimators=MAX_TREES,
        early_stopping_rounds=PATIENCE,
        eval_metric="mae",
        monotone_constraints=constraints,
    )
    y_train = to_model_scale(target, np.array([r[target] for r in train]))
    y_valid = to_model_scale(target, np.array([r[target] for r in valid]))
    model.fit(matrix(train), y_train, eval_set=[(matrix(valid), y_valid)], verbose=False)
    return model


def _mae(model, target: str, rows: list[dict]) -> float:
    if not rows:
        return float("nan")
    predicted = from_model_scale(target, model.predict(matrix(rows)))
    return float(np.abs(predicted - np.array([r[target] for r in rows])).mean())


def choose_params(rows: list[dict], target: str, folds: int = 5, seed: int = 0) -> tuple[dict, float]:
    """Pick hyperparameters by cross-validation grouped by design, on the training rows only."""
    ids = sorted({r["id"] for r in rows})
    np.random.default_rng(seed).shuffle(ids)
    fold_of = {ident: n % folds for n, ident in enumerate(ids)}
    best: tuple[dict, float] = ({}, float("inf"))
    for params in GRID:
        errors = []
        for fold in range(folds):
            inside = [r for r in rows if fold_of[r["id"]] != fold]
            held = [r for r in rows if fold_of[r["id"]] == fold]
            errors.append(_mae(_fit(params, target, inside, held), target, held))
        if float(np.mean(errors)) < best[1]:
            best = (params, float(np.mean(errors)))
    return best


@dataclass
class Planner:
    """The trained models and the margin the planner holds back from their service predictions."""

    models: dict
    margin: float = 0.0

    def predict(self, designs: list[dict[str, float]]) -> dict[str, np.ndarray]:
        """Return predicted outcomes, one array per target, each inside its physical range."""
        x = matrix([surrogate.derive(d) for d in designs])
        return {target: from_model_scale(target, self.models[target].predict(x)) for target in TARGETS}

    def mae(self, target: str, rows: list[dict]) -> float:
        """Return the mean absolute error on simulated rows, in the target's own units."""
        return _mae(self.models[target], target, rows)


def over_prediction_margin(planner: Planner, rows: list[dict], quantile: float = 0.9) -> float:
    """Return how much the service prediction runs high where it counts: on designs predicted to pass.

    The planner only ever accepts designs it predicts will meet the service level, so that is the group
    whose errors matter. Among validation designs with a passing prediction, this is the given quantile
    of prediction minus truth. Measuring it over all designs instead mixes in the large errors made far
    below the service level and produces a margin no design can clear.
    """
    if not rows:
        return 0.0
    predicted = planner.predict(rows)["served_share"]
    passing = predicted >= SERVICE_LEVEL
    if not passing.any():
        return 0.0
    over = predicted[passing] - np.array([r["served_share"] for r in rows])[passing]
    return float(max(0.0, np.quantile(over, quantile)))


def train(parts: dict[str, list[dict]]) -> tuple[Planner, dict]:
    """Train one model per target. Returns the planner and, per target, the errors on every split."""
    models, report = {}, {}
    for target in TARGETS:
        params, cv_error = choose_params(parts["train"], target)
        model = _fit(params, target, parts["train"], parts["valid"])
        models[target] = model
        report[target] = {
            "params": params,
            "trees": int(model.best_iteration) + 1,
            "cv_mae": round(cv_error, 5),
            **{f"{name}_mae": round(_mae(model, target, rows), 5) for name, rows in parts.items()},
        }
    planner = Planner(models)
    planner.margin = over_prediction_margin(planner, parts["valid"])
    return planner, report


def candidates(given: dict[str, float], count: int = 20_000, seed: int = 0) -> list[dict[str, float]]:
    """Return designs that share the given site, fleet and market, and differ in what the planner chooses."""
    unit = qmc.Sobol(d=len(CHOICES), scramble=True, seed=seed).random(count)
    designs = []
    for index, point in enumerate(unit):
        design = {**given, "id": index}
        for u, name in zip(point, CHOICES, strict=True):
            low, high = RANGES[name]
            design[name] = low + float(u) * (high - low)
        designs.append(design)
    return designs


def _values(designs: list[dict], outcomes: dict[str, np.ndarray], prices: Prices | None) -> np.ndarray:
    return np.array(
        [
            surrogate.contribution(design, {target: float(outcomes[target][n]) for target in TARGETS}, prices)
            for n, design in enumerate(designs)
        ]
    )


def rank(planner: Planner, pool: list[dict], top: int = 50, prices: Prices | None = None) -> list[dict]:
    """Return the most profitable designs in the pool that are predicted to meet the service level.

    A design counts as meeting it only if the prediction, less the planner's margin, still does.
    """
    outcomes = planner.predict(pool)
    values = _values(pool, outcomes, prices)
    feasible = outcomes["served_share"] - planner.margin >= SERVICE_LEVEL
    order = [n for n in np.argsort(-values) if feasible[n]][:top]
    return [
        {"design": pool[n], "predicted_served": float(outcomes["served_share"][n]), "predicted_value": float(values[n])}
        for n in order
    ]


def demand_scenarios(count: int = 40, seed: int = 0, level_sd: float = 0.08) -> list[tuple[float, float]]:
    """Return demand scenarios as (level factor, peakiness) pairs.

    The level varies by 8% (one standard deviation), a little more than the week-ahead forecast error, and
    the peak can be anywhere from slightly flatter to noticeably sharper than the learned shape.
    """
    rng = np.random.default_rng(seed)
    return [(float(rng.normal(1.0, level_sd)), float(rng.uniform(0.9, 1.2))) for _ in range(count)]


def under(design: dict[str, float], scenario: tuple[float, float]) -> dict[str, float]:
    """Return the design as it would face one demand scenario."""
    level, gamma = scenario
    return {
        **design,
        "rides_per_vehicle_day": float(
            np.clip(design["rides_per_vehicle_day"] * level, *RANGES["rides_per_vehicle_day"])
        ),
        "peak_gamma": gamma,
    }


def rank_robust(
    planner: Planner,
    pool: list[dict],
    scenarios: list[tuple[float, float]],
    top: int = 50,
    hold_share: float = 0.95,
    prices: Prices | None = None,
) -> list[dict]:
    """Return the designs with the best average contribution that hold the service level in most scenarios."""
    served = np.zeros((len(scenarios), len(pool)))
    values = np.zeros((len(scenarios), len(pool)))
    for row, scenario in enumerate(scenarios):
        faced = [under(design, scenario) for design in pool]
        outcomes = planner.predict(faced)
        served[row] = outcomes["served_share"]
        values[row] = _values(faced, outcomes, prices)
    held = (served - planner.margin >= SERVICE_LEVEL).mean(axis=0)
    mean_value = values.mean(axis=0)
    order = [n for n in np.argsort(-mean_value) if held[n] >= hold_share][:top]
    return [
        {"design": pool[n], "predicted_hold_share": float(held[n]), "predicted_value": float(mean_value[n])}
        for n in order
    ]


def sample_situations(count: int, seed: int = 0) -> list[dict[str, float]]:
    """Draw sites, fleets and markets a planner could be asked about: ones where 99% service is reachable.

    The grid connection is set to deliver 1.05 to 1.8 times the energy the fleet wants; below that no depot
    design reaches the service level and there is nothing to search.
    """
    rng = np.random.default_rng(seed)
    situations = []
    for _ in range(count):
        given = {
            "size": float(round(math.exp(rng.uniform(math.log(200.0), math.log(1800.0))))),
            "rides_per_vehicle_day": float(rng.uniform(*RANGES["rides_per_vehicle_day"])),
            "peak_gamma": float(rng.uniform(*RANGES["peak_gamma"])),
            "kwh_per_mile": float(rng.uniform(*RANGES["kwh_per_mile"])),
        }
        wanted_kw = given["size"] * surrogate.estimated_kwh_per_vehicle_day(given) / 24.0
        site = rng.uniform(1.05, 1.8) * wanted_kw / EFFICIENCY
        given["site_limit_kw"] = float(np.clip(site, *RANGES["site_limit_kw"]))
        situations.append(given)
    return situations


def searched_designs(
    planner: Planner, situations: list[dict[str, float]], top: int, first_id: int, pool_size: int = 5000
) -> list[dict[str, float]]:
    """Return the designs the planner ranks highest in each situation, with ids of their own."""
    picked = []
    for number, given in enumerate(situations):
        for entry in rank(planner, candidates(given, count=pool_size, seed=number), top=top):
            picked.append({**entry["design"], "id": first_id + len(picked)})
    return picked


def over_prediction(planner: Planner, rows: list[dict], quantile: float = 0.9) -> float:
    """Return the given quantile of predicted minus simulated service on rows, floored at zero."""
    if not rows:
        return 0.0
    over = planner.predict(rows)["served_share"] - np.array([r["served_share"] for r in rows])
    return float(max(0.0, np.quantile(over, quantile)))
