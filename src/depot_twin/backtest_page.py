"""The backtest's one-hour errors as the page reads them.

The page's Decisions tab sets three forecasts side by side in each city. For Chicago and New York the comparison
to rely on is E24, 26 weekly origins with a refit before each, and this writes its mean weekly error one
hour ahead to `web/public/backtest.json`. Nothing is forecast again.
"""

from __future__ import annotations

import json
from pathlib import Path

from depot_twin import provenance
from depot_twin.data import data_dir

ARMS = {"last_week": "last_week", "reference": "trained_here", "chronos": "pretrained"}  # the page's name: E24's


def build(out: str = "web/public/backtest.json") -> Path:
    """Write each series' mean weekly error one hour ahead under the three forecasts the page compares."""
    record = json.loads((data_dir() / "derived" / "e24_backtest.json").read_text())
    page = {
        "eval": record["eval"],
        "weeks": record["weeks"],
        "hours_ahead": 1,
        "series": {
            name: {arm: {"error": series["1h"]["error"][theirs]["mean"]} for arm, theirs in ARMS.items()}
            for name, series in record["series"].items()
        },
        "code": provenance.page_stamp("web/public/backtest.json"),
    }
    path = Path(out)
    path.write_text(json.dumps(page, indent=1) + "\n")
    return path


if __name__ == "__main__":
    print(build())
