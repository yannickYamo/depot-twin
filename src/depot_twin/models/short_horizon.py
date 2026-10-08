"""Ride forecasts for the controller: one model per horizon, with calibrated bounds.

The controller plans against the upper bound of demand, not the expected value, so a forecast here is two
things: a prediction and a statement of how far above it the truth could be. The second is measured, not
assumed: on a block of days the model never trained on, see how wrong it was, and use that.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from depot_twin.features import BASELINES, FEATURES, SERIES_FEATURES, WEATHER_FEATURES, build

HORIZONS = (1, 6, 24)
HOLDOUT_DAYS, CALIBRATION_DAYS, STOP_DAYS = 60, 28, 28
TRAIN_EVERY = 3  # on five-minute rows, train on every third: neighbouring hourly sums overlap almost entirely
GRID = [{"max_depth": depth, "min_child_weight": weight} for depth in (4, 6) for weight in (1, 5)]
FIXED = {
    "objective": "count:poisson",
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 7,
    "n_jobs": 4,
}
CV_TREES = 300
MAX_TREES, PATIENCE = 3000, 60


def wape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Return total absolute error over total rides."""
    return float(np.abs(actual - predicted).sum() / actual.sum())


def blocks(frame: pd.DataFrame, horizon_hours: int) -> dict[str, pd.DataFrame]:
    """Cut a feature frame into train, stop, calibrate and holdout blocks, in time order.

    A row belongs to a block only if its label is observed inside that block. Rows whose label reaches
    past the block's end are dropped, so nothing observed in one block is a label in another.
    """
    rows = frame.dropna(subset=["label", "rate_7d_ago", "rate_mean_24h"])
    label_end = rows.index + pd.Timedelta(hours=horizon_hours + 1)
    end = rows.index.max() + pd.Timedelta(hours=horizon_hours + 1)
    holdout = end - pd.Timedelta(days=HOLDOUT_DAYS)
    calibrate = holdout - pd.Timedelta(days=CALIBRATION_DAYS)
    stop = calibrate - pd.Timedelta(days=STOP_DAYS)
    edges = {
        "train": (None, stop),
        "stop": (stop, calibrate),
        "calibrate": (calibrate, holdout),
        "holdout": (holdout, end),
    }
    out = {}
    for name, (low, high) in edges.items():
        inside = label_end <= high
        if low is not None:
            inside &= rows.index >= low
        out[name] = rows[inside]
    out["train"] = thinned(out["train"])
    return out


def thinned(train: pd.DataFrame) -> pd.DataFrame:
    """Training rows with the overlap between neighbours taken out, where there is any.

    Rows a few minutes apart carry labels that are almost the same hour, so every third is enough. Rows an
    hour apart do not overlap at all: taking every third of those would train on eight hours of the day
    and never see the other sixteen, so an hourly series is kept whole.
    """
    if len(train) < 2:
        return train
    step = pd.Series(train.index).diff().median()
    return train.iloc[::TRAIN_EVERY] if step < pd.Timedelta(hours=1) else train


REFERENCE = "target_slot_last_week"
# Divided by the reference in a scale-free model. The last series feature is already a ratio.
SCALED = [name for name in SERIES_FEATURES if name != "running_vs_last_week"]


def _reference(rows: pd.DataFrame) -> np.ndarray:
    """Return rides in the target's slot last week, floored so that a dead hour cannot blow a ratio up."""
    return np.maximum(rows[REFERENCE].to_numpy(), 5.0)


def _inputs(rows: pd.DataFrame, features: list[str], scale_free: bool) -> pd.DataFrame:
    """Return the model's inputs: the features as they are, or with the series divided by last week."""
    x = rows[features]
    if not scale_free:
        return x
    x = x.copy()
    scaled = [name for name in SCALED if name in features]
    x[scaled] = x[scaled].div(_reference(rows), axis=0)
    return x


def _model(params: dict, trees: int, early: bool, scale_free: bool = False):
    import xgboost as xgb

    extra = {"early_stopping_rounds": PATIENCE, "eval_metric": "mae"} if early else {}
    fixed = {**FIXED, "objective": "reg:squarederror"} if scale_free else FIXED
    return xgb.XGBRegressor(**fixed, **params, n_estimators=trees, **extra)


def _train(model, rows: pd.DataFrame, features: list[str], scale_free: bool, stop: pd.DataFrame | None = None):
    """Fit on counts, or on ratios to last week weighted by last week's level."""
    extra = {}
    if stop is not None:
        stop_y = stop["label"] / _reference(stop) if scale_free else stop["label"]
        extra = {"eval_set": [(_inputs(stop, features, scale_free), stop_y)], "verbose": False}
    if scale_free:
        reference = _reference(rows)
        return model.fit(_inputs(rows, features, True), rows["label"] / reference, sample_weight=reference, **extra)
    return model.fit(_inputs(rows, features, False), rows["label"], **extra)


def _predict(model, rows: pd.DataFrame, features: list[str], scale_free: bool) -> np.ndarray:
    raw = model.predict(_inputs(rows, features, scale_free))
    return np.maximum(0.0, raw * _reference(rows)) if scale_free else raw


