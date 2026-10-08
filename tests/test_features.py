import numpy as np
import pandas as pd
import pytest

from depot_twin.data import sftaxi, weather
from depot_twin.features import FEATURES, _slot_shift, build
from depot_twin.models import short_horizon


def series(days=40, steps_per_hour=12, seed=0):
    index = pd.date_range("2024-01-01", periods=days * 24 * steps_per_hour, freq=f"{60 // steps_per_hour}min")
    rng = np.random.default_rng(seed)
    daily = 20 + 15 * np.sin(2 * np.pi * (index.hour + index.minute / 60) / 24)
    return pd.Series(rng.poisson(daily).astype(float), index=index)


@pytest.mark.parametrize("horizon", short_horizon.HORIZONS)
def test_no_feature_sees_the_future(horizon):
    counts = series()
    cut = len(counts) // 2
    changed = counts.copy()
    changed.iloc[cut + 1 :] = 999.0  # rewrite everything after the cut
    before = build(counts, horizon, with_label=False).iloc[: cut + 1]
    after = build(changed, horizon, with_label=False).iloc[: cut + 1]
    pd.testing.assert_frame_equal(before, after)


@pytest.mark.parametrize("horizon", short_horizon.HORIZONS)
def test_the_label_is_the_hour_that_starts_one_horizon_ahead(horizon):
    counts = series()
    frame = build(counts, horizon)
    moment = frame.index[3000]
    start = moment + pd.Timedelta(hours=horizon)
    expected = counts[(counts.index > start) & (counts.index <= start + pd.Timedelta(hours=1))].sum()
    assert frame.loc[moment, "label"] == expected


def test_target_slot_is_the_latest_one_already_observed():
    # A day ahead, yesterday's slot has not happened yet when predicting, so the one before is used.
    assert _slot_shift(24 * 12, 12, 288) == 23 * 12
    assert _slot_shift(1 * 12, 12, 288) == 22 * 12
    assert _slot_shift(6 * 12, 12, 2016) == 2016 - 84


def test_calendar_describes_the_target_hour():
    frame = build(series(), 6)
    moment = pd.Timestamp("2024-01-10 20:00")
    assert frame.loc[moment, "hour"] == 2 and frame.loc[moment, "weekday"] == 3


def test_blocks_are_in_order_and_share_no_label():
    horizon = 6
    parts = short_horizon.blocks(build(series(days=200), horizon), horizon)
    names = ["train", "stop", "calibrate", "holdout"]
    for earlier, later in zip(names, names[1:], strict=False):
        label_end = parts[earlier].index.max() + pd.Timedelta(hours=horizon + 1)
        assert label_end <= parts[later].index.min()
    assert all(len(parts[name]) > 0 for name in names)


def test_bounds_hold_about_as_often_as_they_say():
    horizon = 1
    frame = build(series(days=260, seed=3), horizon)
    parts = short_horizon.blocks(frame, horizon)
    features = [f for f in FEATURES if not f.startswith(("temperature", "rain"))]
    forecast = short_horizon.fit(parts, horizon, features)
    held = parts["holdout"]
    coverage = (held["label"].to_numpy() <= forecast.upper(held)).mean()
    assert 0.92 <= coverage <= 0.98


def test_taxi_records_that_are_not_rides_are_dropped():
    text = (
        "start_time_local,trip_distance_meters,fare_time_milliseconds,sfo_pickup,paratransit,total_fare_amount\n"
        "2024-03-01T00:00:15.000,26017.53,1305000,1,0,64.25\n"
        "2024-03-01T00:00:56.807,0.0,11973,0,0,3.5\n"
        "2024-03-01T00:05:00.000,5000,600000,0,1,20\n"
    )
    rides = sftaxi.parse_month(text)
    assert len(rides) == 1
    assert rides[0]["airport"] and rides[0]["miles"] == pytest.approx(16.17, abs=0.01)


def test_weather_archive_parses():
    text = '{"hourly":{"time":["2024-03-01T00:00","2024-03-01T01:00"],"temperature_2m":[11.5,null],"precipitation":[0.2,0.0]}}'
    rows = weather.parse(text)
    assert rows == [
        {"time": pd.Timestamp("2024-03-01 00:00").to_pydatetime(), "temperature_c": 11.5, "precipitation_mm": 0.2}
    ]
