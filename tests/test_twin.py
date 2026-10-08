import numpy as np
import pytest

from depot_twin import VehicleModel
from depot_twin.twin import ChargeCurveIdentifier, EnergyIdentifier, relative_error


def feed(identifier, true_drive, true_load, steps=400, seed=0):
    rng = np.random.default_rng(seed)
    vehicles = np.arange(len(true_drive))
    for _ in range(steps):
        miles = rng.uniform(0.2, 3.5, size=len(vehicles))
        identifier.record(vehicles, miles, 0.25, miles * true_drive + true_load * 0.25)


def test_estimates_move_from_the_prior_to_the_truth():
    true_drive, true_load = np.array([0.33, 0.27, 0.30]), np.array([2.2, 1.8, 1.7])
    prior_drive, prior_load = np.full(3, 0.30), np.full(3, 2.0)
    identifier = EnergyIdentifier(prior_drive, prior_load, np.full(3, 90.0))
    # About three weeks of readings for one vehicle; the always-on load is the slower of the two to pin down.
    feed(identifier, true_drive, true_load, steps=2000)
    assert relative_error(identifier.drive_kwh_per_mile, true_drive).max() < 0.03
    assert relative_error(identifier.always_on_kw, true_load).max() < 0.05


def test_no_readings_leaves_the_prior_alone():
    identifier = EnergyIdentifier(np.array([0.3, 0.3]), np.array([2.0, 2.0]), np.full(2, 90.0))
    identifier.record(np.array([0]), np.array([2.0]), 0.25, np.array([1.2]))
    assert identifier.drive_kwh_per_mile[1] == 0.3 and identifier.always_on_kw[1] == 2.0
    assert list(identifier.readings) == [1, 0]


def test_a_noisier_gauge_learns_more_slowly():
    truth_drive, truth_load = np.array([0.36]), np.array([2.4])
    errors = []
    for noise in (0.0005, 0.005):
        identifier = EnergyIdentifier(np.array([0.30]), np.array([2.0]), np.array([90.0]), soc_noise=noise)
        feed(identifier, truth_drive, truth_load, steps=60)
        errors.append(float(relative_error(identifier.drive_kwh_per_mile, truth_drive)[0]))
    assert errors[0] < errors[1]


def test_same_seed_same_estimate():
    def run():
        identifier = EnergyIdentifier(np.array([0.30]), np.array([2.0]), np.array([90.0]), seed=4)
        feed(identifier, np.array([0.33]), np.array([2.1]), steps=50)
        return identifier.theta.copy()

    assert (run() == run()).all()


def test_charge_curve_ignores_power_limited_readings():
    car = VehicleModel("car", 90, max_dc_kw=100, max_ac_kw=11)
    curves = ChargeCurveIdentifier()
    for _ in range(40):
        curves.record(car, 0.32, 60.0, 60.0)  # got everything it could take
        curves.record(car, 0.32, 20.0, 60.0)  # the site was short of power
    assert curves.curve("car") == [(pytest.approx(0.325), 60.0)]


def test_charge_curve_needs_enough_readings():
    car = VehicleModel("car", 90, max_dc_kw=100, max_ac_kw=11)
    curves = ChargeCurveIdentifier()
    for _ in range(5):
        curves.record(car, 0.5, 50.0, 50.0)
    assert curves.curve("car") == []
    assert curves.curve("unknown") == []
