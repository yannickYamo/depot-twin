"""The model workbench: one change at a time, and an honest measure of what a bound costs."""

import json
from pathlib import Path

import pytest

from depot_twin import workbench

PAGE = Path(__file__).parent.parent / "web" / "public" / "models.json"


def test_every_variant_changes_one_thing_from_the_reference():
    reference = workbench.VARIANTS[0]
    assert reference.ident == "reference"
    for variant in workbench.VARIANTS[1:]:
        changed = [
            name
            for name in ("features", "trees", "months", "target", "kind", "fault")
            if getattr(variant, name) != getattr(reference, name)
        ]
        assert len(changed) == 1, f"{variant.ident} changes {changed}"


def test_every_dial_has_a_variant_and_every_variant_a_dial():
    dials = {key for key, _, _ in workbench.DIALS}
    assert {v.dial for v in workbench.VARIANTS[1:]} == dials
    assert len({v.ident for v in workbench.VARIANTS}) == len(workbench.VARIANTS)


def test_reserve_counts_vehicles_held_and_rides_left_uncovered():
    # Two days at a flat 100 rides an hour, a fleet sized to offer exactly that.
    flat = {"actual": [100.0] * 48, "mean": [100.0] * 48, "upper": [126.0] * 24 + [90.0] * 24}
    result = workbench.reserve(flat, fleet=96, rides_per_vehicle_day=25.0)
    # Day one holds 26 rides an hour of spare cover, about ten vehicles; averaged over both days, five.
    assert result["vehicles_held_in_reserve"] == pytest.approx(13.0 / workbench.RIDES_PER_VEHICLE_HOUR, abs=0.1)
    # Day two leaves ten rides an hour uncovered: 240 over the day, 120 a day over the two.
    assert result["rides_above_the_bound_per_day"] == pytest.approx(120.0)


def test_a_broken_feed_is_charted_as_the_plan_received_it():
    days = {"mean": [300] * 336, "upper": [360] * 336, "actual": [310] * 336}
    broken = workbench._broken(days)
    assert broken["mean"][0] == 300 and broken["mean"][-1] == 99
    assert broken["actual"] == days["actual"]


def test_the_page_file_matches_the_variants_and_holds_no_gaps():
    page = json.loads(PAGE.read_text())
    assert set(page["variants"]) == {v.ident for v in workbench.VARIANTS}
    for ident, record in page["variants"].items():
        assert set(record["horizons"]) == {"1", "6", "24"}, ident
        assert len(record["days"]["actual"]) == workbench.DAYS * 24
        assert all(value is not None for value in record["decision"].values()), ident
    overfit, reference = page["variants"]["trees_3000"], page["variants"]["reference"]
    # The claim the page makes about training too long: training error lower, held-out error no better.
    assert overfit["curve"]["train"][-1] < reference["curve"]["train"][-1]
    assert overfit["horizons"]["1"]["error"] >= reference["horizons"]["1"]["error"]


def test_the_pretrained_forecast_is_read_for_the_rows_own_label_hour_and_never_from_the_future():
    # Rides are constant within each clock hour and different in every hour, and the hourly table is an
    # oracle that is right about every clock hour it forecasts. Read correctly, the forecast for a
    # five-minute row is then exactly its label, at every minute of the hour and every horizon. Read from
    # the wrong hour, or from a forecast made after the row, it is not.
    import numpy as np
    import pandas as pd

    from depot_twin.features import build

    index = pd.date_range("2024-03-04", periods=12 * 24 * 16, freq="5min")
    by_hour = pd.Series(np.random.default_rng(0).integers(20, 200, size=24 * 16).astype(float), index=index[::12])
    counts = (by_hour.reindex(index).ffill() / 12.0).rename("rides")
    horizons = workbench.pretrained_horizons()
    assert horizons == (1, 2, 6, 7, 24, 25)
    # A forecast from origin o, at horizon h, is of the clock hour h + 1 hours after o: the label convention.
    table = pd.DataFrame(
        {h: by_hour.shift(-(h + 1)) for h in horizons},
        index=by_hour.index,
    )
    made_with = {}

    class Recording(pd.DataFrame):
        def reindex(self, origins, *args, **kwargs):
            made_with["latest_origin_used"] = pd.DatetimeIndex(origins)
            return pd.DataFrame.reindex(self, origins, *args, **kwargs)

    for horizon in (1, 6, 24):
        rows = build(counts, horizon, 12).dropna(subset=["label"]).iloc[2000:2600]
        forecast = workbench.Pretrained(horizon, None, [], {})
        forecast.table = Recording(table)
        assert np.allclose(forecast.predict(rows), rows["label"].to_numpy())
        # The forecast used was made from a clock hour that had ended by the time the row's own step ended.
        known = rows.index + pd.Timedelta(minutes=5)
        assert (made_with["latest_origin_used"] + pd.Timedelta(hours=1) <= known).all()
