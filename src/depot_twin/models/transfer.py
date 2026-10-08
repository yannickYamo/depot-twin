"""A forecast trained across cities, for a place that has no history of its own.

One model per horizon is fitted to many series at once: real ones from donor cities and generated ones for
the target. It predicts the ratio of the target hour to the same hour last week, so the size of a city
never enters as a quantity to predict. It is given only features that mean the same thing everywhere: where
the series stands against its own recent past, the clock, the day of the week, holidays, and rain. No city
name, no month, no temperature; a mild day in Chicago is a cold one in San Francisco.

One feature does carry size: the log of last week's level. It is there because of counting noise. At 100
rides an hour last week's figure is a rough guide; at 30,000 it is a precise one, and the model has to know
which it is looking at.

Bounds cannot be sized the usual way, on the place's own past errors. They are sized on the errors made in
donor cities the model was not trained on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from depot_twin.data.contracts import assert_real, is_synthetic
from depot_twin.features import SERIES_FEATURES, build
from depot_twin.models.short_horizon import GRID, Forecast, _inputs, _reference, wape

# step_std_1h needs steps shorter than an hour, and the panel is hourly.
FEATURES = [name for name in SERIES_FEATURES if name != "step_std_1h"] + [
    "hour",
    "weekday",
    "weekend",
    "holiday",
    "rain_now",
    "rain_target",
    "log_level",
]
STOP_DAYS = 28
SETTINGS = {
    "objective": "reg:squarederror",
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 7,
    "n_jobs": 2,
    "early_stopping_rounds": 40,
    "eval_metric": "mae",
}
MAX_TREES = 1500
Z_95 = 1.645  # one-sided 95% point of a normal, for the counting-noise part of a bound


def rows_for(name: str, series: pd.Series, horizon: int, weather: pd.DataFrame | None, until=None) -> pd.DataFrame:
    """Return an hourly series as model rows, keeping only rows whose label is observed by `until`.

    Each row carries a weight: last week's level over the series' own average, so that a large city does
    not drown a small one and a busy hour still counts for more than a dead one.
    """
    rows = build(series, horizon, 1, weather).dropna(subset=["label", "rate_7d_ago", "rate_mean_24h"])
    if until is not None:
        rows = rows[rows.index + pd.Timedelta(hours=horizon + 1) <= until]
    reference = _reference(rows)
    return with_level(rows).assign(series=name, weight=reference / reference.mean())


def with_level(rows: pd.DataFrame) -> pd.DataFrame:
    """Add the size feature: the log of rides in the target's slot last week."""
    return rows.assign(log_level=np.log(_reference(rows)))


