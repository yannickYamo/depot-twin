import pytest

from depot_twin import sizing


def test_required_rate():
    # 90 kWh pack from 30% to 80% in 5 hours is 45 kWh at 9 kW.
    assert sizing.required_rate_kw(90, 0.3, 0.8, 5) == pytest.approx(9.0)


def test_min_arrival_soc_is_the_inverse_of_required_rate():
    soc = sizing.min_arrival_soc(90, 0.8, charger_kw=11, dwell_hours=4)
    assert sizing.required_rate_kw(90, soc, 0.8, 4) == pytest.approx(11.0)


def test_split_dwell_delivers_the_energy_exactly():
    fast, slow = sizing.split_dwell(energy_kwh=60, dwell_hours=3, fast_kw=50, slow_kw=11)
    assert fast + slow == pytest.approx(3)
    assert fast * 50 + slow * 11 == pytest.approx(60)


def test_split_dwell_edges():
    assert sizing.split_dwell(20, 3, 50, 11) == (0.0, pytest.approx(20 / 11))
    assert sizing.split_dwell(500, 3, 50, 11) == (3, 0.0)


def test_groups_and_waves():
    per_group = sizing.chargers_per_source(source_kw=66, charger_kw=11)
    assert per_group == 6
    assert sizing.groups_needed(200, per_group) == 34
    assert sizing.waves_per_buffer(buffer_kwh=500, group_kw=66, charge_hours=3) == 2


def test_daily_energy_and_buffers():
    energy = sizing.daily_energy_kwh(vehicles=200, miles_per_day=150, kwh_per_mile=0.4, efficiency=0.93)
    assert energy == pytest.approx(200 * 150 * 0.4 / 0.93)
    assert sizing.buffers_needed(energy, usable_kwh_per_buffer=450, cycles_per_day=2, spares=2) == 17


def test_plan_wave_rejects_a_charger_that_is_too_small():
    with pytest.raises(ValueError):
        sizing.plan_wave(10, 90, 0.1, 0.9, dwell_hours=2, charger_kw=11)
