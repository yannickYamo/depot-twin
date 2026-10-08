# Model card: the ride forecasts

**Model card: the ride forecasts in the depot twin. What the trained models are, what they were trained on, what they're for, and what they must not be taken for. This ships with each release as `out/release/`, built by `depot-twin package`.**

## The models

| File | What | Trained on | Scored |
|---|---|---|---|
| `forecast_ratio_{1,6,24}h.json`, `forecast_ratio_bounds.json` | XGBoost, one per horizon, predicting the ratio of a coming hour's rides to the same hour last week, with a symmetric bound, a residual quantile sized on a calibration block | San Francisco taxi trips (SFMTA, PDDL), training rows from 8 December 2022 to 5 February 2024 with the stop and calibration blocks running to 1 April 2024, hourly rates at five-minute steps, with weather from Open-Meteo's archive of past forecasts | E7b: 11.4%, 11.9% and 12.3% error on the last 60 days; bound held 92.8% to 93.8% where 95% was asked |
| `workbench/*.json` | The same forecast built fourteen ways for the model workbench | The same data | `docs/TRAINING.md`, section 9 |
| `out/sites/<name>/forecast_site_*.json` | The cross-city forecast for a site with no history: pooled over New York, Chicago and San Francisco with the place's size as a feature, plus generated demand | New York TLC records (no licence stated), Chicago TNP (city terms), San Francisco taxi (PDDL) | E13: beats "same hour last week" in 7 of 9 cells and is level with it in New York beyond the hour; bounds too narrow with one donor city |

No model here was trained on the Waymo Open Dataset or any Waymo data.

Fleet totals from the CPUC's public quarterly reports were used to calibrate the simulator, not to train a model.

## Intended use

These are inputs to the depot's day-ahead plan in this simulator, and a baseline for anyone forecasting city-wide ride counts at five-minute to hourly steps. One thing I'd keep in front of you while reading them: the forecasts are of trips served, not trips wanted. Where a city's supply was short, demand was higher than these counts.

## Not intended

**Not as a forecast for any real service.** The series are taxis and ride-hail, calibrated to public fleet totals. They aren't a robotaxi's demand.

**Not as a zero-shot claim for the pretrained model used in E18** (Chronos-2, Apache 2.0, not shipped here). New York taxi data is in its public training corpora. Chicago and San Francisco are the readings that can be called zero-shot, and we've recorded the Chicago run as exploratory.

## What the tests found, and the misses

The record is in `EVALS.md`; the index is `docs/SCOREBOARD.md`. In short: a count target missed every bar when the level rose by about 60% (E7). The ratio target passed 5 of 9 (E7b). Fixes that helped on San Francisco did not carry to Chicago (E17, 0 of 4). A pretrained model had 7.7% error against 9.6% and held 35.7 vehicles in reserve against 40.7 at matched 95% reliability (E18). And at this depot, the plan's rides don't depend on the forecast at all (E16).

## Licences and provenance

Code: see `LICENSE` at the root (source-available; use permitted, no modification or redistribution). Data is as listed in `docs/DATA.md`; no raw records are redistributed. Each model file records the package versions it was built with, and the release notes record the commit.
