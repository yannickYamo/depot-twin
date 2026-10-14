"""The fleet to plan for, the feeder-timing scenarios and the block ranges: read against their records."""

import json
from pathlib import Path

import numpy as np
import pytest

from depot_twin import analysis, blocks, cadence
from depot_twin.evals import margin

ROOT = Path(__file__).parent.parent
DERIVED = ROOT / "data" / "derived"
MARGIN = json.loads((DERIVED / "e26_margin.json").read_text())
ACCOUNT = json.loads((DERIVED / "account_study.json").read_text())


def test_energy_use_is_moved_on_both_of_a_vehicle_s_figures():
    fleet, _ = cadence._fleet_and_depot(600, 5, 4, "rule")
    for before, after in zip(fleet.models, margin._models(fleet, 1.1), strict=True):
        assert after.drive_kwh_per_mile == pytest.approx(before.drive_kwh_per_mile * 1.1)
        assert after.always_on_kw == pytest.approx(before.always_on_kw * 1.1)
        assert after.capacity_kwh == before.capacity_kwh


def test_every_fleet_was_run_on_all_forty_pairs_at_every_level_of_energy_use():
    for energy, sizes in MARGIN["sizes"].items():
        for size in sizes:
            mine = [
                r
                for r in MARGIN["runs"]
                if r["label"] == f"energy_{energy}" and r["rule"] == MARGIN["rule"] and r["size"] == size
            ]
            assert {(r["window"], r["seed"]) for r in mine} == {
                (w, s) for w in cadence.E23_WINDOWS for s in cadence.E23_SEEDS
            }, (energy, size)


def test_the_recorded_verdicts_follow_from_the_recorded_runs():
    for energy, sizes in MARGIN["sizes"].items():
        mine = [r for r in MARGIN["runs"] if r["label"] == f"energy_{energy}" and r["rule"] == MARGIN["rule"]]
        verdict = margin._verdict(mine, tuple(sizes), MARGIN["usable_kwh_a_day"])
        assert verdict["capacity"] == MARGIN["carried"][energy]
        assert verdict["by_size"] == MARGIN["by_energy"][energy]["by_size"]


def test_the_planned_fleet_is_carried_at_both_levels_and_in_every_fortnight_at_the_higher():
    planned, _ = analysis.planned_fleet(DERIVED)
    above = MARGIN["by_energy"][f"{MARGIN['margin']:g}"]
    assert planned <= MARGIN["planned_fleet"] <= MARGIN["carried"]["1"]
    assert planned <= above["capacity"]
    assert all(above["by_size"][str(planned)]["carried_by_fortnight"].values())
    # The next fleet up that was run at the higher level fails one of the two conditions.
    larger = min(int(size) for size in above["by_size"] if int(size) > planned)
    row = above["by_size"][str(larger)]
    assert larger > above["capacity"] or not all(row["carried_by_fortnight"].values())
    assert ACCOUNT["base_design"]["fleet"] == planned
    assert analysis.carried_fleet(DERIVED)[0] == MARGIN["carried"]["1"]


def test_without_the_margin_test_the_plan_is_the_carried_fleet(tmp_path):
    (tmp_path / "e23_capacity.json").write_text(json.dumps({"capacity": 600}))
    assert analysis.planned_fleet(tmp_path) == (600, None)


def test_the_waiting_riders_are_read_off_the_last_step_before_a_minute():
    watch = margin._Waiting()
    watch.rows = [(0.0, 1.0), (15.0, 4.0), (30.0, 2.0)]
    assert watch.at(30.0) == 4.0
    assert watch.at(31.0) == 2.0
    assert watch.at(0.0) == 0.0


def test_a_vehicle_on_the_second_feeder_adds_more_than_the_site_s_average():
    timing = ACCOUNT["feeder_timing"]
    added = timing["added_contribution_per_vehicle_day"]
    assert added["dear"] <= added["base"] <= added["cheap"]
    # The land and the first connection are paid already, so the added vehicle carries neither.
    assert added["base"] > timing["site_average_contribution_per_vehicle_day"]
    split = ACCOUNT["split"][str(ACCOUNT["base_design"]["fleet"])]
    assert added["base"] * ACCOUNT["base_design"]["fleet"] < split["depot_contribution"]


def test_the_timing_summary_is_read_off_its_scenarios():
    timing = ACCOUNT["feeder_timing"]
    late = [s for s in timing["scenarios"] if s["applied_months_after_signing"] == 12]
    summary = timing["summary"]
    assert summary["scenarios"] == len(late)
    assert summary["a_year_late_across_fleet_costs"] == [
        min(s["cost_of_waiting"] for s in late),
        max(s["cost_of_waiting"] for s in late),
    ]
    low, high = summary["carrying_cost_of_applying_a_year_early"]
    assert 0 < low <= high < timing["capital"] * 0.1
    # Waiting two years never costs less than waiting one, wherever waiting costs anything.
    two = {
        tuple(v for k, v in s.items() if k not in ("cost_of_waiting", "applied_months_after_signing")): s
        for s in timing["scenarios"]
        if s["applied_months_after_signing"] == 24
    }
    for s in late:
        key = tuple(v for k, v in s.items() if k not in ("cost_of_waiting", "applied_months_after_signing"))
        if s["cost_of_waiting"] > 0:
            assert two[key]["cost_of_waiting"] >= s["cost_of_waiting"]


