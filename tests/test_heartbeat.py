import numpy as np
import pytest

from depot_twin import ChargerBank, DepotConfig, VehicleModel
from depot_twin.control import SlotPower
from depot_twin.fleet import FleetConfig, FleetSim
from depot_twin.heartbeat import Heartbeat, solve_beat_plan
from depot_twin.replay import ReplayDemand, _between

CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11, drive_kwh_per_mile=0.3, always_on_kw=2.0)
DAY = np.array([2, 1, 1, 1, 1, 2, 3, 5, 6, 5, 5, 5, 5, 5, 5, 6, 7, 7, 7, 6, 5, 5, 4, 3], dtype=float)
SHAPE = np.tile(DAY, 7) / np.tile(DAY, 7).sum()


def plan(**changes):
    settings = dict(
        size=500,
        demand=np.full(24, 400.0),
        rate=2.6,
        away_hours=1.6,
        max_visits=40.0,
        eligible_now=500,
        gained_kwh=50.0,
        ride_kwh=1.5,
        idle_kwh=2.7,
        energy_now=0.5 * 90 * 500,
        energy_full=0.85 * 90 * 500,
        energy_reserve=0.3 * 90 * 500,
        stored_value=0.005,
    )
    return solve_beat_plan(**{**settings, **changes})


def test_plan_charges_when_vehicles_are_spare():
    visits, on_road = plan(demand=np.full(24, 100.0))
    assert visits > 10 and on_road == pytest.approx(500 - 1.6 * visits)


def test_plan_does_not_pull_vehicles_the_road_needs():
    # The next three hours need every vehicle and the night after does not: charging waits for the night.
    demand = np.concatenate([np.full(3, 2.6 * 500), np.full(21, 100.0)])
    visits, _ = plan(demand=demand, energy_now=0.8 * 90 * 500)
    assert visits == pytest.approx(0.0, abs=0.5)


def test_plan_never_calls_more_than_can_use_a_slot():
    visits, _ = plan(demand=np.full(24, 50.0), eligible_now=3)
    assert visits <= 3.0 + 1e-6


def test_plan_stops_charging_a_full_fleet():
    visits, _ = plan(demand=np.full(24, 50.0), energy_now=0.85 * 90 * 500, ride_kwh=1e-6, idle_kwh=1e-6)
    assert visits == pytest.approx(0.0, abs=1e-3)


def run(rule, policy, size=80, chargers=12, limit=2000.0, days=3):
    depot = DepotConfig("t", limit, (ChargerBank("dc", chargers, 60),), staff=4, cleaning_bays=4, clean_minutes=8)
    fleet = FleetConfig(size=size, models=(CAR,), step_min=5)
    sim = FleetSim(fleet, depot, SHAPE, rule, depot_policy=policy, seed=1)
    return sim, sim.run(days)


def test_heartbeat_runs_a_fleet_and_keeps_a_ledger():
    rule = Heartbeat()
    _, result = run(rule, "slot_power")
    assert result.stranded == 0
    assert result.summary()["rides_served_share"] > 0.97
    assert len(rule.ledger) >= 70
    assert all({"hour", "planned", "committed", "actual", "kept"} <= set(entry) for entry in rule.ledger)


def test_sessions_are_whole_slots_not_top_ups():
    rule = Heartbeat()
    _, result = run(rule, "slot_power")
    energy = [s.energy_kwh for s in result.depot.sessions if s.charged_min is not None]
    # A slot is about 56 kWh; calls are limited to vehicles with room for most of one.
    assert np.median(energy) > 45.0


def test_never_offers_more_chargers_than_the_site_can_feed():
    rule = Heartbeat()
    # 150 kW feeds two 60 kW chargers at full rate, though twelve are installed and free.
    depot = DepotConfig("t", 150.0, (ChargerBank("dc", 12, 60),), staff=4, cleaning_bays=4)
    sim = FleetSim(
        FleetConfig(size=80, models=(CAR,), step_min=5), depot, SHAPE, rule, depot_policy="slot_power", seed=1
    )
    assert rule._free_on_arrival(sim.state()) == 2


def test_slot_power_feeds_in_order_of_plugging_in():
    class Stub:
        def __init__(self, sid, connected):
            self.sid, self.connected_min = sid, connected
            self.visit = type("V", (), {"arrive_min": connected})()

    sessions = [Stub("late", 10.0), Stub("early", 2.0), Stub("middle", 5.0)]
    grants = SlotPower().allocate(sessions, {"late": 60, "early": 60, "middle": 60}, 100.0, now=20.0)
    assert grants == {"late": 0.0, "early": 60, "middle": 40}


def test_replay_scales_demand_and_serves_forecasts():
    steps = 288 * 2
    curves = {
        "counts": np.full(steps, 2.0),
        "mean": np.full((steps, 24), 24.0),
        "upper": np.full((steps, 24), 30.0),
        "actual": np.full((steps, 24), 24.0),
    }
    demand = ReplayDemand.scaled(curves, rides_per_day=5760.0)  # ten times the source's 576 a day
    assert demand.offered(0.0, 5.0) == pytest.approx(20.0)
    assert demand.offered(0.0, 15.0) == pytest.approx(60.0)
    mean, upper = demand.ahead(600.0)
    assert mean[0] == pytest.approx(240.0) and upper[0] == pytest.approx(300.0)


def test_corrections_are_interpolated_between_horizons():
    ratios = {1: np.array([1.0]), 6: np.array([2.0]), 24: np.array([2.0])}
    assert _between(ratios, 0)[0] == 1.0
    assert _between(ratios, 1)[0] == 1.0
    assert _between(ratios, 3)[0] == pytest.approx(1.4)
    assert _between(ratios, 23)[0] == 2.0


def test_least_left_feeds_the_vehicle_nearest_its_target_first():
    from depot_twin.control import LeastLeft

    class Stub:
        def __init__(self, sid, connected, left):
            self.sid, self.connected_min, self.energy_left_kwh = sid, connected, left

    sessions = [Stub("far", 1.0, 40.0), Stub("near", 9.0, 5.0)]
    grants = LeastLeft().allocate(sessions, {"far": 60, "near": 60}, 60.0, now=20.0)
    assert grants == {"far": 0.0, "near": 60.0}


def test_a_vehicle_the_floor_forces_in_takes_one_of_the_places_the_site_can_feed():
    rule = Heartbeat()
    # 150 kW feeds two 60 kW chargers at full rate. Three vehicles are under the floor and must come in.
    depot = DepotConfig("t", 150.0, (ChargerBank("dc", 12, 60),), staff=4, cleaning_bays=4)
    sim = FleetSim(
        FleetConfig(size=80, models=(CAR,), step_min=5), depot, SHAPE, rule, depot_policy="slot_power", seed=1
    )
    sim.soc[:] = 0.5
    sim.soc[:3] = 0.05
    called = rule.recall(sim.state())
    assert called == [0, 1, 2]  # the forced ones, and nobody the plan chose: the two places are taken
    assert (rule.calls, rule.forced_calls) == (3, 3)
    sim.soc[:3] = 0.2  # low enough to be worth a whole slot, above the floor
    sim.soc[10] = 0.05
    rule._quota, rule._ticks_left = 12.0, 1
    called = rule.recall(sim.state())
    assert 10 in called and len(called) == 2  # one forced, one chosen
    assert (rule.calls, rule.forced_calls) == (5, 4)
