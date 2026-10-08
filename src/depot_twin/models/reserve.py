"""The reserve–coverage frontier: what a forecast's bound asks of a fleet at each level of reliability.

E16 found that a forecast's value at this depot is the reserve its upper bound makes the plan hold. So a
forecast is judged here by that reserve at a required reliability, and the point forecast and the bound
are judged apart. Two ways of sizing a bound are compared:

- symmetric: forecast plus a multiple of the square root of the forecast, the multiple set on the
  calibration block. This is the reference's bound.
- volume-aware: a relative part and a counting part combined in quadrature, both set on the calibration
  block. A bound that knows 500 expected rides and 2,000 do not share a residual scale.

Arms are compared at matched achieved coverage, read off each arm's frontier, never at matched nominal
coverage: a bound that says 95% and holds 90% is not a 95% bound.

Chronos-2 is used as one point forecast, zero-shot and univariate, with its model files pinned by commit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

# Required reliabilities the frontier is read at. Fine enough that reading the reserve at an achieved 95%
# between two of them is a short step: on five points the reading moved by several vehicles.
ALPHAS = tuple(round(0.85 + 0.005 * k, 3) for k in range(29))  # 0.85 to 0.99
RIDES_PER_VEHICLE_HOUR = 60.0 / 23.0
CHRONOS_MODEL = "amazon/chronos-2"
CHRONOS_CONTEXT = 2048  # hours: about twelve weeks


def _scale(actual: np.ndarray, fleet: int, rides_per_vehicle_day: float) -> float:
    """From the source series' rides to a fleet's."""
    return fleet * rides_per_vehicle_day / (actual.sum() / (len(actual) / 24.0))


def reserve_vehicles(actual: np.ndarray, upper: np.ndarray, scale: float) -> float:
    """Vehicles a fleet holds on the road, on average, for the part of the bound above the rides that came."""
    return float(np.clip(upper - actual, 0, None).mean() * scale / RIDES_PER_VEHICLE_HOUR)


def symmetric_bound(calib_actual, calib_pred, pred, alpha: float) -> np.ndarray:
    """The reference's bound: forecast plus a multiple of its square root, the multiple from the calibration block."""
    scaled = (calib_actual - calib_pred) / np.sqrt(calib_pred + 1.0)
    return np.maximum(0.0, pred + float(np.quantile(scaled, alpha)) * np.sqrt(pred + 1.0))


def volume_bound(calib_actual, calib_pred, pred, alpha: float) -> np.ndarray:
    """A bound with a relative part and a counting part; the relative width is the smallest that holds on the calibration block."""
    z = float(norm.ppf(alpha))

    def band(predicted: np.ndarray, relative: float) -> np.ndarray:
        return np.sqrt((relative * predicted) ** 2 + (z**2) * predicted)

    low, high = 0.0, 5.0
    for _ in range(40):
        middle = (low + high) / 2.0
        held = float((calib_actual - calib_pred <= band(calib_pred, middle)).mean())
        low, high = (low, middle) if held >= alpha else (middle, high)
    return np.maximum(0.0, pred + band(pred, high))


def frontier(calib_actual, calib_pred, actual, pred, kind: str, scale: float) -> list[dict]:
    """For each required reliability: the coverage achieved on the test days and the vehicles held for it."""
    make = symmetric_bound if kind == "symmetric" else volume_bound
    out = []
    for alpha in ALPHAS:
        upper = make(calib_actual, calib_pred, pred, alpha)
        out.append(
            {
                "nominal": alpha,
                "achieved": round(float((actual <= upper).mean()), 4),
                "reserve": round(reserve_vehicles(actual, upper, scale), 1),
                "width": round(float((upper - pred).sum() / max(pred.sum(), 1.0)), 4),
            }
        )
    return out


def reserve_at(points: list[dict], achieved: float = 0.95) -> float | None:
    """Reserve at a given achieved coverage, interpolated along the frontier; None when it is out of reach."""
    xs = np.array([p["achieved"] for p in points])
    ys = np.array([p["reserve"] for p in points])
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    if achieved < xs[0] or achieved > xs[-1]:
        return None
    return round(float(np.interp(achieved, xs, ys)), 1)


def chronos_points(counts: pd.Series, origins: pd.DatetimeIndex, horizons=(1, 6, 24), batch: int = 32) -> pd.DataFrame:
    """Chronos-2's point forecast (its median) for the hour starting each horizon after each origin.

    The context is the last CHRONOS_CONTEXT hours up to and including the origin. The label convention is
    the feature builder's: the hour scored for horizon h is the one h + 1 steps after the origin.
    """
    import torch
    from chronos import BaseChronosPipeline

    pipe = BaseChronosPipeline.from_pretrained(CHRONOS_MODEL, device_map="cpu", torch_dtype=torch.float32)
    values = counts.to_numpy(dtype=np.float32)
    position = {moment: k for k, moment in enumerate(counts.index)}
    steps = max(horizons) + 1
    rows = []
    for start in range(0, len(origins), batch):
        chunk = origins[start : start + batch]
        contexts = []
        for origin in chunk:
            end = position[origin] + 1
            contexts.append(values[max(0, end - CHRONOS_CONTEXT) : end])
        shortest = min(len(c) for c in contexts)
        tensor = torch.tensor(np.stack([c[-shortest:] for c in contexts])[:, None, :])
        quantiles, _ = pipe.predict_quantiles(tensor, prediction_length=steps, quantile_levels=[0.5])
        for origin, q in zip(chunk, quantiles, strict=True):
            path = q[0, :, 0].numpy()
            rows.append({"origin": origin, **{h: float(max(0.0, path[h])) for h in horizons}})
    return pd.DataFrame(rows).set_index("origin")


def pinned_versions() -> dict:
    """The exact Chronos-2 files and package used, for the record."""
    import importlib.metadata as metadata

    from huggingface_hub import model_info

    return {
        "model": CHRONOS_MODEL,
        "model_commit": model_info(CHRONOS_MODEL).sha,
        "chronos_forecasting": metadata.version("chronos-forecasting"),
        "torch": metadata.version("torch"),
        "context_hours": CHRONOS_CONTEXT,
        "covariates": "none; univariate, zero-shot",
    }
