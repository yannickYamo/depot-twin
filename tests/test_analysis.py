"""The account study: read from the recorded sweep, so its arithmetic is checked against that record."""

import json
from pathlib import Path

import pytest

from depot_twin import analysis

ROOT = Path(__file__).parent.parent
SWEEP = json.loads((ROOT / "data" / "derived" / "e19_sweet_spot.json").read_text())


def test_moving_no_input_gives_the_recorded_contribution_for_every_design():
    for design in analysis.designs(SWEEP).values():
        for name, _, value, _, _ in analysis.ASSUMPTIONS:
            assert analysis.moved(design, SWEEP["assumptions"], name, value) == pytest.approx(
                design["contribution"], abs=1.0
            )


def test_the_split_adds_back_up_and_the_fleet_is_the_larger_part():
    table = analysis.designs(SWEEP)
    design = table[("one_feeder", 700, 1.0, "threshold")]
    parts = analysis.split(design)
    assert parts["depot_contribution"] - parts["fleet_cost"] - parts["lost_ride_charge"] == pytest.approx(
        design["contribution"], abs=2.0
    )
    assert parts["fleet_cost_share_of_revenue"] > 10 * parts["energy_share_of_revenue"]


def test_the_break_even_is_where_the_two_fleets_earn_the_same():
    table = analysis.designs(SWEEP)
    smaller, larger = table[("one_feeder", 700, 1.0, "threshold")], table[("one_feeder", 800, 1.0, "threshold")]
    value = analysis.break_even_lost_ride(smaller, larger, SWEEP["assumptions"]["lost_ride_cost"])
    at = lambda design: analysis.moved(design, SWEEP["assumptions"], "lost_ride", value)  # noqa: E731
    assert at(smaller) == pytest.approx(at(larger), abs=40.0)  # the value is kept to a tenth of a dollar
    assert analysis.break_even_lost_ride(larger, smaller, 20.0) is None  # the smaller fleet loses no more rides


def test_the_tornado_is_ordered_and_a_dearer_vehicle_always_costs():
    rows = analysis.tornado(analysis.designs(SWEEP)[("one_feeder", 700, 1.0, "threshold")], SWEEP["assumptions"])
    assert [row["swing"] for row in rows] == sorted((row["swing"] for row in rows), reverse=True)
    vehicle = next(row for row in rows if row["input"] == "vehicle_year")
    assert vehicle["contribution_at_high"] < vehicle["contribution_at_low"]


def test_applying_late_costs_only_when_the_feeder_arrives_after_it_is_needed():
    # 500 vehicles today against a capacity of 600, growing 2% a month: full in month 10.
    cases = analysis.feeder_timing(500.0, 600.0, 0.02, 180.0, 550_000.0)
    pick = lambda lead, apply_at: next(  # noqa: E731
        c for c in cases if c["lead_months"] == lead and c["apply_at_month"] == apply_at and c["discount"] == 0.08
    )
    assert pick(24, 0)["against_applying_at_signing"] == 0
    assert pick(24, 0)["contribution_not_earned"] > 0  # even applied for at signing it arrives 14 months late
    assert pick(24, 24)["against_applying_at_signing"] < pick(24, 12)["against_applying_at_signing"] < 0
    # With no growth the site never fills: waiting only postpones the capital, which is worth a little.
    flat = analysis.feeder_timing(500.0, 600.0, 0.0, 180.0, 550_000.0)
    assert all(c["contribution_not_earned"] == 0 for c in flat)
    assert max(c["against_applying_at_signing"] for c in flat) > 0


CAPACITY = json.loads((ROOT / "data" / "derived" / "e23_capacity.json").read_text())


def test_the_account_of_the_capacity_runs_is_read_off_the_rule_that_carried_most():
    table = analysis.from_capacity_runs(CAPACITY)
    rows = CAPACITY["rules"][CAPACITY["best_rule"]]["by_size"]
    assert sorted(table) == sorted(int(size) for size in rows)
    carried = table[CAPACITY["capacity"]]
    low, high = carried["contribution_range"]
    assert low <= carried["contribution"] <= high
    assert carried["served"] >= CAPACITY["floor"]
    lines = carried["lines"]
    assert lines["revenue"] - sum(v for k, v in lines.items() if k != "revenue") == pytest.approx(
        carried["contribution"], rel=0.01
    )  # the lines are a mean over runs and the contribution their median
    charged = analysis.from_capacity_runs(CAPACITY, 20.0)[CAPACITY["capacity"]]
    assert charged["lost"] * 20.0 == pytest.approx(lines["reliability"])


def _capacity(lost: dict[int, list[float]], earned: dict[int, list[float]]) -> dict:
    runs = [
        {
            "label": "base",
            "rule": "waits",
            "size": size,
            "window": "w",
            "seed": seed,
            "rides_lost_per_day": lost[size][seed],
            "contribution_per_day": earned[size][seed],
        }
        for size in lost
        for seed in range(len(lost[size]))
    ]
    return {"best_rule": "waits", "runs": runs}


def test_the_break_even_over_runs_prices_each_extra_lost_ride_run_for_run():
    # The larger fleet earns $300 more and loses 10 more rides in every run: $30 a ride over the $20 charged.
    capacity = _capacity({700: [0.0, 5.0, 0.0], 800: [10.0, 15.0, 10.0]}, {700: [100.0] * 3, 800: [400.0] * 3})
    value = analysis.break_even_over_runs(capacity, 700, 800, 20.0)
    assert value is not None
    assert value["median"] == value["p10"] == value["p90"] == 50.0
    assert value["runs_where_the_larger_fleet_loses_more_rides"] == value["runs"] == 3


def test_there_is_no_break_even_when_the_larger_fleet_seldom_loses_more_rides():
    capacity = _capacity({600: [0.0, 0.0, 0.0], 700: [0.0, 0.0, 4.0]}, {600: [100.0] * 3, 700: [400.0] * 3})
    assert analysis.break_even_over_runs(capacity, 600, 700, 20.0) is None
