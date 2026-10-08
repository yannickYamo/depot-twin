import numpy as np
import pytest

from depot_twin import ChargerBank, DepotConfig, VehicleModel
from depot_twin.dispatch import HARD_FLOOR_SOC, HeadroomRecall, ParamRecall, RollingPlan, lowest, must_come_in
from depot_twin.first_version.policy import ACTIONS, OBSERVATION_SIZE, observe
from depot_twin.fleet import INBOUND, FleetConfig, FleetSim, ThresholdRecall

CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11)
DAY = np.array([2, 1, 1, 1, 1, 2, 3, 5, 6, 5, 5, 5, 5, 5, 5, 6, 7, 7, 7, 6, 5, 5, 4, 3], dtype=float)
SHAPE = np.tile(DAY, 7) / np.tile(DAY, 7).sum()


def sim(rule, size=60, chargers=8, limit=2000.0, seed=1):
    depot = DepotConfig("t", limit, (ChargerBank("dc", chargers, 60),), staff=4, cleaning_bays=4, clean_minutes=8)
    return FleetSim(FleetConfig(size=size, models=(CAR,)), depot, SHAPE, rule, seed=seed)


def state_with(soc, chargers=3):
    fleet = sim(ThresholdRecall(), size=len(soc), chargers=chargers)
    fleet.soc[:] = soc
    return fleet.state()


def test_lowest_picks_the_emptiest_under_the_level():
    state = state_with([0.9, 0.2, 0.5, 0.1, 0.7])
    assert lowest(state, 2) == [3, 1]
    assert lowest(state, 5, below=0.6) == [3, 1, 2]
    assert lowest(state, 0) == []


def test_vehicles_below_the_hard_floor_always_come_in():
    state = state_with([0.9, HARD_FLOOR_SOC - 0.01, 0.5])
    assert must_come_in(state) == [1]
    for rule in (HeadroomRecall(), ParamRecall(recall_soc=0.0), RollingPlan()):
        assert 1 in rule.recall(state)


def test_headroom_never_sends_more_than_the_free_chargers():
    state = state_with([0.3] * 40, chargers=3)
    # Dead of night in the test shape: nearly every vehicle is spare, but only three chargers are free.
    assert len(HeadroomRecall().recall(state)) <= 3


def test_free_chargers_counts_vehicles_already_on_their_way():
    state = state_with([0.5] * 10, chargers=3)
    state.status[:2] = INBOUND
    assert state.free_chargers == 1


@pytest.mark.parametrize("rule", [ThresholdRecall, HeadroomRecall, RollingPlan, ParamRecall])
def test_every_rule_keeps_a_small_fleet_running(rule):
    summary = sim(rule()).run(2).summary()
    assert summary["stranded"] == 0
    assert summary["rides_served_share"] > 0.95


def test_the_plan_survives_a_fleet_that_starts_nearly_empty():
    fleet = sim(RollingPlan(), size=40, chargers=4)
    fleet.soc[:] = 0.14
    summary = fleet.run(1).summary()
    assert summary["depot_visits_per_vehicle_day"] > 0.5  # nearly empty vehicles were brought in and charged
    assert summary["rides_served_share"] > 0.3 and (fleet.soc > 0.14).mean() > 0.5


def test_observation_is_bounded_and_scale_free():
    small, large = sim(ThresholdRecall(), size=40, chargers=4), sim(ThresholdRecall(), size=400, chargers=40)
    for fleet in (small, large):
        fleet.soc[:] = 0.5
    a, b = observe(small.state()), observe(large.state())
    assert a.shape == (OBSERVATION_SIZE,)
    assert np.isfinite(a).all() and (a >= -1).all() and (a <= 2).all()
    # The same situation at ten times the size looks the same to the policy.
    assert a == pytest.approx(b, abs=0.05)


def test_environment_steps_an_hour_and_never_rewards_lost_rides(tmp_path):
    gym = pytest.importorskip("gymnasium")
    from depot_twin.first_version.env import DepotEnv
    from depot_twin.first_version.train import SHAPE as SHAPE_FILE
    from depot_twin.first_version.train import TRAIN_SCENARIO

    env = DepotEnv(TRAIN_SCENARIO, SHAPE_FILE, days=1)
    assert isinstance(env.action_space, gym.spaces.Discrete) and env.action_space.n == len(ACTIONS)
    observation, _ = env.reset(seed=1000)
    assert observation.shape == (OBSERVATION_SIZE,)
    done, steps = False, 0
    while not done:
        observation, reward, done, _, info = env.step(4)
        assert reward <= 0 and info["lost"] >= 0
        steps += 1
    assert steps == 24
