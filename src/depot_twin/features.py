"""One feature builder, used both to train the forecasts and to run them.

Training and control must compute a feature the same way, or the model is asked questions it was never
taught. So there is one function, and both call it.

The series is ride counts in fixed steps (five minutes for the controller). The quantity forecast is the
hourly rate: rides in the 60 minutes ending at a given step. A row is built at time t for a horizon h, and
predicts the rides in the hour that starts h after t.

The rule that keeps the future out: every feature of the series is a shift backwards in time of at least
zero steps. Calendar features describe the target hour, which is known in advance. Weather for the target
hour is a forecast. The label is the only value taken from after t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

SERIES_FEATURES = [
    "rate_now",
    "rate_1h_ago",
    "rate_24h_ago",
    "rate_7d_ago",
    "target_slot_last_day",
    "target_slot_last_week",
    "step_std_1h",
    "rate_mean_24h",
    "rate_max_24h",
    "rate_min_24h",
    "running_vs_last_week",
]
CALENDAR_FEATURES = ["hour", "weekday", "weekend", "holiday", "month", "minute_of_day"]
WEATHER_FEATURES = ["temperature_now", "rain_now", "temperature_target", "rain_target"]
FEATURES = SERIES_FEATURES + CALENDAR_FEATURES + WEATHER_FEATURES
BASELINES = {
    "last_hour": "rate_now",
    "same_time_last_day": "target_slot_last_day",
    "same_time_last_week": "target_slot_last_week",
}


def hourly_rate(counts: pd.Series, steps_per_hour: int) -> pd.Series:
    """Return rides in the 60 minutes ending at each step."""
    return counts.rolling(steps_per_hour).sum()


def _slot_shift(horizon_steps: int, steps_per_hour: int, period_steps: int) -> int:
    """Return how far back the latest value of the target's own slot lies, in whole periods before it.

    The target hour ends horizon + one hour after t. Its slot one period earlier is usable only if that
    moment is not after t; otherwise go back another period.
    """
    lead = horizon_steps + steps_per_hour
    periods = int(np.ceil(lead / period_steps))
    return periods * period_steps - lead


def _series_features(counts: pd.Series, horizon: int, step: int) -> pd.DataFrame:
    """Return the features taken from the ride series itself. Every one looks backwards."""
    day, week = 24 * step, 168 * step
    rate = hourly_rate(counts, step)
    out = pd.DataFrame(index=counts.index)
    out["rate_now"] = rate
    out["rate_1h_ago"] = rate.shift(step)
    out["rate_24h_ago"] = rate.shift(day)
    out["rate_7d_ago"] = rate.shift(week)
    out["target_slot_last_day"] = rate.shift(_slot_shift(horizon, step, day))
    out["target_slot_last_week"] = rate.shift(_slot_shift(horizon, step, week))
    out["step_std_1h"] = counts.rolling(step).std()
    out["rate_mean_24h"] = rate.rolling(day).mean()
    out["rate_max_24h"] = rate.rolling(day).max()
    out["rate_min_24h"] = rate.rolling(day).min()
    out["running_vs_last_week"] = rate / rate.shift(week).clip(lower=1.0)
    return out


def _calendar_features(out: pd.DataFrame, target_start: pd.DatetimeIndex) -> None:
    """Add the calendar of the hour being predicted, not of the moment the prediction is made."""
    holidays = USFederalHolidayCalendar().holidays(start=out.index.min(), end=target_start.max())
    out["hour"] = target_start.hour
    out["weekday"] = target_start.dayofweek
    out["weekend"] = (target_start.dayofweek >= 5).astype(int)
    out["holiday"] = target_start.normalize().isin(holidays).astype(int)
    out["month"] = target_start.month
    out["minute_of_day"] = target_start.hour * 60 + target_start.minute


def _weather_features(out: pd.DataFrame, target_start: pd.DatetimeIndex, weather: pd.DataFrame | None) -> None:
    """Add the weather now and the forecast for the target hour, or blanks when no weather is given."""
    if weather is None:
        for name in WEATHER_FEATURES:
            out[name] = np.nan
        return
    hourly = weather.reindex(out.index.floor("h").union(target_start.floor("h")).unique()).ffill()
    out["temperature_now"] = hourly["temperature_c"].reindex(out.index.floor("h")).to_numpy()
    out["rain_now"] = hourly["precipitation_mm"].reindex(out.index.floor("h")).to_numpy()
    out["temperature_target"] = hourly["temperature_c"].reindex(target_start.floor("h")).to_numpy()
    out["rain_target"] = hourly["precipitation_mm"].reindex(target_start.floor("h")).to_numpy()


def build(
    counts: pd.Series,
    horizon_hours: int,
    steps_per_hour: int = 12,
    weather: pd.DataFrame | None = None,
    with_label: bool = True,
) -> pd.DataFrame:
    """Return one row per step with every feature for the given horizon, and the label when asked for.

    counts is rides per step on a regular time index. weather, when given, is hourly temperature_c and
    precipitation_mm on a time index.
    """
    horizon = horizon_hours * steps_per_hour
    out = _series_features(counts, horizon, steps_per_hour)
    target_start = out.index + pd.Timedelta(hours=horizon_hours)
    _calendar_features(out, target_start)
    _weather_features(out, target_start, weather)
    if with_label:
        # The only value from after t: rides in the hour that starts one horizon ahead.
        out["label"] = hourly_rate(counts, steps_per_hour).shift(-(horizon + steps_per_hour))
    return out
