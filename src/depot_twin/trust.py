"""How much to trust the reference forecast: the figures the page's "under the hood" views are drawn from.

Everything here is computed from the same blocks the model was built on, and written to one file the
front end reads (`web/public/trust.json`). Nothing is typed in. What it holds:

- the split: the dates of the training, stopping, calibration and held-out blocks of the San Francisco
  series, and the fortnight the depot is run on, so the page can draw the time line;
- failure slices: error on the held-out block by time of day, weekday and weekend, demand quartile and
  holidays, for the model and for "same hour last week";
- what the model leans on, two ways: XGBoost gain, which is descriptive, and permutation loss on the
  calibration block, which says whether taking a feature away hurts;
- the reserve frontier for the model's bound on this city: requested coverage, achieved coverage, and the
  vehicles held for it, beside the frontiers E18 recorded for the other cities and the pretrained model;
- the model card's facts: algorithm, objective, rows, trees, horizons, blocks.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from depot_twin.data import data_dir
from depot_twin.features import FEATURES, build
from depot_twin.models import short_horizon
from depot_twin.models.reserve import ALPHAS, frontier, reserve_at
from depot_twin.models.short_horizon import wape
from depot_twin.workbench import FLEET, START, _counts_and_weather

PERIODS = [
    ("Overnight (0 to 6)", 0, 6),
    ("Morning (6 to 10)", 6, 10),
    ("Midday (10 to 16)", 10, 16),
    ("Evening peak (16 to 21)", 16, 21),
    ("Late evening (21 to 24)", 21, 24),
]
RIDES_PER_VEHICLE_DAY = 25.0
PERMUTATIONS = 5


def _fit_reference(parts: dict) -> short_horizon.Forecast:
    """The reference model at one hour, built exactly as the workbench builds it."""
    from depot_twin.workbench import VARIANTS, _fit

    reference = next(v for v in VARIANTS if v.ident == "reference")
    return _fit(reference, parts, 1)


def split_dates(parts: dict) -> dict:
    """First and last day of each block, and how many rows each holds."""
    out = {}
    for name, rows in parts.items():
        out[name] = {"from": str(rows.index.min().date()), "to": str(rows.index.max().date()), "rows": int(len(rows))}
    out["fortnight"] = {"from": START, "to": str((pd.Timestamp(START) + pd.Timedelta(days=13)).date())}
    return out


def _slice_rows(rows: pd.DataFrame, actual: np.ndarray, model: np.ndarray, last_week: np.ndarray) -> list[dict]:
    """Error by slice on one block: n, model, last week."""
    hour = rows["hour"].to_numpy()
    out = []

    def add(name: str, mask: np.ndarray) -> None:
        if mask.sum() == 0:
            return
        out.append(
            {
                "slice": name,
                "n": int(mask.sum()),
                "model": round(wape(actual[mask], model[mask]), 4),
                "last_week": round(wape(actual[mask], last_week[mask]), 4),
            }
        )

    add("All hours", np.ones(len(rows), dtype=bool))
    for name, low, high in PERIODS:
        add(name, (hour >= low) & (hour < high))
    weekend = rows["weekend"].to_numpy() == 1
    add("Weekdays", ~weekend)
    add("Weekends", weekend)
    quartiles = np.quantile(actual, [0.25, 0.5, 0.75])
    add("Quietest quarter of hours", actual <= quartiles[0])
    add("Busiest quarter of hours", actual > quartiles[2])
    add("Holidays", rows["holiday"].to_numpy() == 1)
    return out


def permutation_importance(forecast: short_horizon.Forecast, rows: pd.DataFrame, seed: int = 0) -> list[dict]:
    """How much the error rises on the calibration block when one of the model's inputs is shuffled.

    The shuffle is done on what the model is handed, after the series have been divided by last week's
    rides, and the forecast is then scaled back by each row's own last week. Shuffling the raw column would
    do two things at once for the ratio model: move an input, and move the level every row's forecast is
    multiplied by. That measures the multiplication, not what the trees learnt. Forecasts with no model
    behind them (last week alone, a pretrained table) are shuffled as rows, the only way they can be.
    """
    rng = np.random.default_rng(seed)
    actual = rows["label"].to_numpy()
    base = wape(actual, forecast.predict(rows))
    ratio = forecast.scale_free and forecast.model is not None
    inputs = short_horizon._inputs(rows, forecast.features, True) if ratio else None
    level = short_horizon._reference(rows) if ratio else None
    out = []
    for name in forecast.features:
        losses = []
        for _ in range(PERMUTATIONS):
            if ratio:
                shuffled = inputs.copy()
                shuffled[name] = rng.permutation(shuffled[name].to_numpy())
                predicted = np.maximum(0.0, forecast.model.predict(shuffled) * level)
            else:
                moved = rows.copy()
                moved[name] = rng.permutation(moved[name].to_numpy())
                predicted = forecast.predict(moved)
            losses.append(wape(actual, predicted) - base)
        out.append({"feature": name, "loss": round(float(np.mean(losses)), 4)})
    return sorted(out, key=lambda row: -row["loss"])


def gain_importance(forecast: short_horizon.Forecast) -> dict[str, float]:
    """XGBoost gain, as a share of the total."""
    gains = forecast.model.get_booster().get_score(importance_type="gain")
    total = sum(gains.values()) or 1.0
    return {name: round(value / total, 4) for name, value in gains.items()}


def sf_frontier(forecast: short_horizon.Forecast, parts: dict) -> list[dict]:
    """The reserve frontier of a forecast's symmetric bound on the held-out block of this city."""
    from depot_twin.models.reserve import _scale

    calib, hold = parts["calibrate"], parts["holdout"]
    actual = hold["label"].to_numpy()
    scale = _scale(actual, FLEET, RIDES_PER_VEHICLE_DAY)
    return frontier(
        calib["label"].to_numpy(), forecast.predict(calib), actual, forecast.predict(hold), "symmetric", scale
    )


