"""The cross-city forecast: pooled over series, and bounded by errors on places it never saw."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xgboost")

from depot_twin.models import transfer  # noqa: E402
from tests.test_synth import donor  # noqa: E402


def rows(name: str, level: float, seed: int, horizon: int = 1) -> pd.DataFrame:
    return transfer.rows_for(name, donor(weeks=16, level=level, seed=seed), horizon, None)


def test_weights_do_not_let_a_large_city_drown_a_small_one():
    big, small = rows("big", 5000.0, 1), rows("small", 50.0, 2)
    assert big["weight"].mean() == pytest.approx(1.0)
    assert small["weight"].mean() == pytest.approx(1.0)


def test_rows_stop_before_the_cutoff():
    cutoff = pd.Timestamp("2024-03-01")
    kept = transfer.rows_for("a", donor(weeks=16), 6, None, until=cutoff)
    assert (kept.index + pd.Timedelta(hours=7) <= cutoff).all()


def test_no_feature_names_a_place_or_a_season():
    assert not {"month", "temperature_now", "temperature_target", "minute_of_day"} & set(transfer.FEATURES)


def test_a_model_trained_on_large_places_forecasts_a_small_one():
    groups = {"a": rows("a", 4000.0, 1), "b": rows("b", 900.0, 2)}
    forecast = transfer.fit_site(1, groups)
    unseen = rows("c", 60.0, 3)
    result = transfer.score(forecast, unseen)
    naive = transfer.wape(unseen["label"].to_numpy(), unseen["target_slot_last_week"].to_numpy())
    assert result["wape"] < naive
    assert result["upper_coverage"] > 0.85


def test_relative_bound_is_the_smallest_that_holds():
    rng = np.random.default_rng(0)
    predicted = np.full(20000, 1000.0)
    actual = predicted * (1.0 + 0.1 * rng.standard_normal(20000))
    width = transfer.relative_bound(actual, predicted, upper=True)
    held = (actual - predicted <= np.sqrt((width * predicted) ** 2 + transfer.Z_95**2 * predicted)).mean()
    assert held == pytest.approx(0.95, abs=0.005)
    assert 0.1 < width < 0.2
