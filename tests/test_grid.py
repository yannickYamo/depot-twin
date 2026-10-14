import pytest

from depot_twin.grid import PowerManager, SiteLimitExceeded, fill_in_order, share_equally
from depot_twin.resources import Buffer, ChargerBank, DepotConfig


def depot(limit=100.0, buffer=None, efficiency=1.0, usable=1.0):
    # The mechanics are tested with the whole connection usable; the margin has a test of its own.
    return DepotConfig(
        name="t",
        site_limit_kw=limit,
        chargers=(ChargerBank("dc", 4, 50),),
        buffer=buffer,
        charger_efficiency=efficiency,
        usable_share=usable,
    )


def test_the_load_manager_keeps_a_margin_under_the_connection():
    manager = PowerManager(depot(limit=1000.0, usable=0.95))
    assert manager.available_kw(1 / 60) == pytest.approx(950.0)
    assert manager.settle(950.0, 1 / 60).grid_kw == pytest.approx(950.0)


def test_delivering_more_than_the_site_can_supply_is_an_error_not_a_clipped_record():
    manager = PowerManager(depot(limit=1000.0, usable=0.95))
    with pytest.raises(SiteLimitExceeded):
        manager.settle(1200.0, 1 / 60)
    with_buffer = PowerManager(depot(limit=100.0, buffer=Buffer(energy_kwh=10.0, power_kw=50.0)))
    with pytest.raises(SiteLimitExceeded):
        with_buffer.settle(200.0, 1 / 60)


def test_share_equally_hands_unused_share_to_others():
    grants = share_equally({"a": 10, "b": 50, "c": 50}, 90)
    assert grants == {"a": pytest.approx(10), "b": pytest.approx(40), "c": pytest.approx(40)}


def test_share_equally_never_exceeds_wants_or_supply():
    grants = share_equally({"a": 10, "b": 20}, 500)
    assert grants == {"a": pytest.approx(10), "b": pytest.approx(20)}
    assert sum(share_equally({"a": 80, "b": 80}, 100).values()) == pytest.approx(100)


def test_fill_in_order_starves_the_last():
    assert fill_in_order({"a": 60, "b": 60, "c": 60}, 100, ["b", "a", "c"]) == {"a": 40, "b": 60, "c": 0.0}


def test_grid_draw_includes_charger_losses():
    manager = PowerManager(depot(limit=100, efficiency=0.9))
    assert manager.available_kw(1 / 60) == pytest.approx(90)
    step = manager.settle(90, 1 / 60)
    assert step.grid_kw == pytest.approx(100)


def test_buffer_covers_the_gap_then_refills():
    manager = PowerManager(depot(limit=100, buffer=Buffer(energy_kwh=100, power_kw=50, min_soc=0.0, efficiency=1.0)))
    step = manager.settle(150, 1.0)
    assert step.grid_kw == pytest.approx(100)
    assert step.buffer_kw == pytest.approx(50)
    assert manager.buffer_kwh == pytest.approx(50)
    step = manager.settle(70, 1.0)
    # 30 kW of spare grid power goes back into the buffer.
    assert step.grid_kw == pytest.approx(100)
    assert manager.buffer_kwh == pytest.approx(80)


def test_buffer_stops_at_its_floor():
    manager = PowerManager(depot(limit=100, buffer=Buffer(energy_kwh=100, power_kw=500, min_soc=0.2)))
    # 80 kWh usable over a one-hour step is at most 80 kW of help.
    assert manager.available_kw(1.0) == pytest.approx(180)
