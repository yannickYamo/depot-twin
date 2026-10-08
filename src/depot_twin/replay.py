"""Demand replayed from real days, with the forecasts a controller would have had at each moment.

Drawing demand from an average week is too kind to a controller: every Tuesday looks like every other, and
the forecast is the truth plus noise. Here the rides offered are real five-minute counts from real days,
scaled to the fleet, and what the controller is told about the next 24 hours is what the forecast models
said at that moment from the history up to it. Its forecast errors are therefore real ones.

The models forecast three horizons: 1, 6 and 24 hours. A day plan needs every hour. Each model's output is
read as a correction to last week's curve (predicted rides over rides in the same hour last week), and the
correction for the hours in between is interpolated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from depot_twin.features import build, hourly_rate
from depot_twin.models.short_horizon import HORIZONS, Forecast, _reference

STEP_MIN = 5
STEPS_PER_HOUR = 12
WEEK_STEPS = 168 * STEPS_PER_HOUR
HOURS_AHEAD = 24


def load_forecasts(folder: str | Path, prefix: str = "forecast_ratio") -> dict[int, Forecast]:
    """Read the scale-free forecast models and their bounds from disk."""
    import xgboost as xgb

    folder = Path(folder)
    bounds = json.loads((folder / f"{prefix}_bounds.json").read_text())
    forecasts = {}
    for horizon in HORIZONS:
        model = xgb.XGBRegressor()
        model.load_model(str(folder / f"{prefix}_{horizon}h.json"))
        entry = bounds[f"{horizon}h"]
        forecasts[horizon] = Forecast(
            horizon, model, entry["features"], {}, entry["upper_95"], entry["lower_05"], scale_free=True
        )
    return forecasts


def _corrections(forecasts: dict[int, Forecast], counts: pd.Series, weather: pd.DataFrame, index: pd.DatetimeIndex):
    """Return, per horizon, the predicted and upper-bound rides as ratios to last week, at each step."""
    mean, upper = {}, {}
    for horizon, forecast in forecasts.items():
        rows = build(counts, horizon, STEPS_PER_HOUR, weather, with_label=False).loc[index]
        reference = _reference(rows)
        mean[horizon] = forecast.predict(rows) / reference
        upper[horizon] = forecast.upper(rows) / reference
    return mean, upper


def _between(ratios: dict[int, np.ndarray], hours_ahead: int) -> np.ndarray:
    """Interpolate the correction for a target hour between the horizons the models cover."""
    anchors = sorted(ratios)
    k = float(np.clip(hours_ahead, anchors[0], anchors[-1]))
    for low, high in zip(anchors, anchors[1:], strict=False):
        if low <= k <= high:
            weight = (k - low) / (high - low)
            return (1.0 - weight) * ratios[low] + weight * ratios[high]
    return ratios[anchors[-1]]


def forecast_curves(
    forecasts: dict[int, Forecast], counts: pd.Series, weather: pd.DataFrame, start: pd.Timestamp, days: int
) -> dict[str, np.ndarray]:
    """Return the replay window's ride counts and, for every step, the next 24 hours as forecast then.

    The arrays are in rides of the source data, not yet scaled to a fleet: counts per step, and mean and
    upper as (steps, 24) rides per hour.
    """
    index = pd.date_range(start, periods=days * 24 * STEPS_PER_HOUR, freq=f"{STEP_MIN}min")
    rate = hourly_rate(counts, STEPS_PER_HOUR)
    mean_ratio, upper_ratio = _corrections(forecasts, counts, weather, index)
    mean = np.zeros((len(index), HOURS_AHEAD))
    upper = np.zeros((len(index), HOURS_AHEAD))
    actual = np.zeros((len(index), HOURS_AHEAD))
    for k in range(HOURS_AHEAD):
        lead = (k + 1) * STEPS_PER_HOUR  # steps from now to the end of the hour that starts k hours ahead
        last_week = np.maximum(rate.shift(WEEK_STEPS - lead).loc[index].to_numpy(), 5.0)
        mean[:, k] = last_week * _between(mean_ratio, k)
        upper[:, k] = last_week * _between(upper_ratio, k)
        actual[:, k] = rate.shift(-lead).loc[index].to_numpy()
    return {"counts": counts.loc[index].to_numpy(), "mean": mean, "upper": upper, "actual": actual}


def plain_curves(counts: pd.Series) -> dict[str, np.ndarray]:
    """Return replay curves for five-minute counts with no forecast model: the forecast is what happened.

    For rules that never read a forecast, and for comparing demand series with the forecast taken out of
    the comparison.
    """
    rate = hourly_rate(counts, STEPS_PER_HOUR)
    actual = np.column_stack([rate.shift(-(k + 1) * STEPS_PER_HOUR).ffill().to_numpy() for k in range(HOURS_AHEAD)])
    return {"counts": counts.to_numpy(), "mean": actual, "upper": actual, "actual": actual}


@dataclass
class ReplayDemand:
    """Real demand and the forecasts of it, scaled to a fleet. Plugs into the fleet simulation."""

    counts: np.ndarray  # rides offered per five-minute step
    mean: np.ndarray  # (steps, 24): expected rides per hour for the next 24 hours, as forecast at each step
    upper: np.ndarray  # the same, at the level rides should stay under 95% of the time
    actual: np.ndarray  # what the next 24 hours turned out to be; for scoring only, never shown to a rule
    fault_from_minute: float | None = None  # from this minute on, the forecasts handed out are wrong
    fault_factor: float = 1.0  # by this factor; the demand itself is untouched

    @classmethod
    def scaled(cls, curves: dict[str, np.ndarray], rides_per_day: float) -> ReplayDemand:
        """Scale source-data curves so the window offers the given number of rides a day on average."""
        days = len(curves["counts"]) * STEP_MIN / 1440.0
        scale = rides_per_day / (curves["counts"].sum() / days)
        return cls(*(curves[name] * scale for name in ("counts", "mean", "upper", "actual")))

    def offered(self, minute: float, step_min: float) -> float:
        """Return the rides offered in the step that starts at the given minute."""
        if step_min % STEP_MIN or minute % STEP_MIN:
            raise ValueError(f"replayed demand is in {STEP_MIN}-minute steps; asked for {step_min} minutes at {minute}")
        first, count = int(minute // STEP_MIN), int(step_min // STEP_MIN)
        if first + count > len(self.counts):
            raise ValueError(f"minute {minute} is past the end of the replayed window")
        return float(self.counts[first : first + count].sum())

    def ahead(self, minute: float) -> tuple[np.ndarray, np.ndarray]:
        """Return the forecast for the next 24 hours as it stood at the given minute: mean and upper."""
        step = min(int(minute // STEP_MIN), len(self.mean) - 1)
        if self.fault_from_minute is not None and minute >= self.fault_from_minute:
            return self.mean[step] * self.fault_factor, self.upper[step] * self.fault_factor
        return self.mean[step], self.upper[step]
