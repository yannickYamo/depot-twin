"""The reserve–coverage frontier: bounds sized on one block, judged on another, compared at achieved coverage."""

import numpy as np
import pytest

from depot_twin.models import reserve


def series(n: int, level: float, seed: int, spread: float = 0.1):
    rng = np.random.default_rng(seed)
    expected = level * (1.0 + spread * rng.standard_normal(n))
    return rng.poisson(np.maximum(expected, 1.0)).astype(float), expected


def test_each_bound_holds_on_the_block_it_was_sized_on_and_about_as_often_on_new_days():
    calib_actual, calib_pred = series(4000, 500.0, 1)
    actual, pred = series(4000, 500.0, 2)
    for make in (reserve.symmetric_bound, reserve.volume_bound):
        held = (actual <= make(calib_actual, calib_pred, pred, 0.95)).mean()
        assert held == pytest.approx(0.95, abs=0.02)


def test_the_frontier_rises_with_reliability_and_interpolates_at_achieved_coverage():
    calib_actual, calib_pred = series(3000, 500.0, 5)
    actual, pred = series(3000, 500.0, 6)
    curve = reserve.frontier(calib_actual, calib_pred, actual, pred, "volume", scale=1.0)
    reserves = [p["reserve"] for p in curve]
    assert reserves == sorted(reserves)
    at = reserve.reserve_at(curve, 0.95)
    assert at is not None and reserves[0] <= at <= reserves[-1]
    assert reserve.reserve_at(curve, 0.5) is None


def test_reserve_counts_vehicles_for_rides_held_above_what_came():
    actual = np.full(24, 100.0)
    upper = np.full(24, 100.0 + reserve.RIDES_PER_VEHICLE_HOUR * 10)
    assert reserve.reserve_vehicles(actual, upper, scale=1.0) == pytest.approx(10.0)
