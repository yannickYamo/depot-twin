"""The parts of E33 and E34 that can be held without running a depot: the charger designs, the order a
vehicle asks for chargers in, and the bars read again off the record."""

import json

from depot_twin.data import data_dir
from depot_twin.evals import chargers
from depot_twin.resources import ChargerBank, VehicleModel


def test_each_design_keeps_or_halves_the_count_and_the_mixed_bank_is_two_fifths_fast():
    assert chargers._chargers("all_60", 80) == (ChargerBank("dc", 80, 60.0),)
    assert chargers._chargers("all_150", 80) == (ChargerBank("dc", 80, 150.0),)
    assert chargers._chargers("half_150", 80) == (ChargerBank("dc", 40, 150.0),)
    fast, slow = chargers._chargers("mixed_kept_for_ojai", 80)
    assert (fast.kind, fast.count, fast.kw) == ("fast", 32, 150.0)
    assert (slow.kind, slow.count, slow.kw) == ("dc", 48, 60.0)


def test_a_mixed_bank_sends_the_ojai_to_the_fast_chargers_only_when_kept_for_it():
    from depot_twin import cadence, control, fleet

    kept = "_last_kept" in vars(fleet.FleetSim)
    before = (cadence._fleet_and_depot, control.SlotPower.bank_order, dict(chargers._DESIGN), fleet.FleetSim.run)
    chargers._install()
    try:
        _orders(control)
    finally:
        cadence._fleet_and_depot, control.SlotPower.bank_order = before[0], before[1]
        delattr(cadence, "_by_design")
        if not kept:
            fleet.FleetSim.run = before[3]
            delattr(fleet.FleetSim, "_last_kept")
        chargers._DESIGN.clear()
        chargers._DESIGN.update(before[2])


def _orders(control):

    class Visit:
        def __init__(self, name):
            self.model = VehicleModel(name=name, capacity_kwh=90.0, max_dc_kw=150.0, max_ac_kw=11.0)

    class Session:
        def __init__(self, name):
            self.visit = Visit(name)

    rule = control.SlotPower()
    chargers._DESIGN.update(design="mixed_kept_for_ojai", feeders=1)
    assert rule.bank_order(Session("ojai"), 0.0) == ["fast", "dc"]
    assert rule.bank_order(Session("ipace"), 0.0) == ["dc", "fast"]
    chargers._DESIGN.update(design="mixed_fastest_free")
    assert rule.bank_order(Session("ipace"), 0.0) == ["fast", "dc"]
    chargers._DESIGN.update(design="all_60")
    assert rule.bank_order(Session("ojai"), 0.0) == ["dc", "ac"]


def test_the_recorded_bars_are_the_ones_its_arms_give():
    record = json.loads((data_dir() / "derived" / "e33_chargers.json").read_text())
    assert chargers._bars(record["arms"]) == record["bars"]
    assert record["same_as_e30"]["same"] == record["same_as_e30"]["runs"]


def test_two_feeders_carry_twice_the_plan_with_the_margin():
    record = json.loads((data_dir() / "derived" / "e34_two_feeders.json").read_text())
    assert record["bars"]["1_two_feeders_carry_at_least_1200_in_every_fortnight_with_10pct_more"] == (
        record["carried_in_every_fortnight"] >= 1200
    )
