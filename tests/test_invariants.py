"""Findings the project rests on, checked on small synthetic cases on every change.

Each test is a miniature of a registered evaluation. If one fails, a headline result has probably stopped
being true of the code, whatever the documents still say.
"""

import numpy as np
import pytest

from depot_twin import ChargerBank, DepotConfig, VehicleModel
from depot_twin.fleet import FleetConfig, FleetSim, ThresholdRecall
from depot_twin.heartbeat import Heartbeat
from depot_twin.twin import EnergyIdentifier, relative_error

CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11, drive_kwh_per_mile=0.3, always_on_kw=2.0)
DAY = np.array([2, 1, 1, 1, 1, 2, 3, 5, 6, 5, 5, 5, 5, 5, 5, 6, 7, 7, 7, 6, 5, 5, 4, 3], dtype=float)
SHAPE = np.tile(DAY, 7) / np.tile(DAY, 7).sum()


def sim(rule, policy, size=200, chargers=26, limit=2000.0, seed=3, **fleet):
    depot = DepotConfig("t", limit, (ChargerBank("dc", chargers, 60),), staff=6, cleaning_bays=6, clean_minutes=8)
    return FleetSim(FleetConfig(size=size, models=(CAR,), **fleet), depot, SHAPE, rule, depot_policy=policy, seed=seed)


def test_feeding_in_order_serves_more_rides_when_power_is_short():
    # E11 in miniature: a site that can deliver about two thirds of the energy the fleet wants.
    short = 200 * 88 / 24 * 0.65 / 0.93
    in_order = sim(ThresholdRecall(), "slot_power", limit=short).run(4).summary()
    lowest_first = sim(ThresholdRecall(), "need_first", limit=short).run(4).summary()
    assert in_order["rides_served_share"] > lowest_first["rides_served_share"] + 0.01
    assert in_order["stranded"] == lowest_first["stranded"] == 0


def test_the_power_rule_makes_no_difference_when_power_is_plentiful():
    in_order = sim(ThresholdRecall(), "slot_power").run(3).summary()
    lowest_first = sim(ThresholdRecall(), "need_first").run(3).summary()
    assert abs(in_order["rides_served_share"] - lowest_first["rides_served_share"]) < 0.01


def test_heartbeat_strands_no_vehicle_and_keeps_its_promises():
    # E9 in miniature.
    rule = Heartbeat(ledger_adapt=0.2, ledger_level=0.975, ledger_from_state=True)
    result = sim(rule, "slot_power", step_min=5).run(5)
    kept = np.mean([entry["kept"] for entry in rule.ledger[24:]])
    promised = sum(e["committed"] for e in rule.ledger[24:]) / sum(e["actual"] for e in rule.ledger[24:])
    assert result.stranded == 0
    assert result.summary()["rides_served_share"] > 0.97
    assert kept >= 0.9
    assert promised >= 0.85  # a ledger that promises nothing would pass the line above


def test_identification_beats_the_type_figure():
    # E6 in miniature.
    fleet_sim = sim(ThresholdRecall(), "slot_power", size=150, vehicle_spread=0.08)
    nominal_drive, nominal_load = np.full(150, 0.3), np.full(150, 2.0)
    fleet_sim.telemetry = EnergyIdentifier(nominal_drive, nominal_load, fleet_sim.capacity)
    fleet_sim.run(4)
    identified = np.median(relative_error(fleet_sim.telemetry.drive_kwh_per_mile, fleet_sim.drive_kwh))
    assumed = np.median(relative_error(nominal_drive, fleet_sim.drive_kwh))
    assert identified < 0.7 * assumed


def test_grid_limit_holds_under_every_rule_and_power_rule():
    for rule, policy in (
        (ThresholdRecall(), "need_first"),
        (ThresholdRecall(), "slot_power"),
        (Heartbeat(), "slot_power"),
    ):
        # The run itself raises if a step delivers more than the site can supply (grid.SiteLimitExceeded), so
        # finishing is the check on the limit; what is asserted is that the energy drawn is the energy stored.
        result = sim(rule, policy, limit=500.0, step_min=5).run(2)
        site = result.depot.depot
        into_batteries = sum(s.energy_kwh for s in result.depot.sessions)
        from_grid = result.depot.series[:, 1].sum() / 60.0
        assert into_batteries == pytest.approx(from_grid * site.charger_efficiency, rel=1e-9)
        assert into_batteries > 0


def test_a_rule_that_grants_too_much_power_is_held_to_the_site_limit():
    from depot_twin.control import SlotPower

    class Greedy(SlotPower):
        def allocate(self, charging, wants, available_kw, now):
            return dict(wants)

    result = sim(ThresholdRecall(), Greedy(), limit=300.0, step_min=5).run(2)
    site = result.depot.depot
    assert result.depot.series[:, 3].max() * 60 > site.usable_kw  # more was asked for than the site has
    assert result.depot.series[:, 1].max() == pytest.approx(site.usable_kw)