def choose_params(train: pd.DataFrame, features: list[str], folds: int = 4, scale_free: bool = False) -> dict:
    """Pick hyperparameters by expanding-window cross-validation: each fold trains on the past only."""
    cuts = np.linspace(0, len(train), folds + 2).astype(int)
    best, best_error = GRID[0], float("inf")
    for params in GRID:
        errors = []
        for fold in range(1, folds + 1):
            past, ahead = train.iloc[: cuts[fold]], train.iloc[cuts[fold] : cuts[fold + 1]]
            model = _train(_model(params, CV_TREES, False, scale_free), past, features, scale_free)
            errors.append(wape(ahead["label"].to_numpy(), _predict(model, ahead, features, scale_free)))
        if float(np.mean(errors)) < best_error:
            best, best_error = params, float(np.mean(errors))
    return best


@dataclass
class Forecast:
    """A fitted model for one horizon, with the measured bounds on its error."""

    horizon_hours: int
    model: object
    features: list[str]
    params: dict
    upper_95: float = 0.0  # scaled error not exceeded 95% of the time on the calibration block
    lower_05: float = 0.0
    scale_free: bool = False  # the model predicts the ratio to the same time last week

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Return expected rides in the target hour."""
        return _predict(self.model, rows, self.features, self.scale_free)

    def upper(self, rows: pd.DataFrame) -> np.ndarray:
        """Return the bound the controller plans against: rides will be under this 95% of the time."""
        predicted = self.predict(rows)
        return predicted + self.upper_95 * np.sqrt(predicted + 1.0)

    def lower(self, rows: pd.DataFrame) -> np.ndarray:
        """Return the bound rides will be over 95% of the time."""
        predicted = self.predict(rows)
        return np.maximum(0.0, predicted + self.lower_05 * np.sqrt(predicted + 1.0))


def fit(
    parts: dict[str, pd.DataFrame], horizon_hours: int, features: list[str] | None = None, scale_free: bool = False
) -> Forecast:
    """Choose settings on the training block, set the trees on the stop block, calibrate on the next."""
    features = features or FEATURES
    params = choose_params(parts["train"], features, scale_free=scale_free)
    model = _train(
        _model(params, MAX_TREES, True, scale_free), parts["train"], features, scale_free, stop=parts["stop"]
    )
    forecast = Forecast(horizon_hours, model, features, params, scale_free=scale_free)
    predicted = forecast.predict(parts["calibrate"])
    # Errors grow with the level of demand, roughly as its square root, so they are scaled before pooling.
    scaled = (parts["calibrate"]["label"].to_numpy() - predicted) / np.sqrt(predicted + 1.0)
    forecast.upper_95 = float(np.quantile(scaled, 0.95))
    forecast.lower_05 = float(np.quantile(scaled, 0.05))
    return forecast


def best_baseline(stop: pd.DataFrame) -> str:
    """Return the name of the naive forecast with the lowest error on the stop block."""
    label = stop["label"].to_numpy()
    return min(BASELINES, key=lambda name: wape(label, stop[BASELINES[name]].to_numpy()))


def evaluate(forecast: Forecast, parts: dict[str, pd.DataFrame]) -> dict:
    """Score a forecast once on the held-out block."""
    held = parts["holdout"]
    actual = held["label"].to_numpy()
    predicted = forecast.predict(held)
    baseline = best_baseline(parts["stop"])
    baseline_error = wape(actual, held[BASELINES[baseline]].to_numpy())
    peak = actual >= np.quantile(actual, 0.9)
    gains = forecast.model.get_booster().get_score(importance_type="gain")
    total = sum(gains.values())
    return {
        "rows": {name: len(part) for name, part in parts.items()},
        "params": forecast.params,
        "trees": int(forecast.model.best_iteration) + 1,
        "model_wape": round(wape(actual, predicted), 4),
        "baseline": baseline,
        "baseline_wape": round(baseline_error, 4),
        "all_baselines_wape": {
            name: round(wape(actual, held[column].to_numpy()), 4) for name, column in BASELINES.items()
        },
        "error_removed": round(1.0 - wape(actual, predicted) / baseline_error, 4),
        "upper_95_coverage": round(float((actual <= forecast.upper(held)).mean()), 4),
        "interval_90_coverage": round(
            float(((actual <= forecast.upper(held)) & (actual >= forecast.lower(held))).mean()), 4
        ),
        "peak_signed_error": round(float((predicted[peak] - actual[peak]).sum() / actual[peak].sum()), 4),
        "top_features": sorted(((k, round(v / total, 3)) for k, v in gains.items()), key=lambda kv: -kv[1])[:5],
    }


def run(
    counts: pd.Series, steps_per_hour: int, weather: pd.DataFrame | None, scale_free: bool = False
) -> tuple[dict[int, Forecast], dict]:
    """Fit and score a forecast per horizon, and the same without weather. Returns the models and the report."""
    forecasts, report = {}, {}
    without_weather = [name for name in FEATURES if name not in WEATHER_FEATURES]
    for horizon in HORIZONS:
        parts = blocks(build(counts, horizon, steps_per_hour, weather), horizon)
        forecast = fit(parts, horizon, scale_free=scale_free)
        forecasts[horizon] = forecast
        report[f"{horizon}h"] = evaluate(forecast, parts)
        plain = fit(parts, horizon, without_weather, scale_free=scale_free)
        report[f"{horizon}h"]["without_weather_wape"] = round(
            wape(parts["holdout"]["label"].to_numpy(), plain.predict(parts["holdout"])), 4
        )
    return forecasts, report
