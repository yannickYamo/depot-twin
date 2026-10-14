"""The backtest's ranges again, with neighbouring weeks kept together.

E24 gives each mean over its 26 weeks a range by resampling whole weeks one at a time. Consecutive weeks
of a ride series are not independent: a slow month is several slow weeks in a row, and resampling them
singly can make a range too narrow. This reads the weekly figures E24 recorded and resamples them in
blocks of four consecutive weeks (a moving-block bootstrap, the blocks wrapping round the end), and
writes both ranges side by side in `data/derived/e24_blocks.json`. Nothing is forecast again.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from depot_twin import provenance
from depot_twin.data import data_dir

BLOCK_WEEKS = 4
DRAWS = 2000
PAIRS = (("trained_here", "last_week"), ("pretrained", "trained_here"), ("both", "pretrained"))


def over_blocks(values: list[float], block: int = BLOCK_WEEKS, draws: int = DRAWS, seed: int = 0) -> dict:
    """A mean over weeks with the range that resampling blocks of consecutive weeks gives it (5th to 95th percentile)."""
    array = np.asarray(values, dtype=float)
    n = len(array)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(draws, -(-n // block)))
    index = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    means = array[index.reshape(draws, -1)[:, :n]].mean(axis=1)
    return {
        "mean": round(float(array.mean()), 4),
        "low": round(float(np.quantile(means, 0.05)), 4),
        "high": round(float(np.quantile(means, 0.95)), 4),
    }


def study() -> Path:
    """Write the block ranges of every error and paired difference E24 reports, beside the week-by-week ones."""
    derived = data_dir() / "derived"
    record = json.loads((derived / "e24_backtest.json").read_text())
    out: dict = {}
    for name, series in record["series"].items():
        out[name] = {}
        for horizon in ("1h", "24h"):
            weekly = series[horizon]["error_by_week"]
            cell = {"error": {}, "difference": {}}
            for model, values in weekly.items():
                cell["error"][model] = {"blocks": over_blocks(values), "single_weeks": series[horizon]["error"][model]}
            for first, second in PAIRS:
                apart = [a - b for a, b in zip(weekly[first], weekly[second], strict=True)]
                key = f"{first}_less_{second}"
                blocks = over_blocks(apart)
                cell["difference"][key] = {
                    "blocks": blocks,
                    "single_weeks": series[horizon]["difference"][key],
                    "same_sign_under_blocks": blocks["low"] * blocks["high"] > 0,
                }
            out[name][horizon] = cell
    wider = [
        (row["blocks"]["high"] - row["blocks"]["low"])
        / max(row["single_weeks"]["high"] - row["single_weeks"]["low"], 1e-9)
        for series in out.values()
        for cell in series.values()
        for row in cell["difference"].values()
    ]
    payload = {
        "study": "E24's ranges with weeks resampled in blocks",
        "block_weeks": BLOCK_WEEKS,
        "draws": DRAWS,
        "weeks": record["weeks"],
        "series": out,
        "width_of_a_difference_range_against_single_weeks": {
            "median": round(float(np.median(wider)), 2),
            "largest": round(float(np.max(wider)), 2),
        },
        "code": provenance.page_stamp("data/derived/e24_blocks.json"),
    }
    target = derived / "e24_blocks.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target
