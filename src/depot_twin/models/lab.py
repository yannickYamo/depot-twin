"""The forecast lab: the ride forecast built with one fix at a time, or all of them, and scored the same way.

Each fix answers something a test found. The denominator fix answers the noise in dividing by one hour of
last week. Rolling-origin stopping answers the stop block that happened to hold a level shift. The
normalized-count arm is the fair form of the count target that lost twice. Quantile bounds with a
calibration step answer a symmetric margin that held 93% where it was sized for 95%. Bagging answers
variance. Everything else, the features, the tree settings, the blocks of days, is the reference's.

Hourly throughout, so that three cities can be scored the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from depot_twin.features import SERIES_FEATURES, _slot_shift, build, hourly_rate
from depot_twin.models import short_horizon
from depot_twin.models.short_horizon import blocks, wape

FEATURES = [f for f in SERIES_FEATURES if f != "step_std_1h"] + [
    "hour",
    "weekday",
    "weekend",
    "holiday",
    "rain_now",
    "rain_target",
]
SCALED = [f for f in FEATURES if f in SERIES_FEATURES and f != "running_vs_last_week"]
DAYPARTS = {0: "night", 6: "morning", 12: "afternoon", 18: "evening"}
Z_95 = 1.645


@dataclass(frozen=True)
class Recipe:
    """One way of building the forecast."""

    ident: str
    label: str
    denominator: str = "last_week"  # or "four_weeks"
    stopping: str = "single"  # or "rolling"
    target: str = "ratio"  # or "level"
    bounds: str = "symmetric"  # or "quantile"
    bags: int = 1


RECIPES = (
    Recipe("reference", "Reference"),
    Recipe("four_weeks", "Steadier denominator", denominator="four_weeks"),
    Recipe("rolling", "Rolling-origin stopping", stopping="rolling"),
    Recipe("level", "Normalized counts", target="level"),
    Recipe("quantile", "Calibrated quantile bounds", bounds="quantile"),
    Recipe("bagged", "Bagging", bags=5),
    # Development on San Francisco showed the quantile bound no better than the symmetric one at every horizon,
    # so the combined recipe keeps the symmetric bound; the quantile bound is reported on its own.
    Recipe("all", "All of them", denominator="four_weeks", stopping="rolling", bags=5),
)


def frame(counts: pd.Series, horizon: int, weather: pd.DataFrame | None) -> pd.DataFrame:
    """Build the reference's rows at hourly steps and add the two denominators the recipes can use."""
    rows = build(counts, horizon, 1, weather)
    rate = hourly_rate(counts, 1)
    week = 168
    shift = _slot_shift(horizon, 1, week)
    rows["slot_four_weeks"] = pd.concat([rate.shift(shift + k * week) for k in range(4)], axis=1).mean(axis=1)
    # The trailing level: the mean hourly rate over the last four weeks, known at forecast time.
    rows["level"] = rate.rolling(4 * week).mean()
    return rows


def denominator(rows: pd.DataFrame, recipe: Recipe) -> np.ndarray:
    """What the target is divided by: last week's slot, its four-week mean, or the trailing level."""
    column = {
        "ratio": {"last_week": "target_slot_last_week", "four_weeks": "slot_four_weeks"}[recipe.denominator],
        "level": "level",
    }[recipe.target]
    return np.maximum(rows[column].to_numpy(dtype=float), 5.0)


def inputs(rows: pd.DataFrame, recipe: Recipe) -> pd.DataFrame:
    """The features, with the series ones divided by the denominator so that size never enters."""
    x = rows[FEATURES].copy()
    x[SCALED] = x[SCALED].div(denominator(rows, recipe), axis=0)
    return x


def _model(params: dict, trees: int, seed: int, early: bool, objective: str = "reg:squarederror", **extra):
    import xgboost as xgb

    settings = {**short_horizon.FIXED, "objective": objective, "random_state": seed, **extra}
    stop = {"early_stopping_rounds": short_horizon.PATIENCE, "eval_metric": "mae"} if early else {}
    return xgb.XGBRegressor(**settings, **params, n_estimators=trees, **stop)


def _fit(model, rows: pd.DataFrame, recipe: Recipe, stop: pd.DataFrame | None = None):
    y = rows["label"] / denominator(rows, recipe)
    extra = {}
    if stop is not None:
        extra = {"eval_set": [(inputs(stop, recipe), stop["label"] / denominator(stop, recipe))], "verbose": False}
    return model.fit(inputs(rows, recipe), y, sample_weight=denominator(rows, recipe), **extra)