def pretrained_table(parts: dict) -> pd.DataFrame:
    """The pretrained model's forecasts for this city, from the calibration block to the end of the series."""
    from depot_twin.workbench import _counts_and_weather, _pretrained_table

    counts, _ = _counts_and_weather()
    return _pretrained_table(counts, parts["calibrate"].index.min())


def sf_arms(parts: dict, reference: short_horizon.Forecast, table: pd.DataFrame) -> dict:
    """Error and the reserve at 95% achieved coverage for last week, the reference and the pretrained model, on this city.

    The three are compared the way E18 compares them, at matched achieved coverage read off each one's
    frontier, never at matched nominal coverage. The pretrained model's forecasts are made here, which
    takes a few minutes on a CPU; the workbench made the same ones for its own record.
    """
    from depot_twin.workbench import VARIANTS, _fit

    hold = parts["holdout"]
    actual = hold["label"].to_numpy()
    arms = {}
    for ident in ("last_week", "reference", "chronos"):
        variant = next(v for v in VARIANTS if v.ident == ident)
        forecast = reference if ident == "reference" else _fit(variant, parts, 1, table if ident == "chronos" else None)
        points = sf_frontier(forecast, parts)
        arms[ident] = {
            "error": round(wape(actual, forecast.predict(hold)), 4),
            "reserve_at_95": reserve_at(points, 0.95),
            "frontier": points,
        }
    return arms


def other_cities() -> dict:
    """E18's one-hour frontiers and reserves at 95% achieved, per city and arm, from its record."""
    record = json.loads((data_dir() / "derived" / "e18_reserve.json").read_text())
    arms = {
        "last_week_1h": "last_week",
        "A_reference_bound_1h": "reference",
        "C_chronos_1h": "chronos",
        "D_ensemble_1h": "ensemble",
    }
    out = {}
    for city, table in record["series"].items():
        out[city] = {
            arms[key]: {
                "error": table[key]["error"],
                "reserve_at_95": table[key]["reserve_at_95_achieved"],
                "frontier": table[key]["frontier"],
            }
            for key in arms
            if key in table
        }
    return out


