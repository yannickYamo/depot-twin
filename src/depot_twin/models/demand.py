"""Week-ahead forecast of hourly ride-hail demand.

Depot planning needs to know, a week out, how many vehicles must be on the road each hour, because that
decides when vehicles can be pulled in to charge. The forecast therefore only uses information at least a
week old: the same hour in earlier weeks, the calendar, and the slow trend.

The model to beat is "same hour last week". It is hard to beat on an ordinary week and badly wrong around
holidays and seasonal turns, which is where the calendar features earn their place.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xgboost as xgb
from pandas.tseries.holiday import USFederalHolidayCalendar

WEEK = 168
FEATURES = [
    "hour",
    "weekday",
    "month",
    "holiday",
    "holiday_eve",
    "lag_1w",
    "lag_2w",
    "lag_3w",
    "lag_4w",
    "mean_4w",
    "level_4w",
]
# Fixed before the evaluation run; not tuned on the held-out months.
PARAMS = {
    "objective": "count:poisson",
    "n_estimators": 400,
    "learning_rate": 0.05,
    "max_depth": 6,
    "colsample_bytree": 0.9,
    "random_state": 7,
    "n_jobs": 4,
}


def hourly_frame(rows: list[dict]) -> pd.DataFrame:
    """Turn loader rows into a gap-free hourly series of trips."""
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["day"]) + pd.to_timedelta(frame["hour"], unit="h")
    series = frame.set_index("time")["trips"].sort_index()
    full = pd.date_range(series.index.min(), series.index.max(), freq="h")
    return series.reindex(full, fill_value=0).rename("trips").to_frame()


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add calendar and week-old history features. Nothing newer than one week is used."""
    out = frame.copy()
    index = out.index
    out["hour"] = index.hour
    out["weekday"] = index.dayofweek
    out["month"] = index.month
    holidays = USFederalHolidayCalendar().holidays(start=index.min(), end=index.max() + pd.Timedelta(days=1))
    out["holiday"] = index.normalize().isin(holidays).astype(int)
    out["holiday_eve"] = (index.normalize() + pd.Timedelta(days=1)).isin(holidays).astype(int)
    for weeks in (1, 2, 3, 4):
        out[f"lag_{weeks}w"] = out["trips"].shift(WEEK * weeks)
    out["mean_4w"] = out[["lag_1w", "lag_2w", "lag_3w", "lag_4w"]].mean(axis=1)
    # Overall demand level across all hours of the four weeks ending one week ago.
    out["level_4w"] = out["trips"].shift(WEEK).rolling(WEEK * 4).mean()
    return out.dropna()


def wape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Return the weighted absolute percentage error: total absolute error over total demand."""
    return float(np.abs(actual - predicted).sum() / actual.sum())


@dataclass
class Backtest:
    """How the forecast and the baseline did on months neither had seen."""

    cutoff: str
    hours: int
    model_wape: float
    naive_wape: float

    @property
    def improvement(self) -> float:
        """Return the share of the baseline's error the model removes."""
        return 1.0 - self.model_wape / self.naive_wape


def train(frame: pd.DataFrame) -> xgb.XGBRegressor:
    """Fit the forecast on a feature frame."""
    model = xgb.XGBRegressor(**PARAMS)
    model.fit(frame[FEATURES], frame["trips"])
    return model


def backtest(frame: pd.DataFrame, holdout_days: int = 91) -> tuple[xgb.XGBRegressor, Backtest]:
    """Train on everything before the last holdout_days and score both forecasts on those days."""
    features = add_features(frame)
    cutoff = features.index.max() - pd.Timedelta(days=holdout_days)
    past, future = features[features.index <= cutoff], features[features.index > cutoff]
    model = train(past)
    actual = future["trips"].to_numpy()
    result = Backtest(
        cutoff=str(cutoff),
        hours=len(future),
        model_wape=wape(actual, model.predict(future[FEATURES])),
        naive_wape=wape(actual, future["lag_1w"].to_numpy()),
    )
    return model, result


def weekly_shape(model: xgb.XGBRegressor, frame: pd.DataFrame) -> np.ndarray:
    """Return the forecast for the final week of the frame as 168 hourly shares of the week's demand.

    The first value is Monday 00:00. The shape, not the level, is what the fleet simulation consumes.
    """
    features = add_features(frame).iloc[-WEEK:]
    predicted = pd.Series(model.predict(features[FEATURES]), index=features.index)
    by_slot = predicted.groupby([predicted.index.dayofweek, predicted.index.hour]).mean()
    shape = by_slot.to_numpy()
    return shape / shape.sum()


def walk_forward(frame: pd.DataFrame, folds: int = 4, window_days: int = 28, reserve_days: int = 91) -> list[dict]:
    """Score the forecast on successive four-week windows, each trained only on what came before it.

    The windows all end before the final reserve_days, so this never looks at the held-out period of the
    registered evaluation. Each window also scores a variant whose number of trees is set by early
    stopping on the four weeks before it, to check whether the fixed 400 trees are costing anything.
    """
    features = add_features(frame)
    end = features.index.max() - pd.Timedelta(days=reserve_days)
    window = pd.Timedelta(days=window_days)
    results = []
    for fold in range(folds):
        stop = end - fold * window
        start = stop - window
        past = features[features.index <= start]
        test = features[(features.index > start) & (features.index <= stop)]
        inner = past[past.index > start - window]
        earlier = past[past.index <= start - window]
        stopped = xgb.XGBRegressor(**{**PARAMS, "n_estimators": 3000}, early_stopping_rounds=60, eval_metric="mae")
        stopped.fit(earlier[FEATURES], earlier["trips"], eval_set=[(inner[FEATURES], inner["trips"])], verbose=False)
        actual = test["trips"].to_numpy()
        results.append(
            {
                "window_end": str(stop.date()),
                "fixed_trees_wape": round(wape(actual, train(past).predict(test[FEATURES])), 4),
                "early_stopped_wape": round(wape(actual, stopped.predict(test[FEATURES])), 4),
                "early_stopped_trees": int(stopped.best_iteration) + 1,
                "naive_wape": round(wape(actual, test["lag_1w"].to_numpy()), 4),
            }
        )
    return results
