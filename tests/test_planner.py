import numpy as np
import pytest

from depot_twin.first_version import planner, surrogate


def test_sobol_designs_fill_the_ranges_and_are_reproducible():
    designs = planner.sample_sobol(256, seed=1)
    assert designs == planner.sample_sobol(256, seed=1)
    for name, (low, high) in surrogate.RANGES.items():
        values = np.array([d[name] for d in designs])
        assert values.min() >= low and values.max() <= high
        # Space-filling: both ends of every range are reached.
        assert values.min() < low + 0.1 * (high - low) and values.max() > high - 0.1 * (high - low)


def test_boundary_designs_sit_near_the_edge_of_enough():
    edge = [surrogate.derive(d) for d in planner.sample_boundary(400, seed=2)]
    space = [surrogate.derive(d) for d in planner.sample_sobol(400, seed=2)]
    near = lambda rows: np.mean([0.7 <= r["energy_ratio"] <= 1.4 for r in rows])  # noqa: E731
    assert near(edge) > 0.6
    assert near(edge) > 2 * near(space)
    for design in edge:
        for name, (low, high) in surrogate.RANGES.items():
            assert low <= design[name] <= high


def test_ids_do_not_collide_between_pools():
    a = {d["id"] for d in planner.sample_sobol(50, first_id=0)}
    b = {d["id"] for d in planner.sample_boundary(50, first_id=100_000)}
    assert not a & b


@pytest.mark.parametrize("target", planner.TARGETS)
def test_any_prediction_maps_back_into_the_physical_range(target):
    wild = np.array([-50.0, -3.0, 0.0, 3.0, 50.0])
    back = planner.from_model_scale(target, wild)
    if target in planner.SHARES:
        assert (back >= 0).all() and (back <= 1).all()
    else:
        assert (back > 0).all()


def test_transform_round_trips_inside_the_range():
    shares = np.array([0.01, 0.5, 0.97, 0.995])
    assert planner.from_model_scale("served_share", planner.to_model_scale("served_share", shares)) == pytest.approx(
        shares
    )
    energy = np.array([20.0, 95.0])
    back = planner.from_model_scale("kwh_per_vehicle_day", planner.to_model_scale("kwh_per_vehicle_day", energy))
    assert back == pytest.approx(energy)


class Fixed:
    """A stand-in model that predicts a constant on the model scale."""

    def __init__(self, value):
        self.value = value

    def predict(self, x):
        return np.full(len(x), self.value)


def stub(served: float, margin: float = 0.0) -> planner.Planner:
    models = {
        "served_share": Fixed(float(planner.to_model_scale("served_share", np.array([served]))[0])),
        "kwh_per_vehicle_day": Fixed(np.log(90.0)),
        "peak_period_share": Fixed(0.0),
    }
    return planner.Planner(models, margin=margin)


GIVEN = {"size": 500.0, "site_limit_kw": 2750.0, "rides_per_vehicle_day": 25.0, "peak_gamma": 1.0, "kwh_per_mile": 0.4}


def test_candidates_vary_only_the_planners_choices():
    pool = planner.candidates(GIVEN, count=64)
    for name, value in GIVEN.items():
        assert {d[name] for d in pool} == {value}
    assert len({d["dc_per_100"] for d in pool}) == 64


def test_the_margin_turns_a_marginal_design_down():
    pool = planner.candidates(GIVEN, count=64)
    assert len(planner.rank(stub(0.992), pool, top=5)) == 5
    assert planner.rank(stub(0.992, margin=0.005), pool, top=5) == []


def test_ranking_prefers_the_cheaper_depot_when_service_is_equal():
    pool = planner.candidates(GIVEN, count=256)
    best = planner.rank(stub(0.999), pool, top=1)[0]["design"]
    cost = lambda d: d["dc_per_100"] * (40_000 + 500 * d["dc_kw"]) + d["ac_per_100"] * 8_000  # noqa: E731
    assert cost(best) < np.median([cost(d) for d in pool])


def test_scenarios_move_demand_and_stay_in_range():
    scenarios = planner.demand_scenarios(200, seed=1)
    levels = np.array([level for level, _ in scenarios])
    assert levels.std() == pytest.approx(0.08, abs=0.02)
    faced = planner.under({**GIVEN, "rides_per_vehicle_day": 31.0}, (1.2, 1.1))
    assert faced["rides_per_vehicle_day"] == surrogate.RANGES["rides_per_vehicle_day"][1]
    assert faced["peak_gamma"] == 1.1


def test_margin_is_measured_only_on_designs_predicted_to_pass():
    rows = [{**surrogate.derive(d), "served_share": 0.985} for d in planner.sample_sobol(32, seed=3)]
    # Predicted 99.5%, truly 98.5%: the model runs a point high on designs it would accept.
    assert planner.over_prediction_margin(stub(0.995), rows) == pytest.approx(0.01, abs=1e-3)
    # Predicted to fail: the planner would never accept these, so they say nothing about the margin.
    assert planner.over_prediction_margin(stub(0.80), rows) == 0.0
    # Predicted low but passing while the truth is higher: the margin is never negative.
    high = [{**row, "served_share": 0.999} for row in rows]
    assert planner.over_prediction_margin(stub(0.992), high) == 0.0


def test_situations_are_ones_where_the_service_level_is_reachable():
    for given in planner.sample_situations(100, seed=1):
        assert 200 <= given["size"] <= 1800
        low, high = surrogate.RANGES["site_limit_kw"]
        assert low <= given["site_limit_kw"] <= high
        wanted_kw = given["size"] * surrogate.estimated_kwh_per_vehicle_day(given) / 24.0
        # Unless the range clipped it, the connection can deliver more than the fleet wants.
        if given["site_limit_kw"] < high:
            assert given["site_limit_kw"] * surrogate.EFFICIENCY >= 1.04 * wanted_kw


def test_searched_designs_get_their_own_ids():
    situations = planner.sample_situations(3, seed=2)
    picked = planner.searched_designs(stub(0.999), situations, top=4, first_id=500_000, pool_size=64)
    assert [d["id"] for d in picked] == list(range(500_000, 500_012))


def test_over_prediction_on_searched_designs():
    rows = [{**surrogate.derive(d), "served_share": 0.98} for d in planner.sample_sobol(16, seed=4)]
    assert planner.over_prediction(stub(0.995), rows) == pytest.approx(0.015, abs=1e-3)
    assert planner.over_prediction(stub(0.90), rows) == 0.0
