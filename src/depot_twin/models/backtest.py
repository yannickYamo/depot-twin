"""A rolling backtest: many weeks, each forecast from the data before it, with bounds that keep up.

One held-out window cannot tell a model's skill from the window's luck. Here every week in a long run of
weeks is forecast by a model fitted on the days before it, the error is read week by week, and the
uncertainty on a mean is taken by resampling whole weeks, since hours inside a week are not independent.

Three ways of setting the upper bound are compared on the same forecasts:

- fixed: a quantile of the scaled error on the four weeks before the first test week, never updated;
- rolling: the same quantile, taken again each week from the four weeks before it;
- adaptive: the quantile level itself is moved after every hour, up when the bound was broken and down
  when it held, so that the share of hours over the bound is pulled to the level asked for whatever the
  series does (adaptive conformal inference, Gibbs and Candes 2021).

A bound is always built from errors already observed at the moment it is used: an error is known one
hour after the hour it belongs to has ended.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LEVEL = 0.95
ADAPT = 0.005  # how far one hour moves the adaptive level
WINDOW_HOURS = 28 * 24


def weekly_origins(last: pd.Timestamp, weeks: int) -> list[pd.Timestamp]:
    """The Monday midnights that start the last `weeks` whole weeks ending at or before `last`."""
    end = (last + pd.Timedelta(hours=1)).normalize()
    end -= pd.Timedelta(days=end.dayofweek)
    return [end - pd.Timedelta(weeks=k) for k in range(weeks, 0, -1)]


def scaled(actual: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """The error in units of counting noise, so that a quiet hour and a busy one share a scale."""
    return (actual - predicted) / np.sqrt(predicted + 1.0)


def bound(predicted: np.ndarray, width: float | np.ndarray) -> np.ndarray:
    """A forecast plus a width in the same units as `scaled`."""
    return np.maximum(0.0, predicted + width * np.sqrt(predicted + 1.0))


def fixed_bound(calibration: np.ndarray, predicted: np.ndarray, level: float = LEVEL) -> np.ndarray:
    """The upper bound from one quantile of the calibration errors."""
    return bound(predicted, float(np.quantile(calibration, level)))


def adaptive_bound(
    calibration: np.ndarray,
    predicted: np.ndarray,
    actual: np.ndarray,
    miss_rate: float,
    delay: int,
    level: float = LEVEL,
    adapt: float = ADAPT,
) -> tuple[np.ndarray, float]:
    """The upper bound hour by hour, with the level moved by what has been observed; returns it and the rate reached.

    `miss_rate` is the share of hours the bound is currently allowed to be broken in; it starts at one less
    the level. `delay` is how many hours pass before an hour's outcome is known: its error joins the
    window, and its hit or miss moves the rate, only then. Run it over one unbroken sequence of hours.
    """
    window = list(calibration[-WINDOW_HOURS:])
    upper = np.zeros(len(predicted))
    for t in range(len(predicted)):
        known = t - delay
        if known >= 0:
            missed = float(actual[known] > upper[known])
            miss_rate += adapt * ((1.0 - level) - missed)
            window.append(float(scaled(actual[known : known + 1], predicted[known : known + 1])[0]))
            window = window[-WINDOW_HOURS:]
        at = 1.0 - float(np.clip(miss_rate, 0.001, 0.5))
        upper[t] = bound(predicted[t : t + 1], float(np.quantile(window, at)))[0]
    return upper, miss_rate


def pinball(actual: np.ndarray, upper: np.ndarray, level: float = LEVEL) -> float:
    """The quantile loss of a bound at its level, in rides: low when the bound is tight and still holds."""
    over = actual - upper
    return float(np.mean(np.where(over > 0, level * over, (level - 1.0) * over)))


def wape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Total absolute error over total rides."""
    return float(np.abs(actual - predicted).sum() / max(actual.sum(), 1.0))


def over_weeks(values: list[float], draws: int = 2000, seed: int = 0) -> dict:
    """A mean over weeks with the range that resampling whole weeks gives it (5th to 95th percentile)."""
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = array[rng.integers(0, len(array), size=(draws, len(array)))].mean(axis=1)
    return {
        "mean": round(float(array.mean()), 4),
        "low": round(float(np.quantile(means, 0.05)), 4),
        "high": round(float(np.quantile(means, 0.95)), 4),
    }
