"""A stronger naive forecast than last week's hour, set beside E24's models on the same weeks.

E24 compares its models with the same hour last week. At a depot's scale, 500 rides an hour, last week's
count is one noisy draw, so that baseline is easy to beat by averaging alone. This study builds the
baseline a planner with no model would use: the mean of the same hour over several past weeks, scaled by
how the hours just gone compare with their own means. Its two settings, how many weeks and how long a
recent window, are chosen on the 26 weeks before E24's first test week and then held. It needs the ride
series (`depot-twin data donors`); the weekly errors of E24's models are read from its record.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from depot_twin import provenance
from depot_twin.data import data_dir

SERIES = {
    "chicago": "chicago_ridehail_city",
    "nyc_ridehail": "nyc_ridehail_city",
    "nyc_yellow": "nyc_yellow_city",
}
WEEKS_IN_MEAN = (1, 2, 4, 6, 8)
RECENT_HOURS = (0, 6, 24, 48, 168)  # 0: no scaling by the hours just gone
THINNING_SEED = 24  # E24's draw


def candidates(counts, horizon: int) -> dict:
    """Every setting of the baseline, as a forecast for each hour made `horizon` hours before it."""
    import pandas as pd

    known = horizon + 1  # the latest hour whose count is in when the forecast is made
    out = {}
    for weeks in WEEKS_IN_MEAN:
        usual = pd.concat([counts.shift(168 * k) for k in range(1, weeks + 1)], axis=1).mean(axis=1)
        out[(weeks, 0)] = usual
        for recent in RECENT_HOURS[1:]:
            came = sum(counts.shift(known + k) for k in range(recent))
            expected = sum(usual.shift(known + k) for k in range(recent))
            out[(weeks, recent)] = usual * (came / expected.clip(lower=1.0))
    return out


def weekly_error(counts, forecast, origins) -> np.ndarray:
    """Total absolute error over total rides, for the 168 hours from each origin."""
    import pandas as pd

    week = pd.Timedelta(hours=167)
    out = []
    for origin in origins:
        actual, predicted = counts[origin : origin + week].to_numpy(), forecast[origin : origin + week].to_numpy()
        out.append(float(np.abs(actual - predicted).sum() / max(actual.sum(), 1.0)))
    return np.array(out)


def study() -> Path:
    """Write the baseline's weekly errors beside E24's, with the paired differences."""
    import pandas as pd

    from depot_twin import newsite
    from depot_twin.data import donors
    from depot_twin.models import backtest

    derived = data_dir() / "derived"
    record = json.loads((derived / "e24_backtest.json").read_text())
    panel = donors.load_panel()
    out: dict = {}
    for name, column in SERIES.items():
        counts = newsite.thinned(panel[column].dropna(), float(record["scale_rides_per_hour"]), seed=THINNING_SEED)
        origins = backtest.weekly_origins(counts.index.max(), record["weeks"])
        before = [origins[0] - pd.Timedelta(weeks=k) for k in range(record["weeks"], 0, -1)]
        out[name] = {}
        for horizon in (1, 24):
            recorded = record["series"][name][f"{horizon}h"]["error_by_week"]
            options = candidates(counts, horizon)
            # The record's last-week column, made again from the series, shows the series is the one E24 saw.
            again = weekly_error(counts, counts.shift(168), origins)
            chosen_on = {
                key: float(np.nanmean(weekly_error(counts, option, before))) for key, option in options.items()
            }
            weeks, recent = min(chosen_on, key=lambda key: chosen_on[key])
            errors = weekly_error(counts, options[(weeks, recent)], origins)
            cell = {
                "weeks_in_the_mean": weeks,
                "recent_hours_scaled_by": recent,
                "error_on_the_weeks_it_was_chosen_on": round(chosen_on[(weeks, recent)], 4),
                "error_by_week": [round(float(v), 4) for v in errors],
                "error": backtest.over_weeks(list(errors)),
                "last_week_made_again_matches_the_record": bool(np.allclose(again, recorded["last_week"], atol=6e-5)),
                "difference": {},
            }
            for model in ("last_week", "trained_here", "pretrained"):
                apart = np.array(recorded[model]) - errors
                cell["difference"][f"{model}_less_baseline"] = backtest.over_weeks(list(apart)) | {
                    "median": round(float(np.median(apart)), 4),
                    "weeks_the_model_is_better": int((apart < 0).sum()),
                    "weeks": len(apart),
                }
            out[name][f"{horizon}h"] = cell
    payload = {
        "study": "E24's models against a naive forecast that averages past weeks and follows the hours just gone",
        "chosen_on": f"the {record['weeks']} weeks before E24's first test week",
        "weeks": record["weeks"],
        "series": out,
        "code": provenance.page_stamp("data/derived/e24_baseline.json"),
    }
    target = derived / "e24_baseline.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target
