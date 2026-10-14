import numpy as np
import pytest

from depot_twin import ChargerBank, DepotConfig
from depot_twin.economics import Prices, daily_contribution, energy_by_period, fixed_cost_per_day, tariff_period
from depot_twin.first_version import surrogate


def test_designs_stay_inside_their_ranges_and_are_reproducible():
    designs = surrogate.sample_designs(200, seed=3)
    assert designs == surrogate.sample_designs(200, seed=3)
    for design in designs:
        for name, (low, high) in surrogate.RANGES.items():
            assert low <= design[name] <= high


def test_derived_features_use_inputs_only():
    design = surrogate.sample_designs(1, seed=1)[0]
    derived = surrogate.derive(design)
    assert set(derived) - set(design) == set(surrogate.DERIVED + surrogate.EXTRA_DERIVED)
    assert derived["site_kw_per_vehicle"] == pytest.approx(design["site_limit_kw"] / design["size"])
    assert 0.0 <= surrogate.hand_estimate(design) <= 1.0


def rows_for(count=400):
    designs = surrogate.sample_designs(count, seed=5)
    first = [{**surrogate.derive(d), "seed": 0, "served_share": 1.0} for d in designs]
    second = [{**surrogate.derive(d), "seed": 1, "served_share": 0.9} for d in designs[:50]]
    return first + second


def test_split_never_puts_one_design_on_two_sides():
    parts = surrogate.split(rows_for())
    ids = {name: {r["id"] for r in part} for name, part in parts.items()}
    names = list(ids)
    for a in names:
        for b in names:
            if a < b:
                assert not ids[a] & ids[b]
    assert sum(len(part) for part in parts.values()) == 450


def test_gap_band_is_kept_out_of_training_and_validation():
    parts = surrogate.split(rows_for())
    low, high = surrogate.GAP_BAND
    assert parts["gap"] and all(low <= r["size"] <= high for r in parts["gap"])
    for name in ("train", "valid", "test"):
        assert not any(low <= r["size"] <= high for r in parts[name])


def test_noise_floor_is_the_gap_between_two_runs_of_one_design():
    assert surrogate.noise_floor(rows_for(), "served_share") == pytest.approx(0.1)


def test_only_grid_and_battery_are_constrained():
    assert set(surrogate.MONOTONE_SERVED) <= set(surrogate.FEATURES)
    assert all(direction == 1 for direction in surrogate.MONOTONE_SERVED.values())


def test_equipment_scales_with_the_fleet():
    design = {**surrogate.sample_designs(1, seed=2)[0], "size": 1000.0, "dc_per_100": 10.0, "ac_per_100": 0.0}
    bought = surrogate.equipment(design)
    assert [(b.kind, b.count) for b in bought["chargers"]] == [("dc", 100)]


def test_tariff_periods_cover_the_day():
    assert tariff_period(17 * 60) == "peak"
    assert tariff_period(10 * 60) == "super_off_peak"
    assert tariff_period(3 * 60) == "off_peak"
    assert tariff_period(1440 + 17 * 60) == "peak"


def test_energy_by_period_adds_up():
    minutes = np.arange(0, 2880, 1.0)
    series = np.column_stack([minutes, np.full(len(minutes), 600.0)] + [np.zeros(len(minutes))] * 4)
    energy = energy_by_period(series, skip_days=1.0)
    assert sum(energy.values()) == pytest.approx(600.0 * 24)
    assert energy["peak"] == pytest.approx(600.0 * 5)


def test_contribution_is_revenue_less_every_cost():
    depot = DepotConfig("t", 1000.0, (ChargerBank("dc", 10, 60.0), ChargerBank("ac", 5, 11.0)), staff=2)
    prices = Prices()
    fixed = fixed_cost_per_day(depot, prices)
    assert fixed["chargers"] == pytest.approx((10 * 70_000 + 5 * 8_000) / 3650)
    out = daily_contribution(depot, 1000, {"peak": 100, "off_peak": 100, "super_off_peak": 100}, 990, prices)
    costs = out["energy"] + out["subscription"] + sum(fixed.values())
    assert out["contribution"] == pytest.approx(out["revenue"] - costs)
    assert out["subscription"] == pytest.approx(20 * prices.subscription_per_50kw_month * 12 / 365)
