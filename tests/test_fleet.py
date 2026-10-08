import json
from pathlib import Path

import numpy as np
import pytest

from depot_twin import ChargerBank, DepotConfig, VehicleModel
from depot_twin.fleet import FleetConfig, FleetSim, load_fleet_scenario, load_weekly_shape

ROOT = Path(__file__).parent.parent
CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11)
# Two daily peaks, the same every day: enough structure for the fleet to have a rush hour.
DAY = np.array([2, 1, 1, 1, 1, 2, 3, 5, 6, 5, 5, 5, 5, 5, 5, 6, 7, 7, 7, 6, 5, 5, 4, 3], dtype=float)
SHAPE = np.tile(DAY, 7) / np.tile(DAY, 7).sum()


def depot(chargers=10, limit=2000.0):
    return DepotConfig("t", limit, (ChargerBank("dc", chargers, 60),), staff=4, cleaning_bays=4, clean_minutes=8)


def run(size=60, days=3, seed=1, **kwargs):
    return FleetSim(FleetConfig(size=size, models=(CAR,)), depot(**kwargs), SHAPE, seed=seed).run(days)


def test_an_unconstrained_fleet_matches_the_filed_mileage_split():
    targets = json.loads((ROOT / "data" / "derived" / "cpuc_targets.json").read_text())["targets"]
    summary = run(size=100, days=5).summary()
    assert summary["rides_served_share"] > 0.99
    for share in ("idle_share", "to_pickup_share", "with_passenger_share"):
        assert summary[share] == pytest.approx(targets[share], abs=0.03)


class Watch:
    """Checks each step, as the run goes, that every vehicle is in one place and the depot agrees about which."""

    def __init__(self):
        self.steps = 0
        self.most_at_depot = 0

    def tick(self, sim):
        from depot_twin.fleet import AT_DEPOT, INBOUND

        self.steps += 1
        depot = sim.depot
        live = [s for s in depot.sessions if s.ready_min is None]
        at_depot = {int(v) for v in np.flatnonzero(sim.status == AT_DEPOT)}
        self.most_at_depot = max(self.most_at_depot, len(at_depot))
        # A vehicle at the depot has exactly one unfinished visit there, and no vehicle on the road has one.
        assert sorted(int(s.visit.vehicle_id) for s in live) == sorted(at_depot)
        inbound = int((sim.status == INBOUND).sum())
        assert len(depot.visits) - len(depot.sessions) == inbound  # called in and not yet arrived
        chargers = sum(bank.count for bank in depot.depot.chargers)
        assert 0 <= sum(depot.free.values()) <= chargers
        assert len(depot.charging) <= chargers - sum(depot.free.values())
        assert depot.staff.count <= depot.depot.staff and depot.bays.count <= depot.depot.cleaning_bays
        assert ((sim.soc >= 0.0) & (sim.soc <= 1.0)).all()
        # Rides are carried only by vehicles on the road, and never more than they have minutes for.
        minute, _, served, on_road, *_ = sim._steps[-1]
        assert served <= on_road * sim.config.step_min / sim.config.ride_minutes + 1e-9


def test_every_vehicle_is_in_one_place_at_every_step_and_none_runs_flat():
    watch = Watch()
    sim = FleetSim(FleetConfig(size=60, models=(CAR,), step_min=5), depot(chargers=3), SHAPE, seed=2, observer=watch)
    result = sim.run(3)
    assert watch.steps == 3 * 288 and watch.most_at_depot > 3  # the depot was crowded, so the checks had work to do
    assert result.stranded == 0
    assert (sim.soc > 0).all()


def test_a_ride_waits_for_a_free_vehicle_and_is_lost_only_after_the_wait():
    cfg = FleetConfig(size=10, models=(CAR,), step_min=5, max_wait_minutes=10.0)
    sim = FleetSim(cfg, depot(), SHAPE, seed=1)
    # Ten vehicles carry 10 * 5 / 23 rides a step. Five rides arrive at once: two steps clear 4.35 of them,
    # and the rest have waited ten minutes by the third step and are given up on.
    a_step = 10 * 5 / 23
    assert sim._take_rides(5.0, a_step) == (pytest.approx(a_step), 0.0)
    sim.env.run(until=5)
    assert sim._take_rides(0.0, a_step) == (pytest.approx(a_step), 0.0)
    sim.env.run(until=10)
    served, lost = sim._take_rides(0.0, a_step)
    assert served == 0.0 and lost == pytest.approx(5.0 - 2 * a_step)


def test_rides_served_do_not_depend_on_how_fine_the_step_is():
    from depot_twin.fleet import served_share

    def served(step):
        cfg = FleetConfig(size=120, models=(CAR,), step_min=step, rides_per_vehicle_day=38.0)
        return served_share(FleetSim(cfg, depot(chargers=14), SHAPE, seed=4).run(4).steps)

    # A small fleet losing 4% of its rides: without the wait, one-minute steps lost over a point more than
    # five-minute ones here, because a ride nobody could take in its own minute was gone.
    fine, coarse = served(1.0), served(5.0)
    assert fine < 0.999  # rides are being lost, so there is something to compare
    assert fine == pytest.approx(coarse, abs=0.008)


