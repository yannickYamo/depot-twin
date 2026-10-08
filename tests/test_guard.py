import numpy as np

from depot_twin import ChargerBank, DepotConfig, VehicleModel
from depot_twin.fleet import FleetConfig, FleetSim, ThresholdRecall
from depot_twin.guard import Guarded
from depot_twin.heartbeat import Heartbeat
from depot_twin.replay import ReplayDemand

CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11, drive_kwh_per_mile=0.3, always_on_kw=2.0)
SHAPE = np.full(168, 1 / 168)


def demand(days=4, per_step=7.0, fault_from=None, factor=1.0):
    steps = days * 288
    hourly = per_step * 12
    return ReplayDemand(
        counts=np.full(steps, per_step),
        mean=np.full((steps, 24), hourly),
        upper=np.full((steps, 24), hourly * 1.2),
        actual=np.full((steps, 24), hourly),
        fault_from_minute=fault_from,
        fault_factor=factor,
    )


def run(rule, replay, days=4):
    depot = DepotConfig("t", 2000.0, (ChargerBank("dc", 12, 60),), staff=4, cleaning_bays=4, clean_minutes=8)
    fleet = FleetConfig(size=80, models=(CAR,), step_min=5)
    sim = FleetSim(fleet, depot, SHAPE, rule, depot_policy="slot_power", seed=1, demand=replay)
    return sim.run(days)


def test_a_sound_forecast_never_trips_the_guard():
    guard = Guarded(Heartbeat(), ThresholdRecall())
    run(guard, demand())
    assert guard.events == []
    assert guard.active is guard.primary
    assert sum(guard.breaks) == 0


def test_a_broken_forecast_trips_the_guard_within_its_window():
    guard = Guarded(Heartbeat(), ThresholdRecall(), window_hours=12)
    # From the start of day two the forecast says a third of the truth.
    run(guard, demand(fault_from=1440.0, factor=0.33))
    assert guard.events and guard.events[0]["event"] == "fell back"
    assert 24 < guard.events[0]["hour"] <= 24 + 12
    assert guard.active is guard.fallback


def test_control_returns_once_the_forecast_is_sound_again():
    guard = Guarded(Heartbeat(), ThresholdRecall(), window_hours=6, hold_hours=6)
    replay = demand(days=5, fault_from=1440.0, factor=0.33)
    depot = DepotConfig("t", 2000.0, (ChargerBank("dc", 12, 60),), staff=4, cleaning_bays=4, clean_minutes=8)
    sim = FleetSim(
        FleetConfig(size=80, models=(CAR,), step_min=5),
        depot,
        SHAPE,
        guard,
        depot_policy="slot_power",
        seed=1,
        demand=replay,
    )
    sim.advance(2.5 * 1440)
    assert guard.active is guard.fallback
    replay.fault_from_minute = None  # the feed is repaired
    sim.advance(1.5 * 1440)
    assert [e["event"] for e in guard.events] == ["fell back", "restored"]
    assert guard.active is guard.primary


def test_shadow_mode_records_and_never_acts():
    guard = Guarded(Heartbeat(), ThresholdRecall(), shadow_only=True)
    result = run(guard, demand(fault_from=1440.0, factor=0.33))
    assert guard.active is guard.fallback and guard.events == []
    assert len(guard.shadow_calls) > 500
    assert result.stranded == 0
