"""The demand generator: what it takes from donors, and what it must never do."""

import numpy as np
import pandas as pd
import pytest

from depot_twin import synth
from depot_twin.data import nyc, sftaxi
from depot_twin.data.donors import Donor
from depot_twin.newsite import eligible, monday_before

START = pd.Timestamp("2024-01-01")  # a Monday


def donor(weeks: int = 30, peak_hour: int = 18, level: float = 400.0, seed: int = 0) -> pd.Series:
    """An hourly series with one daily peak, a quiet weekend and some noise."""
    index = pd.date_range(START, periods=weeks * 168, freq="h")
    shape = 1.0 + 0.8 * np.exp(-0.5 * ((index.hour - peak_hour) / 3.0) ** 2)
    shape = shape * np.where(index.dayofweek >= 5, 0.6, 1.0)
    rng = np.random.default_rng(seed)
    return pd.Series(rng.poisson(level * shape).astype(float), index=index)


def test_profile_recovers_the_shape_of_the_week():
    profile = synth.extract("d", donor())
    assert profile.weekly.mean() == pytest.approx(1.0)
    assert int(np.argmax(profile.weekly[:24])) == 18
    assert profile.weekly[5 * 24 + 18] < profile.weekly[18]  # Saturday evening under Monday evening
    assert profile.residual.shape[1] == 168


def test_generated_series_has_the_level_asked_for_and_the_donors_shape():
    profiles = [synth.extract("a", donor(seed=1)), synth.extract("b", donor(seed=2))]
    made = synth.generate(profiles, START, 20, 250.0, np.random.default_rng(3))
    assert len(made) == 20 * 168
    assert made.mean() == pytest.approx(250.0, rel=0.1)
    assert int(made.groupby(made.index.hour).mean().idxmax()) == 18
    assert (made >= 0).all()


def test_a_mix_of_two_donors_lies_between_them():
    early, late = synth.extract("early", donor(peak_hour=8)), synth.extract("late", donor(peak_hour=20))
    made = synth.generate([early, late], START, 30, 500.0, np.random.default_rng(4), weights=np.array([0.5, 0.5]))
    by_hour = made[made.index.dayofweek < 5].groupby(made[made.index.dayofweek < 5].index.hour).mean()
    assert by_hour[8] > by_hour[14] and by_hour[20] > by_hour[14]


def test_generation_is_repeatable_and_must_start_on_a_monday():
    profiles = [synth.extract("a", donor())]
    first = synth.generate(profiles, START, 4, 100.0, np.random.default_rng(5))
    again = synth.generate(profiles, START, 4, 100.0, np.random.default_rng(5))
    assert first.equals(again)
    with pytest.raises(ValueError):
        synth.generate(profiles, START + pd.Timedelta(days=1), 4, 100.0, np.random.default_rng(5))


def test_five_minute_steps_keep_every_hours_total():
    hourly = donor(weeks=1)
    steps = synth.five_minute(hourly, np.random.default_rng(6))
    assert len(steps) == len(hourly) * 12
    assert np.allclose(steps.to_numpy().reshape(-1, 12).sum(axis=1), hourly.to_numpy())


def test_likeness_is_small_for_series_made_from_the_same_donor():
    real = donor(seed=7)
    made = [synth.generate([synth.extract("a", real)], START, 30, 400.0, np.random.default_rng(k)) for k in range(3)]
    assert synth.likeness(made, real)["shape_error"] < 0.05


def test_a_held_out_city_never_lends_to_itself():
    donors = [
        Donor("a_core", "a", "taxi", "core", "a"),
        Donor("a_outer", "a", "taxi", "outer", "a"),
        Donor("b_core", "b", "taxi", "core", "b"),
        Donor("b_inner", "b", "taxi", "inner", "b"),
    ]
    assert [d.name for d in eligible(donors, "core", without_city="a")] == ["b_core"]
    # No other city has an outer area, so the nearest kind is borrowed.
    assert [d.name for d in eligible(donors, "outer", without_city="a")] == ["b_inner"]


def test_monday_before_leaves_whole_weeks():
    start = monday_before(pd.Timestamp("2024-03-14 05:00"), 10)
    assert start.dayofweek == 0 and start.hour == 0
    assert start + pd.Timedelta(weeks=10) <= pd.Timestamp("2024-03-14 05:00")


def test_new_york_zones_map_to_areas_and_stray_dates_are_dropped():
    lookup = (
        '"LocationID","Borough","Zone","service_zone"\n'
        '1,"EWR","Newark Airport","EWR"\n132,"Queens","JFK Airport","Airports"\n'
        '161,"Manhattan","Midtown Center","Yellow Zone"\n42,"Manhattan","Central Harlem North","Boro Zone"\n'
        '7,"Queens","Astoria","Boro Zone"\n'
    )
    areas = nyc.parse_zones(lookup)
    assert areas == {132: "airports", 161: "manhattan_core", 42: "upper_manhattan", 7: "outer_boroughs"}
    times = pd.to_datetime(["2024-03-05 10:15", "2024-03-05 10:50", "2009-01-01 00:00", "2024-03-05 11:05"])
    counts = nyc.count_hours(times, [161, 161, 161, 1], areas, 2024, 3)
    assert counts == {("manhattan_core", pd.Timestamp("2024-03-05 10:00")): 2}


def test_san_francisco_rides_fall_in_one_of_three_areas():
    ride = {"airport": False, "latitude": 37.79, "longitude": -122.40}
    assert sftaxi.area_of(ride) == "core"
    assert sftaxi.area_of({**ride, "latitude": 37.73}) == "rest"
    assert sftaxi.area_of({**ride, "airport": True}) == "airport"
    assert sftaxi.area_of({"airport": False, "latitude": float("nan"), "longitude": float("nan")}) == "rest"


def test_thinning_keeps_the_rhythm_at_a_smaller_scale():
    from depot_twin.newsite import thinned

    city = donor(level=20000.0)
    small = thinned(city, 500.0, seed=1)
    assert small.mean() == pytest.approx(500.0, rel=0.05)
    assert (small <= city).all()
    assert np.corrcoef(small, city)[0, 1] > 0.95


def test_weeks_are_borrowed_in_runs_so_a_week_resembles_the_one_before():
    index = pd.date_range(START, periods=40 * 168, freq="h")
    # A donor whose evenings grow busier over the weeks: a slow change that week-by-week draws would scramble.
    season = 1.0 + 0.5 * np.sin(np.arange(len(index)) / (20 * 168) * np.pi) * (index.hour >= 18)
    series = pd.Series(np.random.default_rng(0).poisson(2000.0 * season).astype(float), index=index)
    made = synth.generate([synth.extract("a", series)], START, 30, 2000.0, np.random.default_rng(1))
    assert synth.likeness([made], series)["week_to_week_generated"] > 0.5


def test_expected_error_is_quoted_against_last_weeks_curve():
    from depot_twin.newsite import expected_error

    def cell(horizon, error, naive, held):
        arm = {"wape": error, "upper_coverage": held}
        return {"horizon": horizon, "donors_and_generated": arm, "naive": {"same_time_last_week": naive}}

    cells = [cell(h, 0.05, 0.10, 0.97) for h in (1, 6, 24)] + [cell(h, 0.09, 0.10, 0.88) for h in (1, 6, 24)]
    quoted = expected_error({"cells": cells})["24h"]
    assert quoted["error_against_last_week_best"] == 0.5
    assert quoted["error_against_last_week_worst"] == 0.9
    assert quoted["upper_bound_held_least"] == 0.88