def test_two_arms_with_one_seed_are_offered_the_same_rides():
    from depot_twin.fleet import ThresholdRecall

    cfg = FleetConfig(size=60, models=(CAR,), step_min=5)
    early = FleetSim(cfg, depot(chargers=3), SHAPE, ThresholdRecall(0.6), seed=9).run(2)
    late = FleetSim(cfg, depot(chargers=3), SHAPE, ThresholdRecall(0.2), seed=9).run(2)
    assert (early.steps[:, 1] == late.steps[:, 1]).all()
    assert (early.steps[:, 3] != late.steps[:, 3]).any()  # the arms did differ in what their vehicles were doing


def test_an_empty_battery_gives_nothing_and_its_vehicle_carries_nobody():
    cfg = FleetConfig(size=4, models=(CAR,), step_min=5, floor_soc=-1.0)  # nothing calls an empty vehicle in

    class Never:
        def recall(self, state):
            return []

        def target_soc(self, vehicle, state):
            return 0.85

    sim = FleetSim(cfg, depot(), SHAPE, Never(), seed=1)
    sim.soc[:] = 0.02
    held = float((sim.soc * sim.capacity).sum())
    result = sim.run(1)
    assert (sim.soc == 0.0).all()
    assert result.energy_kwh == pytest.approx(held)  # no more was used than the batteries held
    empty = result.steps[result.steps[:, 0] >= 720]
    assert empty[:, 2].sum() == 0.0 and empty[:, 5].sum() > 0  # on the road, carrying nobody, rides given up on


def test_energy_is_conserved_between_fleet_and_depot():
    sim = FleetSim(FleetConfig(size=60, models=(CAR,)), depot(), SHAPE, seed=3)
    start = float((sim.soc * sim.capacity).sum())
    result = sim.run(3)
    # Vehicles still charging hold energy the fleet has not been told about yet.
    in_depot = sum(s.energy_kwh for s in result.depot.sessions if s.ready_min is None)
    known = float((sim.soc * sim.capacity).sum()) + in_depot
    delivered = sum(s.energy_kwh for s in result.depot.sessions)
    assert known == pytest.approx(start + delivered - result.energy_kwh, rel=1e-6)


def test_too_few_chargers_cost_rides():
    plenty = run(size=120, chargers=20).summary()
    scarce = run(size=120, chargers=4).summary()
    assert scarce["rides_served_share"] < plenty["rides_served_share"] - 0.05
    assert scarce["available_at_peak_share"] < plenty["available_at_peak_share"]


def test_same_seed_same_fleet_result():
    assert run(seed=5).summary() == run(seed=5).summary()
    assert run(seed=5).summary() != run(seed=6).summary()


def test_scenario_files_load():
    config, site = load_fleet_scenario(ROOT / "scenarios" / "east_oakland_200.toml")
    assert config.size == 200
    assert [m.name for m in config.models] == ["ipace", "ojai"]
    assert site.site_limit_kw == 2750
    assert load_weekly_shape(ROOT / "data" / "derived" / "weekly_shape.json").sum() == pytest.approx(1.0)


def test_cleaning_every_nth_visit_follows_the_physical_vehicle_in_the_fleet():
    # The fleet issues a new visit id each time a vehicle comes back; the cleaning count must follow the vehicle.
    from dataclasses import replace

    from depot_twin.fleet import ThresholdRecall

    cfg = FleetConfig(size=60, models=(CAR,))
    rule = ThresholdRecall(recall_soc=0.55, target=0.85)  # short, frequent visits
    every = FleetSim(cfg, replace(depot(chargers=10), clean_every=1), SHAPE, rule, seed=3).run(3)
    second = FleetSim(cfg, replace(depot(chargers=10), clean_every=2), SHAPE, rule, seed=3).run(3)
    fourth = FleetSim(cfg, replace(depot(chargers=10), clean_every=4), SHAPE, rule, seed=3).run(3)
    done = lambda r: [s for s in r.depot.sessions if s.ready_min is not None]  # noqa: E731
    share = lambda r: sum(s.cleaned for s in done(r)) / len(done(r))  # noqa: E731
    assert share(every) == 1.0
    assert 0.4 <= share(second) <= 0.6
    assert 0.15 <= share(fourth) <= 0.35
    assert second.summary() != fourth.summary()


def test_rides_served_and_vehicle_busy_time_agree_at_every_step():
    # The minutes the served rides took are exactly the busy minutes drained from the vehicles, even when the
    # fleet is saturated and some vehicles are busy for the whole step.
    from depot_twin.fleet import busy_shares

    rng = np.random.default_rng(7)
    for total, n in ((3.0, 50), (45.0, 50), (49.9, 50), (50.0, 50)):
        busy = busy_shares(total, rng.gamma(4.0, 0.25, size=n))
        assert busy.sum() == pytest.approx(total)
        assert busy.max() <= 1.0 and busy.min() >= 0.0
    assert busy_shares(80.0, rng.gamma(4.0, 0.25, size=50)).sum() == pytest.approx(50.0)
