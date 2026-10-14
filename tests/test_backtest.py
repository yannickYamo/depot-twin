"""The rolling backtest's parts: weeks, bounds that keep up, and a mean with its range over weeks."""

import numpy as np
import pandas as pd
import pytest

from depot_twin.models import backtest


def test_origins_are_the_mondays_of_the_last_whole_weeks():
    origins = backtest.weekly_origins(
        pd.Timestamp("2026-08-31 23:00"), 3
    )  # a Monday night: the week it starts is not whole
    assert [str(o.date()) for o in origins] == ["2026-08-10", "2026-08-17", "2026-08-24"]
    assert all(o.dayofweek == 0 and o.hour == 0 for o in origins)


def test_a_fixed_bound_holds_at_its_level_on_errors_like_the_ones_it_was_sized_on():
    rng = np.random.default_rng(0)
    predicted = np.full(4000, 400.0)
    actual = rng.poisson(400.0, size=4000).astype(float)
    upper = backtest.fixed_bound(backtest.scaled(actual[:2000], predicted[:2000]), predicted[2000:])
    assert float((actual[2000:] <= upper).mean()) == pytest.approx(0.95, abs=0.015)


def test_the_adaptive_bound_recovers_when_the_level_shifts_and_the_fixed_one_does_not():
    rng = np.random.default_rng(1)
    predicted = np.full(3000, 400.0)
    calm = rng.poisson(400.0, size=1000).astype(float)
    shifted = rng.poisson(460.0, size=3000).astype(float)  # rides run 15% over the forecast from here on
    calibration = backtest.scaled(calm, predicted[:1000])
    fixed = backtest.fixed_bound(calibration, predicted)
    adaptive, rate = backtest.adaptive_bound(calibration, predicted, shifted, miss_rate=0.05, delay=2)
    held_fixed, held_adaptive = float((shifted <= fixed).mean()), float((shifted[1000:] <= adaptive[1000:]).mean())
    assert held_fixed < 0.2  # sized on the calm days, it is broken most hours
    assert held_adaptive == pytest.approx(0.95, abs=0.02)
    assert 0.0 < rate < 0.5


def test_the_adaptive_bound_uses_only_what_was_known_at_each_hour():
    rng = np.random.default_rng(2)
    predicted = np.full(200, 300.0)
    actual = rng.poisson(300.0, size=200).astype(float)
    calibration = backtest.scaled(rng.poisson(300.0, size=600).astype(float), np.full(600, 300.0))
    first, _ = backtest.adaptive_bound(calibration, predicted, actual, 0.05, delay=2)
    changed = actual.copy()
    changed[100:] += 500.0  # the future turns out differently
    second, _ = backtest.adaptive_bound(calibration, predicted, changed, 0.05, delay=2)
    assert np.array_equal(first[:102], second[:102])  # nothing before the change is known has moved
    assert not np.array_equal(first[103:], second[103:])


def test_pinball_loss_rewards_a_bound_that_is_tight_and_still_holds():
    actual = np.array([100.0, 100.0, 100.0, 100.0])
    assert backtest.pinball(actual, np.full(4, 110.0)) < backtest.pinball(actual, np.full(4, 150.0))
    assert backtest.pinball(actual, np.full(4, 110.0)) < backtest.pinball(actual, np.full(4, 99.0))


def test_a_mean_over_weeks_carries_the_range_resampling_weeks_gives_it():
    weeks = [0.08, 0.10, 0.09, 0.12, 0.07, 0.11]
    out = backtest.over_weeks(weeks)
    assert out["low"] < out["mean"] < out["high"]
    assert out["mean"] == pytest.approx(np.mean(weeks), abs=1e-4)
    assert backtest.over_weeks([0.1] * 6) == {"mean": 0.1, "low": 0.1, "high": 0.1}