def test_blocks_of_one_week_are_the_week_by_week_resampling_and_a_flat_series_has_no_range():
    assert blocks.over_blocks([0.2] * 26) == {"mean": 0.2, "low": 0.2, "high": 0.2}
    values = list(np.linspace(0.0, 1.0, 26))
    single, four = blocks.over_blocks(values, block=1), blocks.over_blocks(values)
    assert single["mean"] == four["mean"]
    # A trend is the dependence blocks keep: the range of the mean is wider with neighbours kept together.
    assert four["high"] - four["low"] > single["high"] - single["low"]


def test_the_block_ranges_file_is_what_the_backtest_gives():
    recorded = json.loads((DERIVED / "e24_blocks.json").read_text())
    backtest = json.loads((DERIVED / "e24_backtest.json").read_text())
    weekly = backtest["series"]["chicago"]["1h"]["error_by_week"]["trained_here"]
    assert recorded["series"]["chicago"]["1h"]["error"]["trained_here"]["blocks"] == blocks.over_blocks(weekly)


# ---------------------------------------------------------------------------------------------------------
# Hand values: what the functions must give on inputs small enough to work out on paper.


def _margin_record(above: dict, at_estimate: tuple[int, ...] = (550, 600, 625, 650), carried: int = 650) -> dict:
    """A small E26-shaped record: `above` maps fleet -> fortnights carried with more energy use."""
    capacity = max((size for size, weeks in above.items() if any(weeks)), default=None)
    return {
        "margin": 1.1,
        "planned_fleet": capacity,
        "carried": {"1": carried, "1.1": capacity},
        "by_energy": {
            "1": {"by_size": {str(size): {} for size in at_estimate}},
            "1.1": {
                "capacity": capacity,
                "by_size": {
                    str(size): {"carried_by_fortnight": {str(k): ok for k, ok in enumerate(weeks)}}
                    for size, weeks in above.items()
                },
            },
        },
    }


def _planned(tmp_path, record: dict) -> int:
    (tmp_path / "e26_margin.json").write_text(json.dumps(record))
    return analysis.planned_fleet(tmp_path)[0]


def test_the_plan_stops_at_the_first_fleet_that_fails_a_fortnight(tmp_path):
    yes, one_short = (True, True, True, True), (True, False, True, True)
    assert _planned(tmp_path, _margin_record({550: yes, 600: yes, 625: one_short})) == 600
    # A larger fleet that passes does not rescue a smaller one that failed.
    assert _planned(tmp_path, _margin_record({550: yes, 600: one_short, 625: yes})) == 550


def test_the_plan_is_a_fleet_run_at_the_estimate_and_within_what_it_carried(tmp_path):
    yes = (True, True, True, True)
    # 575 was not run at the estimate: it may pass, and the plan is still the last fleet run at both.
    assert _planned(tmp_path, _margin_record({550: yes, 575: yes})) == 550
    assert _planned(tmp_path, _margin_record({550: yes, 600: yes, 625: yes}, carried=600)) == 600


def test_no_fleet_sound_in_every_fortnight_is_an_error_and_not_a_fallback(tmp_path):
    with pytest.raises(ValueError):
        _planned(tmp_path, _margin_record({550: (True, False, True, True), 600: (True, False, True, True)}))


def test_a_late_feeder_costs_the_vehicles_it_would_have_carried_up_to_one_feeder_s_worth():
    # 100 vehicles today, a feeder that carries 100, demand doubling every month, no discounting to speak of.
    growth, per_day, capital = 1.0, 10.0, 0.0
    cases = analysis.feeder_timing(100.0, 100.0, growth, per_day, capital)
    case = next(c for c in cases if (c["lead_months"], c["apply_at_month"], c["discount"]) == (24, 0, 0.08))
    monthly = 1.08 ** (1 / 12) - 1
    # Month 0: nothing over. Month 1: 100 over. From month 2 on demand is past two feeders: capped at 100.
    expected = sum(100.0 * analysis.DAYS_PER_MONTH * per_day / (1 + monthly) ** month for month in range(1, 24))
    assert case["contribution_not_earned"] == pytest.approx(expected, abs=600)
    late = next(c for c in cases if (c["lead_months"], c["apply_at_month"], c["discount"]) == (24, 12, 0.08))
    year = sum(100.0 * analysis.DAYS_PER_MONTH * per_day / (1 + monthly) ** month for month in range(24, 36))
    assert -late["against_applying_at_signing"] == pytest.approx(year, abs=1200)


