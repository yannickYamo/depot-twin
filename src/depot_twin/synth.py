"""Demand for a place with no ride history, generated from places that have one.

A donor series is taken apart into pieces that travel: the shape of its week, what holidays and rain do to
it, how its level drifts, and whatever variation is left over, kept in whole weeks so that its rhythm and
persistence survive. A new series is put together from the pieces of several donors, on the new place's own
calendar and weather, at a level the caller chooses.

What does not travel is the level. Nothing here says how many rides a new place will see; that is an input,
and anything built on the output should be run across a range of it.

Everything is hourly. `five_minute` spreads an hourly series over five-minute steps for the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

WEEK = 168
LEVEL_WINDOW = 4 * WEEK  # the slow level is a four-week centred mean
RUN_WEEKS = (8, 16)  # leftover variation is borrowed in runs of this many consecutive weeks
RAIN_LIMIT = 0.3  # a donor's fitted response to rain is clipped to this, in log points per log-mm


@dataclass
class Profile:
    """What one donor series teaches about how rides move."""

    name: str
    weekly: np.ndarray  # (168,) rides in each hour of the week over the week's mean; Monday 00:00 first
    holiday: np.ndarray  # (24,) rides on a public holiday over an ordinary day's, by hour
    rain: float  # change in log rides per unit of log(1 + mm of rain in the hour)
    residual: np.ndarray  # (weeks, 168) log of rides over everything above; whole weeks
    drift: np.ndarray  # change in log weekly level from one week to the next


def _holidays(index: pd.DatetimeIndex) -> np.ndarray:
    days = USFederalHolidayCalendar().holidays(start=index.min(), end=index.max())
    return index.normalize().isin(days)


def _hour_of_week(index: pd.DatetimeIndex) -> np.ndarray:
    return index.dayofweek * 24 + index.hour


def _whole_weeks(series: pd.Series) -> pd.Series:
    """Trim a series to whole weeks that start on a Monday at midnight."""
    first = series.index[(series.index.dayofweek == 0) & (series.index.hour == 0)][0]
    kept = series[first:]
    return kept.iloc[: len(kept) // WEEK * WEEK]


def _rain(index: pd.DatetimeIndex, weather: pd.DataFrame | None) -> np.ndarray:
    """Return log(1 + mm of rain) for each hour, or zeros when there is no weather."""
    if weather is None:
        return np.zeros(len(index))
    return np.log1p(weather["precipitation_mm"].reindex(index).fillna(0.0).to_numpy())


def extract(name: str, series: pd.Series, weather: pd.DataFrame | None = None) -> Profile:
    """Take an hourly donor series apart into the pieces a new series can be built from."""
    series = _whole_weeks(series.astype(float))
    index = series.index
    level = series.rolling(LEVEL_WINDOW, center=True, min_periods=LEVEL_WINDOW // 2).mean().clip(lower=1e-6)
    ratio = (series / level).to_numpy()
    holiday, slot = _holidays(index), _hour_of_week(index)
    weekly = np.array([ratio[(slot == h) & ~holiday].mean() for h in range(WEEK)])
    weekly /= weekly.mean()
    on_holiday = np.ones(24)
    if holiday.any():
        relative = ratio / weekly[slot]
        on_holiday = np.array([relative[holiday & (index.hour == h)].mean() for h in range(24)])
    fitted = level.to_numpy() * weekly[slot] * np.where(holiday, on_holiday[index.hour], 1.0)
    error = np.log((series.to_numpy() + 1.0) / (fitted + 1.0))
    rain = _rain(index, weather)
    slope = float(np.clip(rain @ error / max(rain @ rain, 1e-9), -RAIN_LIMIT, RAIN_LIMIT)) if rain.any() else 0.0
    weekly_level = np.log(series.to_numpy().reshape(-1, WEEK).mean(axis=1) + 1.0)
    left_over = _without_counting_noise((error - slope * rain).reshape(-1, WEEK), fitted.reshape(-1, WEEK))
    return Profile(name, weekly, on_holiday, slope, left_over, np.diff(weekly_level))


def _without_counting_noise(residual: np.ndarray, fitted: np.ndarray) -> np.ndarray:
    """Shrink a donor's leftover variation by the part that is only the luck of small counts.

    A donor with 50 rides an hour is noisy because 50 is a small number, not because its demand is
    erratic. That noise belongs to the donor's size and must not be carried to a place of another size;
    the generator adds the right amount back when it draws counts. For each hour of the week, the variance
    counting alone would give (about one over the expected count) is taken out of the variance seen.
    """
    seen = residual.var(axis=0)
    counting = (1.0 / np.maximum(fitted, 1.0)).mean(axis=0)
    keep = np.sqrt(np.clip(seen - counting, 0.0, None) / np.maximum(seen, 1e-12))
    return residual * keep


def _mixture(profiles: list[Profile], weights: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Return the weighted weekly shape, holiday pattern and rain response of several donors."""
    weekly = sum(w * p.weekly for w, p in zip(weights, profiles, strict=True))
    holiday = sum(w * p.holiday for w, p in zip(weights, profiles, strict=True))
    rain = float(sum(w * p.rain for w, p in zip(weights, profiles, strict=True)))
    return weekly / weekly.mean(), holiday, rain


