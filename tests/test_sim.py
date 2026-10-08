from dataclasses import replace
from pathlib import Path

import pytest

from depot_twin import ChargerBank, DepotConfig, DepotSim, VehicleModel, Visit, load_scenario, sizing
from depot_twin.cli import main

EXAMPLE = Path(__file__).parent.parent / "scenarios" / "overnight_example.toml"
CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11)


def wave(count, soc_in=0.3, target=0.8, due=300.0):
    return [Visit(f"v{n}", CAR, arrive_min=0.0, soc_in=soc_in, target_soc=target, due_min=due) for n in range(count)]


def depot(limit_kw, ac=0, dc=0, **kwargs):
    banks = tuple(b for b in (ChargerBank("ac", ac, 11), ChargerBank("dc", dc, 100)) if b.count)
    defaults = dict(
        staff=100, plug_minutes=0, cleaning_bays=100, clean_minutes=0, charger_efficiency=1.0, usable_share=1.0
    )
    return DepotConfig(name="t", site_limit_kw=limit_kw, chargers=banks, **{**defaults, **kwargs})


def test_simulator_matches_hand_sizing_for_one_wave():
    plan = sizing.plan_wave(60, CAR.capacity_kwh, 0.3, 0.8, dwell_hours=5, charger_kw=11)
    result = DepotSim(depot(60 * 11, ac=plan.chargers), wave(60)).run()
    summary = result.summary()
    assert summary["on_time_share"] == 1.0
    assert summary["energy_delivered_kwh"] == pytest.approx(plan.energy_kwh, rel=1e-6)
    # Each vehicle has its own 11 kW charger, so the hand answer for charge time is 45 kWh / 11 kW.
    hand_minutes = 60 * 45 / 11
    # Power is integrated in one-minute steps: a vehicle joins on the step after it is plugged in and
    # leaves at the end of the step in which it fills, so the simulator may run up to two steps long.
    assert max(s.charged_min for s in result.sessions) == pytest.approx(hand_minutes, abs=2.0)


def test_site_limit_below_the_hand_answer_makes_vehicles_late():
    plan = sizing.plan_wave(60, CAR.capacity_kwh, 0.3, 0.8, dwell_hours=5, charger_kw=11)
    short = DepotSim(depot(plan.site_kw * 0.8, ac=60), wave(60)).run().summary()
    enough = DepotSim(depot(plan.site_kw * 1.01, ac=60), wave(60), policy="fifo").run().summary()
    assert short["on_time_share"] < 1.0
    assert enough["on_time_share"] == 1.0


def test_site_limit_is_never_exceeded():
    # The run raises if a step delivers more than the site can supply (grid.SiteLimitExceeded), so finishing
    # is the check. What is asserted is that the limit was reached and that the energy adds up to it.
    site = depot(250, dc=10)
    result = DepotSim(site, wave(30, soc_in=0.1, target=0.9)).run()
    summary = result.summary()
    assert summary["finished"] == 30
    assert summary["peak_grid_kw"] == pytest.approx(site.usable_kw)
    assert summary["energy_delivered_kwh"] == pytest.approx(summary["grid_energy_kwh"] * site.charger_efficiency)


def test_no_vehicle_is_charged_past_its_target_or_its_limit():
    result = DepotSim(depot(2000, dc=10), wave(10, soc_in=0.5, target=0.95)).run()
    for session in result.sessions:
        assert session.soc == pytest.approx(0.95, abs=1e-6)
    # Ten vehicles at 100 kW each is the most the batteries accept.
    assert result.series[:, 1].max() <= 1000 + 1e-6


def test_need_first_beats_fifo_when_one_vehicle_is_urgent():
    visits = wave(6, soc_in=0.2, target=0.9, due=600.0)
    visits.append(Visit("urgent", CAR, arrive_min=1.0, soc_in=0.2, target_soc=0.9, due_min=75.0))
    site = depot(150, dc=7)
    late_fifo = DepotSim(site, visits, policy="fifo").run().summary()["on_time_share"]
    late_need = DepotSim(site, visits, policy="need_first").run().summary()["on_time_share"]
    assert late_need == 1.0
    assert late_fifo < 1.0


def test_staff_and_bays_slow_the_turnaround():
    fast = DepotSim(depot(2000, dc=20), wave(20)).run().summary()
    slow = (
        DepotSim(depot(2000, dc=20, staff=1, cleaning_bays=1, clean_minutes=10, plug_minutes=2), wave(20))
        .run()
        .summary()
    )
    assert slow["turnaround_mean_min"] > fast["turnaround_mean_min"] + 10


def test_a_depot_with_no_power_still_returns():
    summary = DepotSim(depot(0, dc=2), wave(2)).run().summary()
    assert summary["finished"] == 0


def test_same_seed_same_result():
    first = DepotSim.from_scenario(load_scenario(EXAMPLE, seed=3)).run().summary()
    second = DepotSim.from_scenario(load_scenario(EXAMPLE, seed=3)).run().summary()
    other = DepotSim.from_scenario(load_scenario(EXAMPLE, seed=4)).run().summary()
    assert first == second
    assert first != other


def test_cli_runs_the_example(capsys):
    assert main(["run", str(EXAMPLE), "--seed", "1", "--json"]) == 0
    assert '"vehicles": 60' in capsys.readouterr().out


def test_the_same_vehicle_is_cleaned_on_every_second_of_its_own_visits():
    # Four visits by one physical vehicle, each with its own visit id, as the fleet simulator issues them.
    visits = [Visit("v1", CAR, arrive_min=60.0 * k, soc_in=0.5, target_soc=0.6, visit_id=f"v1:{k}") for k in range(4)]
    result = DepotSim(depot(500, dc=2, clean_every=2), visits).run()
    cleaned = [s.cleaned for s in sorted(result.sessions, key=lambda s: s.visit.arrive_min)]
    assert cleaned == [False, True, False, True]
    every = DepotSim(depot(500, dc=2, clean_every=1), visits).run()
    assert all(s.cleaned for s in every.sessions)


def test_inspection_falls_on_each_vehicles_own_nth_visit_whether_or_not_it_is_cleaned_then():
    # Two vehicles, six visits each, interleaved. Cleaned every fourth visit, inspected every third.
    visits = [
        Visit(name, CAR, arrive_min=90.0 * k + shift, soc_in=0.5, target_soc=0.6, visit_id=f"{name}:{k}")
        for k in range(6)
        for name, shift in (("a", 0.0), ("b", 30.0))
    ]
    site = replace(depot(500, dc=2, clean_every=4), inspect_every=3, inspect_minutes=20.0)
    result = DepotSim(site, visits).run()
    for name in ("a", "b"):
        mine = sorted((s for s in result.sessions if s.visit.vehicle_id == name), key=lambda s: s.visit.arrive_min)
        assert [s.inspected for s in mine] == [False, False, True, False, False, True]
        assert [s.cleaned for s in mine] == [False, False, False, True, False, False]
        plain, inspected = mine[0], mine[2]
        assert (inspected.ready_min - inspected.charged_min) - (plain.ready_min - plain.charged_min) == pytest.approx(
            20.0
        )