def variant_figures(parts: dict, reference: short_horizon.Forecast, table: pd.DataFrame | None) -> dict:
    """Every workbench variant at one hour: error, slices, importances, frontier and card, so the page follows the chosen one.

    The fault variants share the reference's forecast and are left out; the no-local variant is fitted the
    way the workbench fits it.
    """
    from depot_twin.workbench import VARIANTS, _fit, _recent, _trees, _without_local_history

    hold = parts["holdout"]
    actual = hold["label"].to_numpy()
    last_week = hold[short_horizon.REFERENCE].to_numpy().astype(float)
    out = {}
    for variant in VARIANTS:
        if variant.fault:
            continue
        if variant.ident == "reference":
            forecast = reference
        elif variant.kind == "no_local":
            forecast = _without_local_history(1)
        else:
            forecast = _fit(variant, parts, 1, table if variant.kind == "pretrained" else None)
        predicted = forecast.predict(hold)
        points = sf_frontier(forecast, parts)
        trained = variant.kind == "trained"
        record = {
            "error": round(wape(actual, predicted), 4),
            "reserve_at_95": reserve_at(points, 0.95),
            "frontier": points,
            "slices": _slice_rows(hold, actual, predicted, last_week),
            "card": {
                "kind": variant.kind,
                "target": "rides in the target hour"
                if variant.target != "ratio"
                else "ratio to the same hour last week",
                "trees": _trees(forecast) if trained else None,
                "rows": int(len(_recent(parts["train"], variant.months))) if trained else None,
                "features": len(variant.features) if trained else None,
            },
        }
        if trained:
            gains = gain_importance(forecast)
            record["importance"] = [
                {"feature": row["feature"], "gain": gains.get(row["feature"], 0.0), "permutation_loss": row["loss"]}
                for row in permutation_importance(forecast, parts["calibrate"])
            ]
        out[variant.ident] = record
    return out


def build_trust(out: str = "web/public/trust.json") -> Path:
    """Fit the reference once and write every figure the trust views need."""
    counts, weather = _counts_and_weather()
    parts = short_horizon.blocks(build(counts, 1, 12, weather), 1)
    forecast = _fit_reference(parts)
    hold = parts["holdout"]
    actual = hold["label"].to_numpy()
    model = forecast.predict(hold)
    last_week = hold[short_horizon.REFERENCE].to_numpy().astype(float)
    gains = gain_importance(forecast)
    table = pretrained_table(parts)
    workbench = json.loads(Path("web/public/models.json").read_text())
    page = {
        "split": split_dates(parts),
        "slices": _slice_rows(hold, actual, model, last_week),
        "importance": [
            {"feature": row["feature"], "gain": gains.get(row["feature"], 0.0), "permutation_loss": row["loss"]}
            for row in permutation_importance(forecast, parts["calibrate"])
        ],
        "frontier_sf": sf_frontier(forecast, parts),
        "sf": sf_arms(parts, forecast, table),
        "variants": variant_figures(parts, forecast, table),
        "alphas": list(ALPHAS),
        "cities": other_cities(),
        "sf_workbench": {
            ident: {
                "error": workbench["variants"][ident]["horizons"]["1"]["error"],
                "reserve_at_nominal_95": workbench["variants"][ident]["reserve"]["vehicles_held_in_reserve"],
            }
            for ident in ("last_week", "reference", "chronos")
            if ident in workbench["variants"]
        },
        "card": {
            "algorithm": "XGBoost, gradient-boosted trees",
            "objective": "squared error on the ratio to the same hour last week",
            "rows": int(len(parts["train"])),
            "trees": int(getattr(forecast.model, "best_iteration", 0) or 0) + 1,
            "features": len(FEATURES),
            "horizons": [1, 6, 24],
            "holdout_days": short_horizon.HOLDOUT_DAYS,
            "stop_days": short_horizon.STOP_DAYS,
            "calibration_days": short_horizon.CALIBRATION_DAYS,
        },
    }
    path = Path(out)
    path.write_text(json.dumps(page, separators=(",", ":")))
    return path
