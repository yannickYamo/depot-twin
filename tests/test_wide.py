"""The fleet between two steps, the side studies' spreads, and the page's outcome file: read against their records."""

import json
from pathlib import Path

import pytest

from depot_twin import analysis, cadence
from depot_twin.evals import wide

ROOT = Path(__file__).parent.parent
DERIVED = ROOT / "data" / "derived"
BETWEEN = json.loads((DERIVED / "e25_between.json").read_text())
CAPACITY = json.loads((DERIVED / "e23_capacity.json").read_text())
DEMAND = json.loads((DERIVED / "e21_demand.json").read_text())


def run(served: float, low: float) -> dict:
    return {"served": served, "arrived_at_floor_share": low}


def test_a_verdict_needs_the_rides_and_the_calling_rule_in_charge():
    good = [run(1.0, 0.0)] * 9 + [run(0.9, 0.0)]
    assert wide._verdict(good, 0.99, 0.9, 0.5)
    assert not wide._verdict(good[1:] + [run(0.9, 0.0)], 0.99, 0.9, 0.5)
    leaning = [run(1.0, 0.6)] * 10
    assert not wide._verdict(leaning, 0.99, 0.9, 0.5)
    assert wide._verdict(leaning, 0.99, 0.9, 0.75)


def test_the_recorded_bars_of_the_fleet_between_follow_from_its_runs():
    runs, size = BETWEEN["runs"], str(BETWEEN["size"])
    assert len(runs) == len(BETWEEN["windows"]) * len(BETWEEN["seeds"])
    # The record keeps each run without its account lines, so the verdict is read again without the detail.
    again = cadence.carried([{k: v for k, v in r.items() if k != "window"} for r in runs], (BETWEEN["size"],))
    assert (again["capacity"] == BETWEEN["size"]) == BETWEEN["carried"]
    assert again["by_size"][size]["runs_at_floor"] == BETWEEN["by_size"][size]["runs_at_floor"]
    lines = BETWEEN["carried_by_where_the_line_is_drawn"][size]
    for line, verdict in lines.items():
        assert wide._verdict(runs, CAPACITY["floor"], CAPACITY["confidence"], float(line)) == verdict
    assert BETWEEN["bars"]["4_the_verdict_is_the_same_wherever_the_low_battery_line_is_drawn"] == (
        len(set(lines.values())) == 1
    )


def test_the_fleet_between_runs_on_the_pairs_of_the_capacity_test():
    pairs = {(r["window"], r["seed"]) for r in BETWEEN["runs"]}
    assert pairs == {(r["window"], r["seed"]) for r in CAPACITY["runs"] if r["label"] == "base"}
    assert {r["rule"] for r in BETWEEN["runs"]} == {CAPACITY["best_rule"]}


def test_the_carried_fleet_is_the_one_between_only_where_it_was_carried(tmp_path):
    (tmp_path / "e23_capacity.json").write_text(json.dumps({"capacity": 600}))
    assert analysis.carried_fleet(tmp_path) == (600, None)
    for carried, expected in ((False, 600), (True, 650)):
        (tmp_path / "e25_between.json").write_text(json.dumps({"carried": carried, "size": 650}))
        assert analysis.carried_fleet(tmp_path)[0] == expected


def test_months_against_another_fleet_are_the_same_arithmetic():
    same = analysis.demand_at(DEMAND, DEMAND["capacity_one_feeder"])
    assert same == DEMAND["areas"]
    larger = analysis.demand_at(DEMAND, DEMAND["capacity_one_feeder"] + 50)
    for name, area in larger.items():
        before = DEMAND["areas"][name]
        rate = DEMAND["growth_per_month"]
        assert area["months_until_second_feeder"] == cadence.months_until(
            DEMAND["capacity_one_feeder"] + 50, area["vehicles_at_25_rides"], rate
        )
        if before["months_until_second_feeder"]:
            assert area["months_until_second_feeder"] >= before["months_until_second_feeder"]
        assert area["rides_per_day"] == before["rides_per_day"]


def test_the_outcome_file_is_what_the_records_give(tmp_path):
    from depot_twin.data import build

    built = json.loads(build.build_outcome(str(tmp_path / "outcome.json")).read_text())
    page = json.loads((ROOT / "web" / "public" / "outcome.json").read_text())
    assert built == page
    calling = page["decisions"]["calling"]
    # Both rules on the same steps (E26): the largest fleet each carried there.
    same = json.loads((DERIVED / "e26_margin.json").read_text())["on_the_same_steps"]
    assert calling["with"]["fleet"] == same["waits_for_a_charger"]
    assert calling["without"]["fleet"] == same["plain"]
    assert page["one_feeder"]["planned"]["fleet"] == analysis.planned_fleet(DERIVED)[0]
    power = page["decisions"]["power"]
    gain = power["with"]["rides_served_share"] - power["without"]["rides_served_share"]
    assert gain == pytest.approx(CAPACITY["power_rule_gain"]["median"], abs=0.005)
    assert page["decisions"]["plan"]["energy_saving"] == CAPACITY["plan_energy_saving_at_500"]["median"]


@pytest.mark.parametrize("name", ["staffing.json", "sensitivity.json", "session_length.json", "e19_sweet_spot.json"])
def test_the_side_studies_say_how_many_seeds_they_rest_on(name):
    record = json.loads((DERIVED / name).read_text())
    assert len(record["seeds"]) >= 5


def test_the_staffing_gain_is_the_difference_of_its_two_arms():
    record = json.loads((DERIVED / "staffing.json").read_text())
    rows = {(r["staff"], r["power"]): r for r in record["rows"]}
    for staff, gain in record["in_order_gain"].items():
        apart = rows[(int(staff), "slot_power")]["served"] - rows[(int(staff), "need_first")]["served"]
        assert gain["median"] == pytest.approx(apart, abs=0.002)
        assert gain["runs"] == len(record["seeds"])