def split(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cut one series' rows into training rows and its last four weeks, which decide when to stop.

    Rows a generator made are all training rows: nothing is ever stopped, calibrated or scored on them.
    """
    if "series" in rows and len(rows) and is_synthetic(str(rows["series"].iloc[0])):
        return rows, rows.iloc[0:0]
    edge = rows.index.max() - pd.Timedelta(days=STOP_DAYS)
    return rows[rows.index <= edge], rows[rows.index > edge]


def _fit_one(train: pd.DataFrame, stop: pd.DataFrame, params: dict):
    import xgboost as xgb

    assert_real(stop, "stopping")

    model = xgb.XGBRegressor(**SETTINGS, **params, n_estimators=MAX_TREES)
    model.fit(
        _inputs(train, FEATURES, True),
        train["label"] / _reference(train),
        sample_weight=train["weight"],
        eval_set=[(_inputs(stop, FEATURES, True), stop["label"] / _reference(stop))],
        sample_weight_eval_set=[stop["weight"]],
        verbose=False,
    )
    return model


def fit_pooled(train: pd.DataFrame, stop: pd.DataFrame, params: dict | None = None) -> tuple[object, dict]:
    """Fit one model to rows pooled over series. Tree settings are chosen on the stop rows unless given."""
    if params is not None:
        return _fit_one(train, stop, params), params
    best = None
    for candidate in GRID:
        model = _fit_one(train, stop, candidate)
        error = float(model.best_score)
        if best is None or error < best[0]:
            best = (error, model, candidate)
    return best[1], best[2]


def predict(model, rows: pd.DataFrame) -> np.ndarray:
    """Return expected rides in the target hour."""
    rows = rows if "log_level" in rows else with_level(rows)
    return np.maximum(0.0, model.predict(_inputs(rows, FEATURES, True)) * _reference(rows))


def _band(predicted: np.ndarray, relative: float) -> np.ndarray:
    """Return the width of a bound: a share of the prediction and counting noise, combined."""
    return np.sqrt((relative * predicted) ** 2 + Z_95**2 * predicted)


def relative_bound(actual: np.ndarray, predicted: np.ndarray, upper: bool, level: float = 0.95) -> float:
    """Return the smallest relative width whose bound holds for `level` of the rows given."""
    sign = 1.0 if upper else -1.0

    def held(relative: float) -> float:
        return float((sign * (actual - predicted) <= _band(predicted, relative)).mean())

    low, high = 0.0, 5.0
    for _ in range(40):
        middle = (low + high) / 2.0
        low, high = (low, middle) if held(middle) >= level else (middle, high)
    return high


def best_trust(errors: pd.DataFrame) -> float:
    """Return how far to move from last week's figure towards the model's, judged on places it never saw.

    Zero is "same hour last week"; one is the model as it stands. A model that transfers badly between
    the donor cities is trusted less at a new one.
    """
    actual, last_week = errors["actual"].to_numpy(), errors["last_week"].to_numpy()
    step = errors["predicted"].to_numpy() - last_week
    choices = np.linspace(0.0, 1.0, 11)
    return float(min(choices, key=lambda trust: np.abs(actual - last_week - trust * step).sum()))


@dataclass
class SiteForecast(Forecast):
    """A cross-city forecast. Its bounds are a share of the prediction plus counting noise."""

    upper_relative: float = 0.0
    lower_relative: float = 0.0
    trust: float = 1.0  # share of the way from last week's figure to the model's

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Return expected rides in the target hour."""
        last_week = _reference(rows)
        return last_week + self.trust * (predict(self.model, rows) - last_week)

    def upper(self, rows: pd.DataFrame) -> np.ndarray:
        """Return the level rides should stay under 95% of the time."""
        predicted = self.predict(rows)
        return predicted + _band(predicted, self.upper_relative)

    def lower(self, rows: pd.DataFrame) -> np.ndarray:
        """Return the level rides should stay over 95% of the time."""
        predicted = self.predict(rows)
        return np.maximum(0.0, predicted - _band(predicted, self.lower_relative))


# Rows that stay in training beside the real ones: a frame, or a function that builds the frame for a fold
# from a set of series it must not draw on. Generated demand is the second kind: each generated series is a
# mix of donor profiles, so the rows for a fold must be generated without the group that fold holds out.
Extra = pd.DataFrame | Callable[[frozenset[str]], "pd.DataFrame | None"] | None


def _extra_rows(extra: Extra, without: frozenset[str] = frozenset()) -> pd.DataFrame | None:
    return extra(without) if callable(extra) else extra


def held_out_errors(
    groups: dict[str, pd.DataFrame], extra: Extra, params: dict, like: set[str] | None = None
) -> pd.DataFrame:
    """Return actual and predicted rides for each group of series, from a model that never saw that group.

    groups maps a group (a city, or a service where there is one city) to its rows. extra is rows that stay
    in training beside them, such as generated series; when it is a function it is asked for rows that owe
    nothing to the group left out, so that group's shape cannot come back in through generated demand. Only each series' last weeks are scored, and only
    the series named in `like` when a group has any: an airport's errors say little about a whole city's.
    """
    scored = []
    for name, rows in groups.items():
        beside = _extra_rows(extra, frozenset(rows["series"].unique()))
        others = [g for other, g in groups.items() if other != name] + ([beside] if beside is not None else [])
        parts = [split(series) for frame in others for _, series in frame.groupby("series")]
        model, _ = fit_pooled(pd.concat(p[0] for p in parts), pd.concat(p[1] for p in parts), params)
        alike = rows[rows["series"].isin(like)] if like else rows
        alike = alike if len(alike) else rows
        recent = pd.concat(split(series)[1] for _, series in alike.groupby("series"))
        assert_real(recent, "calibration")
        columns = {
            "actual": recent["label"].to_numpy(),
            "predicted": predict(model, recent),
            "last_week": _reference(recent),
        }
        scored.append(pd.DataFrame(columns))
    return pd.concat(scored)


def fit_site(
    horizon: int,
    groups: dict[str, pd.DataFrame],
    extra: Extra = None,
    like: set[str] | None = None,
    params: dict | None = None,
) -> SiteForecast:
    """Fit the cross-city forecast for one horizon and size its bounds on groups it was not trained on.

    like names the donor series that resemble the place being forecast; bounds are sized on those.
    """
    beside = _extra_rows(extra)
    frames = list(groups.values()) + ([beside] if beside is not None else [])
    parts = [split(series) for frame in frames for _, series in frame.groupby("series")]
    model, params = fit_pooled(pd.concat(p[0] for p in parts), pd.concat(p[1] for p in parts), params)
    forecast = SiteForecast(horizon, model, FEATURES, params, scale_free=True)
    if len(groups) > 1:
        errors = held_out_errors(groups, extra, params, like)
        forecast.trust = best_trust(errors)
        actual = errors["actual"].to_numpy()
        predicted = (
            errors["last_week"].to_numpy() + forecast.trust * (errors["predicted"] - errors["last_week"]).to_numpy()
        )
        forecast.upper_relative = relative_bound(actual, predicted, upper=True)
        forecast.lower_relative = relative_bound(actual, predicted, upper=False)
    return forecast


def score(forecast: Forecast, held: pd.DataFrame) -> dict:
    """Score a forecast on rows it has never seen."""
    assert_real(held, "scoring")
    actual = held["label"].to_numpy()
    return {
        "wape": round(wape(actual, forecast.predict(held)), 4),
        "upper_coverage": round(float((actual <= forecast.upper(held)).mean()), 4),
        "lower_coverage": round(float((actual >= forecast.lower(held)).mean()), 4),
    }