def _borrowed_weeks(profiles: list[Profile], weights: np.ndarray, weeks: int, rng: np.random.Generator):
    """Return leftover variation and level drift for each week, borrowed from donors in runs of weeks.

    What makes "the same hour last week" a good forecast is that a week resembles the one before it. Weeks
    drawn one at a time would lose that, so they are borrowed in consecutive runs, a season or so long,
    each from one donor, with that donor's own drift over the same weeks.
    """
    residual, drift = np.zeros((weeks, WEEK)), np.zeros(weeks)
    week = 0
    while week < weeks:
        donor = profiles[rng.choice(len(profiles), p=weights)]
        length = min(weeks - week, len(donor.residual), int(rng.integers(RUN_WEEKS[0], RUN_WEEKS[1] + 1)))
        first = int(rng.integers(len(donor.residual) - length + 1))
        residual[week : week + length] = donor.residual[first : first + length]
        # Borrowed with a random sign: a new place is as likely to shrink over a season as to grow.
        steps = donor.drift[first : first + length - 1]
        drift[week + 1 : week + length] = rng.choice([-1.0, 1.0]) * steps
        week += length
    path = np.cumsum(drift)
    return residual.ravel(), np.repeat(path - path.mean(), WEEK)


def generate(
    profiles: list[Profile],
    start: pd.Timestamp,
    weeks: int,
    level: float,
    rng: np.random.Generator,
    weather: pd.DataFrame | None = None,
    weights: np.ndarray | None = None,
) -> pd.Series:
    """Return hourly rides for a new place: `weeks` whole weeks from `start`, `level` rides an hour on average.

    weights sets how much each donor contributes; left out, a mix is drawn at random, so that repeated
    calls give places that differ in the way the donors differ from each other.
    """
    if start.dayofweek != 0 or start.hour != 0:
        raise ValueError("a generated series starts on a Monday at midnight")
    weights = rng.dirichlet(np.ones(len(profiles))) if weights is None else np.asarray(weights) / np.sum(weights)
    index = pd.date_range(start, periods=weeks * WEEK, freq="h")
    weekly, on_holiday, rain = _mixture(profiles, weights)
    residual, drift = _borrowed_weeks(profiles, weights, weeks, rng)
    holiday = np.where(_holidays(index), on_holiday[index.hour], 1.0)
    rate = level * weekly[_hour_of_week(index)] * holiday * np.exp(rain * _rain(index, weather) + residual + drift)
    return pd.Series(rng.poisson(rate).astype(float), index=index)


def five_minute(hourly: pd.Series, rng: np.random.Generator) -> pd.Series:
    """Spread hourly rides over five-minute steps, keeping each hour's total.

    Within an hour the rate follows a straight line between neighbouring hours, and each ride falls in a
    step at random in proportion to it. Burstiness inside the hour is not modelled.
    """
    centres = np.arange(len(hourly)) + 0.5
    steps = (np.arange(len(hourly) * 12) + 0.5) / 12.0
    rate = np.maximum(np.interp(steps, centres, hourly.to_numpy()), 1e-9).reshape(-1, 12)
    share = rate / rate.sum(axis=1, keepdims=True)
    counts = np.vstack([rng.multinomial(int(n), p) for n, p in zip(hourly.to_numpy(), share, strict=True)])
    index = pd.date_range(hourly.index[0], periods=counts.size, freq="5min")
    return pd.Series(counts.ravel().astype(float), index=index)


def likeness(generated: list[pd.Series], real: pd.Series) -> dict:
    """Return how close generated series are to a real one in shape, spread and persistence.

    shape_error is the mean absolute gap between the weekly profiles, as a share of the mean hour.
    spread and persistence compare the leftover variation: its standard deviation, and how much of it
    carries from one hour to the next, one day to the next and one week to the next.
    """
    truth = extract("real", real)
    made = [extract("generated", series) for series in generated]

    def carried(profile: Profile, lag: int) -> float:
        flat = profile.residual.ravel()
        return float(np.corrcoef(flat[:-lag], flat[lag:])[0, 1])

    return {
        "shape_error": round(float(np.mean([np.abs(p.weekly - truth.weekly).mean() for p in made])), 4),
        "spread_real": round(float(truth.residual.std()), 4),
        "spread_generated": round(float(np.mean([p.residual.std() for p in made])), 4),
        "hour_to_hour_real": round(carried(truth, 1), 3),
        "hour_to_hour_generated": round(float(np.mean([carried(p, 1) for p in made])), 3),
        "day_to_day_real": round(carried(truth, 24), 3),
        "day_to_day_generated": round(float(np.mean([carried(p, 24) for p in made])), 3),
        "week_to_week_real": round(carried(truth, WEEK), 3),
        "week_to_week_generated": round(float(np.mean([carried(p, WEEK) for p in made])), 3),
    }