def test_an_added_vehicle_carries_what_grows_with_the_fleet_and_nothing_paid_already():
    lines = {
        "revenue": 1000.0,
        "energy_tariff": 100.0,
        "subscription": 10.0,
        "chargers": 20.0,
        "buffer": 0.0,
        "staff": 70.0,
        "land": 50.0,
        "connection": 5.0,
        "vehicles": 300.0,
        "vehicle_operations": 200.0,
        "reliability": 0.0,
    }
    design = {"lines": lines, "fleet": 10}
    # 1000 - (100 + 10 + 20 + 0 + 70 + 300 + 200 + 0) = 300, over ten vehicles; land and connection left out.
    assert analysis.added_per_vehicle_day(design, {}, "base") == pytest.approx(30.0)
    # Cheap: $30,000 a vehicle a year and $50 a day. Dear: $100,000 and $250, which loses money, unclamped.
    cheap = (1000 - (200 + 10 * 30_000 / 365 + 10 * 50)) / 10
    dear = (1000 - (200 + 10 * 100_000 / 365 + 10 * 250)) / 10
    assert analysis.added_per_vehicle_day(design, {}, "cheap") == pytest.approx(cheap)
    assert analysis.added_per_vehicle_day(design, {}, "dear") == pytest.approx(dear)
    assert dear < 0


def test_months_against_another_fleet_keep_the_readings_that_do_reach_it():
    demand = {
        "capacity_one_feeder": 600,
        "growth_per_month": 0.05,
        "growth_per_month_by_estimate": {"fast": 0.05, "none": 0.0},
        "areas": {
            "a": {
                "vehicles_at_25_rides": 300.0,
                "months_until_second_feeder_range": [1, 2],
                "by_level": {"now": {"vehicles_at_25_rides": 300.0}},
            }
        },
    }
    area = analysis.demand_at(demand, 700)["a"]
    reached = int(np.ceil(np.log(700 / 300) / np.log(1.05)))
    assert area["by_level"]["now"]["months_until_second_feeder_by_estimate"] == {"fast": reached, "none": None}
    assert area["months_until_second_feeder_range"] == [reached, reached]


def test_the_spread_of_runs_that_repeat_their_fortnight_is_worth_one_run_a_fortnight():
    same = [{"window": w, "x": value} for w, value in (("a", 0.9), ("b", 1.0)) for _ in range(10)]
    split = analysis._between_and_within(same, "x")
    assert split["share_of_variance_between_fortnights"] == 1.0
    assert split["runs_worth"] == 2.0
    # Draws that differ as much inside a fortnight as across them are each worth a run.
    noise = [{"window": w, "x": float(k % 2)} for w in ("a", "b") for k in range(10)]
    assert analysis._between_and_within(noise, "x")["runs_worth"] == 20.0


def test_blocks_reproduce_a_hand_count_on_a_series_of_two_values():
    # Blocks of the whole series, wrapping: every resample is a rotation, so the mean never moves.
    assert blocks.over_blocks([0.0, 1.0, 0.0, 1.0], block=4) == {"mean": 0.5, "low": 0.5, "high": 0.5}


def test_more_energy_use_is_more_energy_used_on_the_road():
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape

    fleet, depot = cadence._fleet_and_depot(200, 5, 4, "rule")
    shape = load_weekly_shape(DERIVED / "weekly_shape_sf.json")
    used = []
    for energy in (1.0, 1.1):
        from dataclasses import replace

        moved = replace(fleet, models=margin._models(fleet, energy))
        sim = FleetSim(moved, depot, shape, ThresholdRecall(0.55, 0.85, wait_for_charger=True), "slot_power", seed=1)
        used.append(sim.run(1).summary()["kwh_per_vehicle_day"])
    # Not a full tenth: a vehicle that uses more spends longer in the depot, where the model drains nothing.
    assert 1.05 < used[1] / used[0] <= 1.1 + 1e-9


def test_the_cap_on_a_year_s_delay_is_a_feeder_s_worth_of_vehicles_for_twelve_months():
    assert analysis._capped_year(100.0, 10.0, 0, 0.0) == pytest.approx(100.0 * 10.0 * 365.0)
    # Later and discounted, it is worth less, and the summary counts the scenarios that sit on it.
    assert analysis._capped_year(100.0, 10.0, 36, 0.08) < analysis._capped_year(100.0, 10.0, 24, 0.08)
    summary = ACCOUNT["feeder_timing"]["summary"]
    assert 0 < summary["base_cost_scenarios_at_the_cap"] < summary["base_cost_scenarios"]
    assert ACCOUNT["feeder_timing"]["most_a_year_late_can_cost"] == pytest.approx(
        ACCOUNT["base_design"]["fleet"] * ACCOUNT["feeder_timing"]["valued_at_per_vehicle_day"]["base"] * 365.0,
        abs=1000,
    )
