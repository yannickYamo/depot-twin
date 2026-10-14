"""The parts of E28 and E29 that can be held without running a depot, and the page file read from the backtest."""

import json

import numpy as np

from depot_twin import backtest_page
from depot_twin.data import data_dir
from depot_twin.evals import further, steer
from depot_twin.evals.common import E12_SETTINGS


def test_a_sharper_peak_raises_only_the_busiest_hours_and_keeps_the_total():
    rng = np.random.default_rng(0)
    week = np.repeat(rng.uniform(1.0, 9.0, size=168), further.STEPS_AN_HOUR)
    counts = np.concatenate([week, week])
    out = further.sharper(counts, 1.2, share=0.25)
    assert np.isclose(out.sum(), counts.sum())
    ratio = np.unique(np.round(out / counts, 9))
    assert len(ratio) == 2 and np.isclose(ratio[1] / ratio[0], 1.2)
    raised = (out > counts).reshape(2, 168, further.STEPS_AN_HOUR)
    assert (
        raised.all(axis=2).sum() == 2 * 42 and (raised[0] == raised[1]).all()
    )  # a quarter of 168 hours, the same in both weeks
    assert week.reshape(168, -1)[raised[0].all(axis=1)].min() >= week.reshape(168, -1)[~raised[0].any(axis=1)].max()


def test_a_factor_of_one_changes_nothing():
    counts = np.arange(2 * 168 * further.STEPS_AN_HOUR, dtype=float) + 1.0
    assert np.allclose(further.sharper(counts, 1.0), counts)


def test_the_plan_settings_are_moved_in_the_process_and_the_registered_ones_are_left_alone():
    from depot_twin import evals

    before = dict(E12_SETTINGS)
    try:
        steer._settings(0.25, 36, 0.5)
        moved, wanted = evals.E12_SETTINGS, before | {"peak_call_below": 0.25, "horizon": 36, "reserve_soc": 0.5}
        assert moved == wanted
        assert dict(E12_SETTINGS) == before
    finally:
        evals.E12_SETTINGS = E12_SETTINGS


def test_the_page_shows_the_backtests_own_means(tmp_path):
    record = json.loads((data_dir() / "derived" / "e24_backtest.json").read_text())
    page = json.loads(backtest_page.build(str(tmp_path / "backtest.json")).read_text())
    assert page["weeks"] == record["weeks"] and page["hours_ahead"] == 1
    for name, series in record["series"].items():
        for arm, theirs in backtest_page.ARMS.items():
            assert page["series"][name][arm]["error"] == series["1h"]["error"][theirs]["mean"]
