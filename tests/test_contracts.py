"""The data contracts: what a series must satisfy, and the registry of which days serve which purpose."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from depot_twin import evals
from depot_twin.data import contracts, registry


def hourly(days: int, level: float = 100.0, seed: int = 0) -> pd.Series:
    index = pd.date_range("2024-01-01", periods=days * 24, freq="h")
    return pd.Series(np.random.default_rng(seed).poisson(level, len(index)).astype(float), index=index)


def test_a_clean_series_passes_and_an_outage_is_flagged():
    clean = contracts.audit("clean", hourly(70))
    assert clean.sound and clean.regular and clean.unique and clean.step_minutes == 60
    broken = hourly(70)
    broken.iloc[200:212] = 0.0
    found = contracts.audit("broken", broken)
    assert not found.sound
    assert found.zero_runs == [("2024-01-09 08:00:00", 12)]


def test_a_duplicate_moment_and_an_irregular_index_are_caught():
    series = hourly(10)
    doubled = pd.concat([series, series.iloc[[5]]]).sort_index()
    assert not contracts.audit("doubled", doubled).unique
    assert not contracts.audit("gappy", series.drop(series.index[[7, 8]])).regular


def test_a_level_shift_is_dated():
    series = hourly(120)
    series.iloc[60 * 24 :] *= 1.5
    shifts = contracts.audit("shift", series).level_shifts
    assert len(shifts) == 1
    assert shifts[0][0].startswith("2024-02") and shifts[0][1] > 1.25


def test_daylight_saving_hours_are_counted():
    index = pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h")
    found = contracts.dst_hours(index)
    assert [str(m) for m in found] == ["2024-03-10 02:00:00", "2024-11-03 01:00:00"]


def test_generated_rows_may_only_be_trained_on():
    rows = pd.DataFrame({"series": ["generated_3", "generated_3"], "label": [1.0, 2.0]})
    with pytest.raises(ValueError):
        contracts.assert_real(rows, "scoring")
    contracts.assert_real(rows.assign(series="nyc_ridehail_city"), "scoring")


def test_the_registry_has_no_window_serving_two_purposes():
    assert registry.conflicts() == []
    assert registry.purpose_of("sf_taxi", date(2024, 3, 20)) == "development"
    assert registry.purpose_of("sf_taxi", date(2024, 5, 15)) == "test"
    assert registry.purpose_of("chicago_ridehail_city", date(2026, 2, 1)) == "test"


def test_the_evaluations_run_on_the_days_the_registry_says():
    assert registry.window("sf_dev").start.isoformat() == evals.E8_DEV_START
    assert registry.window("sf_e8").start.isoformat() == evals.E8_START
    assert registry.window("sf_e12").start.isoformat() == evals.E12_START
    assert registry.window("sf_e9").start.isoformat() == evals.E9_START
    assert registry.window("chicago_depot").start.isoformat() == evals.E14_START
    for ident in ("chicago_forecast_confirm", "nyc_forecast_confirm"):
        assert registry.window(ident).start.isoformat() == evals.E17_WINDOW[0]
        assert registry.window(ident).used_by[0] == "E17"
    assert registry.window("nyc_yellow_confirm").used_by == ("E18",)


def test_the_clock_changes_leave_no_zero_hour_and_no_doubled_hour():
    index = pd.date_range("2025-03-01", "2025-11-10", freq="h", inclusive="left")
    rides = pd.Series(100.0, index=index)
    rides[pd.Timestamp("2025-03-09 02:00")] = 0.0  # the hour that does not exist
    rides[pd.Timestamp("2025-11-02 01:00")] = 200.0  # the hour that happens twice
    steady = contracts.steady_clock(rides)
    assert (steady == 100.0).all()
    kept = contracts.steady_clock(rides, doubled_hour=False)
    assert kept[pd.Timestamp("2025-11-02 01:00")] == 200.0 and kept[pd.Timestamp("2025-03-09 02:00")] == 100.0
    five = pd.Series(10.0, index=pd.date_range("2025-03-08", "2025-03-11", freq="5min", inclusive="left"))
    five[(five.index >= "2025-03-09 02:00") & (five.index < "2025-03-09 03:00")] = 0.0
    assert (contracts.steady_clock(five) == 10.0).all()
