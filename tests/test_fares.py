"""The price model: the service's price structure, levelled on the published average, with busy pricing from the run."""

import numpy as np
import pytest

from depot_twin import fares


def steps(served: float, on_road: float, n: int = 12) -> np.ndarray:
    """Five-minute steps of (minute, offered, served, on_road, at_depot) at one level of use."""
    return np.array([[5.0 * k, served, served, on_road, 0.0] for k in range(n)])


def test_the_quiet_price_of_the_filed_trip_is_the_published_average():
    model = fares.PriceModel()
    assert model.quiet() == pytest.approx(fares.PUBLISHED_AVERAGE_FARE)
    # Longer and slower trips pay more; the scaled rates keep the survey's proportions.
    assert model.quiet(miles=2 * fares.PAID_TRIP_MILES) > model.quiet()
    assert model.quiet(minutes=30.0) > model.quiet()
    rates = model.describe()["rates_scaled"]
    assert rates["per_mile"] / rates["base"] == pytest.approx(1.66 / 9.52, rel=1e-3)


def test_busy_pricing_is_flat_below_the_threshold_and_capped_at_full_use():
    model = fares.PriceModel()
    assert model.multiplier(np.array([0.0, 0.5, 0.8])).tolist() == [1.0, 1.0, 1.0]
    assert model.multiplier(np.array([1.0]))[0] == pytest.approx(model.busy_cap)
    assert 1.0 < model.multiplier(np.array([0.9]))[0] < model.busy_cap


def test_busy_pricing_moves_the_price_between_steps_and_leaves_the_average_on_the_published_fare():
    model = fares.PriceModel()
    # 100 vehicles on the road can serve 100 * 5 / 23 rides in a five-minute step; a quarter of that is quiet.
    quiet = steps(served=5.0, on_road=100.0)
    full = steps(served=100.0 * 5.0 / 23.0, on_road=100.0)
    assert model.busy_share(quiet).max() < model.busy_threshold
    assert model.busy_share(full).min() == pytest.approx(1.0)
    mixed = np.vstack([quiet, full])
    prices = model.prices(mixed)
    assert prices[len(quiet) :].min() == pytest.approx(model.busy_cap * prices[: len(quiet)].max())
    for run in (quiet, full, mixed):
        assert model.revenue(run) / run[:, 2].sum() == pytest.approx(fares.PUBLISHED_AVERAGE_FARE)


def test_a_depot_that_starves_its_road_is_not_paid_more_per_ride_for_it():
    model = fares.PriceModel()
    healthy = steps(served=10.0, on_road=100.0)
    starved = steps(served=40.0 * 5.0 / 23.0, on_road=40.0)  # fewer vehicles out, every one of them full
    per_ride = lambda run: model.revenue(run) / run[:, 2].sum()  # noqa: E731
    assert per_ride(starved) == pytest.approx(per_ride(healthy))