def choose_trees(train: pd.DataFrame, recipe: Recipe, params: dict, folds: int = 4) -> int:
    """Rolling-origin stopping: the median best tree count over expanding folds of the training block."""
    cuts = np.linspace(0, len(train), folds + 2).astype(int)
    best = []
    for fold in range(1, folds + 1):
        past, ahead = train.iloc[: cuts[fold]], train.iloc[cuts[fold] : cuts[fold + 1]]
        model = _fit(_model(params, short_horizon.MAX_TREES, 7, True), past, recipe, stop=ahead)
        best.append(int(model.best_iteration) + 1)
    return int(np.median(best))


@dataclass
class Fitted:
    """A fitted recipe at one horizon: its point models, its bound models and their calibration."""

    recipe: Recipe
    horizon: int
    models: list = field(default_factory=list)
    upper_models: list = field(default_factory=list)
    lower_models: list = field(default_factory=list)
    symmetric: tuple[float, float] = (0.0, 0.0)
    correction: dict[str, tuple[float, float]] = field(default_factory=dict)  # by daypart: (upper, lower)
    trees: int = 0

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Expected rides in the target hour: the bagged mean, scale restored."""
        scale = denominator(rows, self.recipe)
        raw = np.mean([m.predict(inputs(rows, self.recipe)) for m in self.models], axis=0)
        return np.maximum(0.0, raw * scale)

    def _bound(self, rows: pd.DataFrame, upper: bool) -> np.ndarray:
        predicted = self.predict(rows)
        if self.recipe.bounds == "symmetric":
            width = self.symmetric[0 if upper else 1] * np.sqrt(predicted + 1.0)
            return np.maximum(0.0, predicted + width)
        models = self.upper_models if upper else self.lower_models
        raw = np.mean([m.predict(inputs(rows, self.recipe)) for m in models], axis=0) * denominator(rows, self.recipe)
        part = rows.index.hour.map(daypart).to_numpy()
        factor = np.array([self.correction[p][0 if upper else 1] for p in part])
        return np.maximum(0.0, raw * factor)

    def upper(self, rows: pd.DataFrame) -> np.ndarray:
        """The level rides should stay under 95% of the time."""
        return self._bound(rows, True)

    def lower(self, rows: pd.DataFrame) -> np.ndarray:
        """The level rides should stay over 95% of the time."""
        return self._bound(rows, False)


def daypart(hour: int) -> str:
    """Night, morning, afternoon or evening."""
    return DAYPARTS[max(k for k in DAYPARTS if k <= hour)]


def fit(recipe: Recipe, parts: dict[str, pd.DataFrame], horizon: int) -> Fitted:
    """Fit a recipe at one horizon on the training block, stop or choose trees, then size its bounds."""
    params = REFERENCE_PARAMS[horizon]  # the reference's tree settings, held fixed for every recipe
    fitted = Fitted(recipe, horizon)
    trees = choose_trees(parts["train"], recipe, params) if recipe.stopping == "rolling" else None
    for bag in range(recipe.bags):
        seed = 7 + bag
        if trees is None:
            model = _fit(
                _model(params, short_horizon.MAX_TREES, seed, True), parts["train"], recipe, stop=parts["stop"]
            )
            fitted.trees = int(model.best_iteration) + 1
        else:
            model = _fit(_model(params, trees, seed, False), parts["train"], recipe)
            fitted.trees = trees
        fitted.models.append(model)
        if recipe.bounds == "quantile":
            count = fitted.trees
            for alpha, store in ((0.95, fitted.upper_models), (0.05, fitted.lower_models)):
                store.append(
                    _fit(
                        _model(params, count, seed, False, "reg:quantileerror", quantile_alpha=alpha),
                        parts["train"],
                        recipe,
                    )
                )
    calibrate(fitted, parts["calibrate"])
    return fitted


def calibrate(fitted: Fitted, rows: pd.DataFrame) -> None:
    """Size the bounds on the calibration block, which the models never trained on."""
    actual, predicted = rows["label"].to_numpy(), fitted.predict(rows)
    if fitted.recipe.bounds == "symmetric":
        scaled = (actual - predicted) / np.sqrt(predicted + 1.0)
        fitted.symmetric = (float(np.quantile(scaled, 0.95)), float(np.quantile(scaled, 0.05)))
        return
    # A quantile model is not calibrated by itself. Each bound is scaled, by time of day, so that it holds
    # 95% of the time on days it never saw.
    scale = denominator(rows, fitted.recipe)
    raw_upper = np.mean([m.predict(inputs(rows, fitted.recipe)) for m in fitted.upper_models], axis=0) * scale
    raw_lower = np.mean([m.predict(inputs(rows, fitted.recipe)) for m in fitted.lower_models], axis=0) * scale
    part = rows.index.hour.map(daypart).to_numpy()
    for name in DAYPARTS.values():
        here = part == name
        up = np.quantile(actual[here] / np.maximum(raw_upper[here], 1.0), 0.95)
        low = np.quantile(actual[here] / np.maximum(raw_lower[here], 1.0), 0.05)
        fitted.correction[name] = (float(up), float(low))


REFERENCE_PARAMS = {
    1: {"max_depth": 6, "min_child_weight": 1},
    6: {"max_depth": 4, "min_child_weight": 1},
    24: {"max_depth": 4, "min_child_weight": 1},
}
RIDES_PER_VEHICLE_HOUR = 60.0 / 23.0


def score(fitted: Fitted, held: pd.DataFrame, fleet: int = 500, rides_per_vehicle_day: float = 25.0) -> dict:
    """Error, coverage, sharpness as vehicles in reserve, and the error on each day for paired comparisons."""
    actual, predicted, upper = held["label"].to_numpy(), fitted.predict(held), fitted.upper(held)
    scale = fleet * rides_per_vehicle_day / (actual.sum() / (len(actual) / 24.0))
    days = pd.Series(np.abs(actual - predicted), index=held.index).groupby(held.index.date).sum()
    totals = pd.Series(actual, index=held.index).groupby(held.index.date).sum()
    return {
        "error": round(wape(actual, predicted), 4),
        "same_hour_last_week": round(wape(actual, held["target_slot_last_week"].to_numpy()), 4),
        "upper_bound_held": round(float((actual <= upper).mean()), 4),
        "bound_above_forecast": round(float((upper - predicted).sum() / predicted.sum()), 4),
        "reserve_vehicles": round(float(np.clip(upper - actual, 0, None).mean() * scale / RIDES_PER_VEHICLE_HOUR), 1),
        "trees": fitted.trees,
        "daily_error": (days / totals).round(4).tolist(),
    }


def paired_interval(mine: list[float], theirs: list[float], block: int = 7, draws: int = 2000, seed: int = 0) -> dict:
    """The mean daily difference (mine minus theirs) with a 90% block-bootstrap interval, weeks as blocks."""
    delta = np.array(mine) - np.array(theirs)
    rng = np.random.default_rng(seed)
    starts = np.arange(0, max(1, len(delta) - block + 1))
    means = []
    for _ in range(draws):
        picked = np.concatenate(
            [delta[s : s + block] for s in rng.choice(starts, size=max(1, len(delta) // block), replace=True)]
        )
        means.append(picked.mean())
    return {
        "mean": round(float(delta.mean()), 4),
        "low": round(float(np.quantile(means, 0.05)), 4),
        "high": round(float(np.quantile(means, 0.95)), 4),
    }


def cut_before(rows: pd.DataFrame, horizon: int, test_from: pd.Timestamp, until: pd.Timestamp | None) -> dict:
    """Blocks for a test window chosen in advance: calibrate and stop are the 28 days each before it, train is earlier."""
    lead = pd.Timedelta(hours=horizon + 1)
    before = rows[rows.index + lead <= test_from]
    calibrate_from = test_from - pd.Timedelta(days=short_horizon.CALIBRATION_DAYS)
    stop_from = calibrate_from - pd.Timedelta(days=short_horizon.STOP_DAYS)
    held = rows[rows.index >= test_from]
    if until is not None:
        held = held[held.index + lead <= until]
    return {
        "train": short_horizon.thinned(before[before.index + lead <= stop_from]),
        "stop": before[(before.index >= stop_from) & (before.index + lead <= calibrate_from)],
        "calibrate": before[before.index >= calibrate_from],
        "holdout": held,
    }


def run_city(
    counts: pd.Series,
    weather: pd.DataFrame | None,
    horizons=(1, 6, 24),
    recipes=RECIPES,
    until: pd.Timestamp | None = None,
    test_from: pd.Timestamp | None = None,
) -> dict:
    """Fit every recipe at every horizon on one city and score it on its held-out days.

    With `test_from`, the days from that moment are the test and the blocks are cut from the days before;
    otherwise the series' own last 60 days are the test, as in E7b.
    """
    out = {}
    for horizon in horizons:
        rows = frame(counts, horizon, weather).dropna(
            subset=["label", "rate_7d_ago", "rate_mean_24h", "slot_four_weeks", "level"]
        )
        parts = blocks(rows, horizon) if test_from is None else cut_before(rows, horizon, test_from, until)
        for recipe in recipes:
            fitted = fit(recipe, parts, horizon)
            out[f"{recipe.ident}_{horizon}h"] = score(fitted, parts["holdout"])
    return out
