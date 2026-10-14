# Ride forecasts: models, experiments, decisions

[Back to the README](../README.md)

*Every forecasting experiment: models, splits, controls and what I decided. For a reader checking the machine learning. The one thing to take: a better forecast buys a tighter safety margin here, and no rides.*


The forecasting and learned-model experiments in this project, what each showed and what I decided. The depot and money tests (E2, E8 to E12, E14, E15, E19 to E23, E25 to E29) are in [EVALS.md](../EVALS.md), linked from [SCOREBOARD.md](SCOREBOARD.md). Figures are read from the records in `data/derived/`; registrations and bars are in EVALS.md; sources are in [DATA.md](DATA.md). "Error" is total absolute error over total rides. "Last week" is the same hour one week earlier.

The forecasting experiments ran in this order: a week-ahead count model that did not beat last week by its bar (E1), a count model for the plan that missed every bar (E7), the ratio target that passed five of nine (E7b), a site with no history (E13, E15), the first-hour study and the workbench, what a forecast is worth to the plan (E16), recipes carried to other cities (E17), the bound separated from the point forecast (E18), and the 26-week backtest that replaced single windows (E24). The reason for each step is in [the path through the tests](../EVALS.md#the-path-through-the-tests). Section 2 gives the conclusion first, and section 3 the single-window tests that led to it.

Two of the depot tests concern forecasts:

- [E10](../EVALS.md#e10-a-guard-for-when-the-forecast-breaks), the guard when a forecast breaks: it caught a stale one within 8 hours in three draws at each of two fleet sizes on one fortnight, and never fired on a sound forecast, there or on any of the four replayed fortnights at the planned fleet's scale (2 of 3 bars).
- [E15](../EVALS.md#e15-is-the-worst-generated-scenario-a-safe-reading-of-a-constrained-depot), generated scenarios for sizing: the real fortnight served 3.1 and 2.9 points more rides than the worst of ten generated ones in Chicago and New York (2 of 2 bars).

## 1. What the forecast is for

The depot's plan needs rides per hour 1, 6 and 24 hours ahead. It plans against an upper bound on those rides, not the expected value, and that bound sets how many vehicles stay out on the road instead of coming in to charge. Forecast error isn't the depot's result. [E16](../EVALS.md#e16-what-is-a-forecast-worth-to-the-plan-and-does-that-depend-on-what-binds) fed the plan perfect foresight, the model, last week's curve and a broken feed: where energy binds all four serve 87.72% of rides, and where vehicles bind perfect foresight serves 99.20% against 99.22% on last week's curve, nothing beyond noise (3 of 4 bars). What the plan buys at this depot is a lower energy price, not rides, and a rule with no forecast buys it cheaper: in [E12](../EVALS.md#e12-does-a-plan-that-knows-the-price-of-energy-earn-its-place), at 500 vehicles, a clock-aware threshold that waits for a free charger pays $0.1530 per kWh and serves 99.03% of rides, against the plan's $0.1675 at 100%, and the quota of the plan's hourly program sits at its ceiling in 95.6% of hours. What a better forecast changes is the reserve. In this document the reserve is the bound's margin above the rides that came, converted to vehicle-equivalents at one vehicle per 60/23 rides an hour; it isn't vehicles a plan held. In E16's four regimes it's 50, 70, 100 and 64 under the model and 64, 89, 127 and 81 under last week's curve.

| | |
|---|---|
| Algorithm | XGBoost, one model per horizon, squared error on the ratio of the target hour's rides to the same hour last week. The forecast is the predicted ratio times last week's figure. |
| Features (21) | Eleven from the ride series, each a backward shift: the hourly rate now, 1 hour, 24 hours and 7 days ago; the target hour's slot on the latest day and the latest week already observed; spread within the last hour; mean, maximum and minimum over 24 hours; this week against last. All but the last are divided by last week's figure. Six calendar fields of the hour being predicted. Temperature and rain now, and as forecast for the hour being predicted. |
| Feature timing | A row is built when its step has ended, and the hour it predicts starts one horizon after that moment: the row's time stamp plus one step plus the horizon. The calendar fields and the target-hour weather describe that hour, not the moment of prediction. The label is the only value taken from after the row. |
| Training rows | San Francisco taxi rides in five-minute steps, 8 December 2022 to 5 February 2024, every third row: 40,789 at one hour ahead. Then 28 days stop the trees (8,041 rows), 28 days size the bound (8,041) and 60 days are held out (17,257). |
| Horizons | The hour starting 1, 6 and 24 hours after the forecast moment. |
| Weighting | Each row by last week's rides in its slot (floor of 5), in training and in the block that stops the trees, so the weighted error of the ratio is the error in rides. |
| Settings and early stopping | Depth 4 or 6 and minimum child weight 1 or 5, chosen by four expanding-window folds inside the training block: depth 6, 4 and 4 with weight 1. Learning rate 0.05, row and column sample 0.8. Up to 3,000 trees, stopped after 60 rounds without gain on the stop block: 336, 798 and 399 trees. |
| Bound | Upper bound from a quantile of the scaled error: the 95% quantile of (rides less forecast) over the square root of the forecast plus one, measured on the calibration block. |
| Hourly form | E17, E18 and E24 use the same recipe on hourly series: 16 features (no month, temperature, minute of day or within-hour spread), every hour trained on, tree settings held at the ones above. |
| Retraining | Weekly. E24 refits every week on the days before it; that is the cadence tested, and no slower one has evidence behind it. |
| Monitoring | Each week: the share of hours the bound held, against 95%, and the week's error against last week's curve on the same hours. |
| Fallback trigger | The guard in E10 compares each hour's rides with the bound given for that hour. When the bound is broken in eight or more of the last 12 hours, the plan drops to the fixed-threshold rule, and returns after at least 24 hours once the bound is broken in a third of recent hours or fewer. A change in what a series reports, as in San Francisco in February 2024, needs a refit on data after the change. |
| Intended use | An input to the depot plan in this simulator, and a baseline for city-wide ride counts at five-minute to hourly steps. |
| Out of scope | The demand of any real service. Rides wanted, as opposed to rides served. A series whose reporting has changed since training. A zero-shot claim for the pretrained model in New York. |
| Records | `data/derived/e7b_scale_free.json`, in the repository. The fitted models (`forecast_ratio_{1,6,24}h.json`, `forecast_ratio_bounds.json`) are not committed: `depot-twin eval e7b` fits and writes them from the public ride records, and a release carries the copies its scores were measured on. |

## 2. The comparison to rely on: 26 weekly origins in three series (E24)

**Decision.** A model trained on a series' own history is kept over last week's curve. Chronos-2, used zero-shot, is ahead of it in every series over 26 weeks: by 0.45, 0.98 and 1.33 points one hour ahead on all weeks, and by 0.45, 0.40 and 0.55 points on the weeks not opened before for this comparison, where the New York ride-hail range includes zero. In New York the mean lead is mostly a few disrupted weeks: the median weekly lead is 0.34 and 0.38 points, and the four largest weeks make up 88% and 75% of the total. The Chicago lead is spread across the weeks: ahead in 23 of 26, with a median of 0.48 points against a mean of 0.45. It's my preferred pretrained candidate; the trees stay the default in the plan until the pretrained forecast has run inside it. The mean of the two adds nothing over the pretrained model alone. For the bound, the fixed quantile stays the plan's bound, and adaptive conformal inference is an option where steady weekly coverage is worth the width. All four bars passed ([E24](../EVALS.md#e24-over-26-weeks-in-three-series-which-forecast-is-better-and-which-bound-holds)).

**Method.** Three series in two cities: Chicago ride-hail, New York ride-hail and New York yellow taxi, hourly, thinned to 500 rides an hour. Each of the last 26 whole weeks is forecast by a model fitted on the days before it: the four weeks before size the bound, the four before those stop the trees, everything earlier trains. Rows are placed by the hour they predict (`lab.cut_week`), so all 168 hours of each week are scored at both horizons. Differences are paired by week, and each range is the 5th to 95th percentile of the mean over 2,000 resamples of whole weeks: a 90% range, one of twelve reported (three series, two horizons, all weeks and fresh weeks), with no correction for there being twelve. Record: `data/derived/e24_backtest.json`.

**Against a stronger naive forecast.** The same hour last week is one count, and at 500 rides an hour one count is noisy: a model beats it partly by averaging. So I built the forecast a planner with no model would use, the mean of the same hour over several past weeks scaled by how the hours just gone compare with their own means, and chose its two settings on the 26 weeks before the first test week (eight weeks and the last 24 hours, in every series). Record: `data/derived/e24_baseline.json`, built by `depot-twin data baseline`.

| Series, horizon | Last week | Average of past weeks | Trained here | Pretrained | Trained here ahead of the average, points (90% range) | Weeks trained here is better, of 26 | Weeks pretrained is better |
|---|---|---|---|---|---|---|---|
| Chicago ride-hail, 1 h | 8.6% | 6.2% | 5.9% | 5.4% | 0.33 (0.02 to 0.67) | 15 | 24 |
| Chicago ride-hail, 24 h | 8.6% | 6.8% | 6.8% | 6.2% | 0.02 (-0.27 to 0.35) | 14 | 21 |
| New York ride-hail, 1 h | 11.8% | 9.0% | 7.0% | 6.0% | 1.98 (0.96 to 3.16) | 23 | 26 |
| New York ride-hail, 24 h | 11.8% | 11.3% | 9.1% | 8.2% | 2.20 (1.36 to 3.19) | 23 | 24 |
| New York yellow taxi, 1 h | 15.1% | 11.1% | 9.1% | 7.7% | 2.06 (1.00 to 3.22) | 22 | 25 |
| New York yellow taxi, 24 h | 15.1% | 13.3% | 11.8% | 10.3% | 1.51 (0.79 to 2.28) | 20 | 24 |

In Chicago the trees are ahead of a sensible no-model forecast by a third of a point one hour ahead and by nothing a day ahead. In New York they keep a lead of 1.5 to 2.2 points: a third to two fifths of what the comparison with last week shows one hour ahead, and up to four fifths a day ahead. The pretrained model is ahead of the average in every cell. So "removes a third of last week's error" is a statement about last week's hour, and the trees' own contribution in Chicago is small.

Mean weekly error, %, and paired differences in points. "Latest same hour known" is the latest same hour of day already known: yesterday's at one hour ahead, the day before's at 24 hours. One hour ahead the model trained here beats last week in all 26 weeks of every series, and the pretrained model beats it in 23, 20 and 21 weeks:

| Series | Ahead | Last week | Latest same hour known | Trained here | Pretrained | Mean of both | Trained less last week | Pretrained less trained | Both less pretrained |
|---|---|---|---|---|---|---|---|---|---|
| Chicago ride-hail | 1 h | 8.62 | 18.01 | 5.85 | 5.40 | 5.40 | -2.77 (-3.41 to -2.19) | -0.45 (-0.58 to -0.32) | 0.00 (-0.07 to 0.06) |
| | 24 h | 8.62 | 29.52 | 6.75 | 6.15 | 6.17 | -1.87 (-2.42 to -1.38) | -0.60 (-0.82 to -0.35) | 0.02 (-0.11 to 0.13) |
| New York ride-hail | 1 h | 11.75 | 17.96 | 7.00 | 6.02 | 6.17 | -4.75 (-6.01 to -3.79) | -0.98 (-1.70 to -0.35) | 0.16 (-0.12 to 0.48) |
| | 24 h | 11.75 | 27.17 | 9.07 | 8.15 | 8.20 | -2.68 (-3.83 to -1.71) | -0.92 (-1.78 to -0.22) | 0.05 (-0.27 to 0.44) |
| New York yellow taxi | 1 h | 15.08 | 20.92 | 9.06 | 7.72 | 7.93 | -6.02 (-7.42 to -4.77) | -1.33 (-2.38 to -0.53) | 0.21 (-0.18 to 0.71) |
| | 24 h | 15.08 | 31.82 | 11.78 | 10.34 | 10.48 | -3.30 (-4.85 to -1.77) | -1.43 (-2.51 to -0.55) | 0.14 (-0.31 to 0.65) |

Eight of each New York series' weeks lie inside the window E17 and E18 scored, where the pretrained model was first compared. The pretrained model less the model trained here, in points, on the weeks outside that window:

| Series | Weeks not opened before | 1 h (range) | 24 h (range) |
|---|---|---|---|
| Chicago ride-hail | 26 of 26 | -0.45 (-0.58 to -0.32) | -0.60 (-0.82 to -0.35) |
| New York ride-hail | 18 of 26 | -0.40 (-1.01 to 0.11) | -0.37 (-0.97 to 0.19) |
| New York yellow taxi | 18 of 26 | -0.55 (-0.94 to -0.20) | -0.94 (-1.58 to -0.37) |

In New York ride-hail the range includes zero at both horizons. In Chicago and New York yellow taxi it doesn't. The range of "both less pretrained" includes zero in every row of the first table.

Three upper bounds on the same forecasts, each an upper bound from a quantile of the scaled error, sized for 95%. Fixed: one quantile from the four weeks before the first test week. Rolling: the quantile taken again each week. Adaptive: adaptive conformal inference, run once through all 26 weeks in order, where the level moves after every hour using only outcomes already known. One hour ahead; width is the bound less the forecast, as a share of the forecast; pinball loss is the quantile loss of the bound at 95%, in rides an hour, lower is better:

| Series | Bound | Trained here: held % | Weeks at 90% or more, of 26 | Mean weekly distance from 95%, points | Width % | Pinball loss | Pretrained: held % | Weeks at 90% or more | Width % | Pinball loss |
|---|---|---|---|---|---|---|---|---|---|---|
| Chicago ride-hail | Fixed | 94.3 | 24 | 2.04 | 11.7 | 4.150 | 94.9 | 24 | 11.2 | 4.033 |
| | Rolling | 95.0 | 24 | 2.21 | 12.3 | 4.160 | 95.0 | 24 | 11.2 | 4.051 |
| | Adaptive | 95.0 | 26 | 1.57 | 12.5 | 4.166 | 95.1 | 25 | 11.3 | 4.015 |
| New York ride-hail | Fixed | 94.8 | 21 | 3.86 | 13.9 | 7.522 | 95.5 | 26 | 12.9 | 5.474 |
| | Rolling | 94.3 | 22 | 3.37 | 15.0 | 7.711 | 95.1 | 24 | 12.4 | 5.524 |
| | Adaptive | 95.0 | 24 | 2.25 | 19.4 | 7.585 | 95.1 | 26 | 12.9 | 5.568 |
| New York yellow taxi | Fixed | 94.4 | 22 | 2.76 | 17.2 | 7.787 | 94.4 | 25 | 15.4 | 7.406 |
| | Rolling | 94.9 | 23 | 2.54 | 18.2 | 7.851 | 94.9 | 25 | 16.0 | 7.403 |
| | Adaptive | 95.1 | 26 | 1.92 | 18.7 | 7.862 | 95.0 | 26 | 17.1 | 7.618 |

On the model trained here the adaptive bound holds its level by construction, 95.0% to 95.1% of hours, and sits 0.47, 1.61 and 0.84 points nearer 95% week by week than the fixed one. It's 7%, 39% and 8% wider, and its pinball loss is higher than the fixed bound's in all three series, so it buys steadier weeks and not a better bound. On the pretrained forecast its pinball loss is lower than the fixed bound's in Chicago only, 4.015 against 4.033. In the hardest week, New York ride-hail from 26 January 2026, the fixed bound held 76.8% of hours and the adaptive one 88.1%.

**Limits.** New York taxi records are in public pretraining corpora, so the two New York series show that an available component helps, not that it transfers unseen. The test weeks, December 2025 to August 2026, most likely postdate the model's weights, so what its corpus can hold is earlier years of the same cities, which it may well hold for New York taxi; I have no evidence either way for Chicago ride-hail. Chicago is the firmer reading for a different reason, its lead being steady across weeks: 5.40% against 5.85%. Those weeks were not opened before for the pretrained comparison. The trees had been scored against last week on 18 of them in earlier tests (E13, E7 and E1), nine as test weeks and nine as development. The model trained here also has less to learn from in Chicago, 12 to 18 months of history against three years in New York, and all three series are one thinning draw. At 24 hours the adaptive bound costs more: on the model trained here it holds 95.0% to 95.1% of hours, at 90% or more in 25, 23 and 23 weeks, with a width of 17.3%, 44.7% and 64.9% of the forecast against 13.2%, 17.8% and 23.9% for the fixed bound, and a pinball loss of 5.991, 15.444 and 20.559 against 5.367, 10.422 and 10.252.

## 3. Single-window tests and what each taught

### E7. Counts as the target: missed, and why

**Decision.** Don't forecast counts on a series whose level can move. Belief: a Poisson count model would beat the simple rules. Result on 60 held-out San Francisco days: 0 of 9 bars ([E7](../EVALS.md#e7-ride-forecasts-for-the-controller)).

| Ahead | Count model | Best simple rule | Bound held (asked 95%) | Busiest tenth of hours |
|---|---|---|---|---|
| 1 h | 15.4% | 15.4% (yesterday) | 91.5% | 24.0% low |
| 6 h | 24.7% | 15.4% (yesterday) | 90.1% | 40.8% low |
| 24 h | 25.3% | 14.9% (last week) | 89.8% | 44.6% low |

Why: a reporting change in mid-February 2024 raised recorded rides by about 45%, with the number of cabs reporting flat ([DATA.md](DATA.md)). Training ends on 5 February 2024, so the model was fitted below the level of the held-out days, and trees don't predict beyond the range they have seen. Where the level is stable the same pipeline works: on Chicago it has 4.00%, 4.64% and 4.95% error against 6.44%, 6.43% and 6.34% for last week, with bounds holding 95.7% to 97.1%. Record: `data/derived/e7_forecasts.json`.

### E7b. The ratio to last week as the target: adopted

**Decision.** The ratio target is the reference model (section 1). Same data, blocks, search and bars as E7: 5 of 9 bars ([E7b](../EVALS.md#e7b-the-same-forecasts-on-a-scale-free-target)).

| Ahead | Ratio model | Last week | Error removed against last week | Bound held | Busiest tenth of hours |
|---|---|---|---|---|---|
| 1 h | 10.7% | 14.9% | 28.2% | 94.4% | 6.0% low |
| 6 h | 12.4% | 14.9% | 16.8% | 92.7% | 11.6% low |
| 24 h | 11.8% | 14.9% | 20.9% | 94.6% | 7.3% low |

**Limit.** The bound falls out of its bar at six hours, and the peak bar is missed at every horizon: over the busiest tenth of hours the forecast runs low, which is why the plan reads the bound and not the mean. The held-out days are the ones E7 was scored on, so this confirms a diagnosis; the comparison to rely on is section 2. Record: `data/derived/e7b_scale_free.json`.

### E13. A site with no history

**Decision.** A new site runs on last week's curve until it has a few weeks of its own rides, and a guard on the bound is mandatory there. Generated demand is used to size a depot, not to improve a forecast. 1 of 4 bars ([E13](../EVALS.md#e13-can-a-forecast-be-built-for-a-place-with-no-ride-history)).

Each city is held out in turn and forecast by one pooled model trained on the other cities' series (7, 28 and 23 of them, counting the copies of large ones thinned to 300 and 2,000 rides an hour; no city identifier; told the size of the place), with and without generated demand for the target. Cells are percentages at 1 h / 6 h / 24 h on the city's last 60 days:

| Held-out city | Last week | Own history | Donors only | Donors plus generated | Bound held |
|---|---|---|---|---|---|
| New York | 8.21 / 8.23 / 8.09 | 4.07 / 5.27 / 5.71 | 7.69 / 7.90 / 8.09 | 7.63 / 7.89 / 8.09 | 97.2 / 96.2 / 97.3 |
| Chicago | 6.44 / 6.43 / 6.34 | 4.00 / 4.71 / 5.12 | 5.16 / 5.68 / 5.88 | 5.10 / 5.89 / 5.88 | 99.2 / 99.0 / 98.9 |
| San Francisco | 14.90 / 14.90 / 14.94 | 10.10 / 12.06 / 12.95 | 11.26 / 13.16 / 13.63 | 11.26 / 13.05 / 13.86 | 91.2 / 88.2 / 87.2 |

- The forecast beats last week in 8 of 9 cells and is within 1.25 times the own-history model in 4; history is worth 0.8 to 3.6 points. In New York at 24 hours the donors transfer so poorly that the measured trust is zero and the forecast is last week's figure.
- Generated demand lowers forecast error in four cells, by up to 0.11 points, leaves three level and raises two, by 0.21 and 0.23 points. For sizing it holds: at 1,000 vehicles the depot serves 88.0% of rides on generated demand against 88.2% on real days (ten scenarios, 86.2% to 90.7%), and 100.0% both ways at 500.
- Bounds are too narrow for San Francisco, where the only donor city with earlier data is New York, and run wide for Chicago, over 99% in two cells.
- **Limit.** Three cities, all dense. The level of demand at a new site is an input, not a prediction. Record: `data/derived/e13_new_site.json`.

### E17. Modelling recipes over six thinning draws

**Decision.** The reference stands. Belief: three changes that each helped on San Francisco (a four-week denominator, rolling folds for the tree count, bagging) would carry to other cities. Result on Chicago and New York ride-hail at 500 rides an hour, 5 January to 1 March 2026: 0 of 4 bars ([E17](../EVALS.md#e17-do-the-changes-to-the-model-improve-the-forecasts-bound-and-does-that-hold-on-days-held-back-for-it)). One hour ahead, mean of six draws; the margin is the reserve of section 1, scaled to a fleet of 500 at 25 rides a vehicle a day:

| Recipe | Chicago: error | Held | Margin, vehicle-equivalents | Draws lower, of 6 | New York: error | Held | Margin, vehicle-equivalents | Draws lower |
|---|---|---|---|---|---|---|---|---|
| Reference (last week 12.66%, 16.16%) | 7.96% | 95.7% | 36.9 | | 8.85% | 92.4% | 31.4 | |
| Ratio to a four-week mean of the slot | 8.23% | 93.6% | 32.2 | 0 | 8.21% | 92.4% | 28.8 | 6 |
| Trees chosen on four rolling folds | 8.02% | 95.7% | 36.6 | 0 | 8.88% | 92.2% | 31.2 | 2 |
| Counts over the trailing four-week level | 7.95% | 95.1% | 34.8 | 3 | 8.47% | 92.6% | 30.0 | 6 |
| Quantile model for the bound | 7.96% | 94.6% | 39.5 | | 8.85% | 91.1% | 33.7 | |
| Five bagged models | 7.90% | 95.5% | 35.6 | 6 | 8.80% | 92.2% | 31.1 | 4 |
| Four-week mean, rolling folds and bagging together | 8.23% | 93.3% | 31.8 | 1 | 8.30% | 92.2% | 29.0 | 6 |

The combined recipe helps in New York (paired-day difference -0.81 points, 90% interval -1.90 to +0.16) and not in Chicago (+0.19, -0.43 to +1.21; at 6 and 24 hours 9.55% and 10.19% against 8.27% and 8.83%). Its smaller margin in Chicago is bought with 2.4 points of coverage. One hour ahead, bagging is the only change whose interval excludes zero, in both cities, and it's small: 0.07 points in Chicago and 0.13 in New York. **Limit.** One eight-week window per city; New York holds under 95% for every recipe. Record: `data/derived/e17_fixes.json`.

### E18. The bound's margin at matched coverage

**Decision.** Keep the bound from section 1 and judge forecasts by the margin their bound asks for at the same achieved coverage. Belief: a bound with a relative part and a counting part would ask for a smaller margin. It asked for a larger one. 2 of 3 bars ([E18](../EVALS.md#e18-how-cheaply-can-the-fleet-buy-a-required-level-of-demand-certainty)). Each bound is sized at 29 levels from 85% to 99% on the calibration block and read on the test days; arms are compared at 95% achieved. New York yellow taxi, one hour ahead, mean of three draws:

| Arm | Error | Held when sized for 95% | Margin at 95% achieved, vehicle-equivalents |
|---|---|---|---|
| Reference trees, bound from section 1 | 10.46% | 94.3% | 41.7 |
| Reference trees, relative-plus-counting bound | 10.46% | 95.6% | 54.8 |
| Chronos-2, relative-plus-counting bound | 7.73% | 96.3% | 35.9 |
| Mean of the two forecasts, same bound | 8.54% | 96.0% | 37.9 |
| Last week, same bound | 17.64% | 92.9% | 141.1 |

The margin fell only where the point forecast improved. On the same window Chronos-2 against the reference gives 6.46% and 27.1 against 7.98% and 34.0 in Chicago, and 6.11% and 25.8 against 8.96% and 40.2 on New York ride-hail; both are exploratory, since E17 had opened that window. **Limit.** One series confirms; the Chicago reading is the one least likely to overlap the pretraining corpora. Record: `data/derived/e18_reserve.json`.

### The hour under way (first-hour study)

**Decision.** A fourth model for the hour that has already started is kept as an option; the registered tests run without it. Over four replay windows (56 days) it has 9.3% error with the bound holding 95.6%, against 13.6% and 91.3% for the figure interpolated from the one-hour model. Rides served are identical either way in every arm (100.0% at 500 vehicles and 88.7% at 1,000 under the plain plan); at 500 vehicles the price-aware plan pays $0.1674 per kWh against $0.1675. No bars: every window had been used before ([registration](../EVALS.md#first-hour-forecast-study)). Record: `data/derived/first_hour.json`.

### Workbench ablations: features, history, trees

**Decision.** No variant is adopted on this evidence. The variants were scored on the 60 San Francisco days the reference is reported on, so choosing among them there would be tuning on the test set; E17 carried the ideas to other cities. One change per variant, tree settings held at the reference's. Records: `data/derived/workbench/*.json`.

| Variant | Error 1 h / 6 h / 24 h | Bound held, 1 h |
|---|---|---|
| Reference (336 trees) | 10.7% / 12.4% / 11.8% | 94.4% |
| 10, 50, 200 trees | 1 h: 12.1%, 9.8%, 10.2% | 92.6%, 95.5%, 95.1% |
| 3,000 trees, no early stopping | 12.4% / 14.9% / 14.4% | 91.2% |
| Lags only; lags and calendar (no weather) | 1 h: 11.3%; 10.6% | 93.8%; 94.7% |
| 1, 3, 6 months of history | 1 h: 13.2%, 10.4%, 10.3% | 97.8%, 95.2%, 95.5% |
| Counts as the target | 15.4% / 24.9% / 26.1% | 91.5% |
| No local history (the E13 model) | 11.4% / 13.1% / 13.8% | 91.3% |
| No model: last week | 14.9% / 14.9% / 14.9% | 92.0% |
| Chronos-2, zero-shot | 8.4% / 9.3% / 9.8% | 96.9% |

What it taught: the 50-tree variant reads lower than the reference on these 60 days, 9.8% against 10.7% one hour ahead. That's one window, and picking the tree count on it would be tuning on the test set, so the reference keeps the count its stop block chose. Past 400 trees, training error keeps falling (8.2% to 3.2% at 3,000) while error on the stop block rises from 15.4% to 15.7%. One hour ahead, three to six months of history do as well as all fourteen across this break. One month is behind them at 13.2%: still ahead of last week one hour ahead, and behind it at six and 24 hours (16.0% and 15.6% against 14.9%). Dropping weather moves error by under 0.1 points at every horizon.

## 4. Learned models beside the forecast

| Test and record in `data/derived/` | What was tried | Result against its bars | What was kept |
|---|---|---|---|
| [E1](../EVALS.md#e1-week-ahead-demand-forecast) demand a week ahead: `e1_demand.json`, `e1_walk_forward.json` | XGBoost on counts, fixed 400 trees, calendar and one-to-four-week lags; Chicago, 14,592 hours, last 91 days held out. Bar: remove 15% of last week's error. | 6.26% against 6.29%: 0.5% removed, 0 of 1. On four four-week windows trained only on what came before: 2.3%, 26.9%, 8.2% and 15.5% removed. Early stopping was worse in one of the four. | The weekly demand shape. A week ahead, the depot plans on last week. |
| [E3](../EVALS.md#e3-a-fast-stand-in-for-the-simulator) stand-in for the simulator: `e3_surrogate.json` | XGBoost per output on 1,600 simulated depot designs, split by design, fleets of 900 to 1,150 withheld (143). | Error on share of rides served, points: train 0.22, validation 0.44, test 0.68, withheld band 0.77; spreadsheet rule 6.21; two runs of one design 0.34. 4 of 6: test is 1.57 times validation (bar 1.3), and the designs it picked were predicted to earn 11.2% to 14.6% more than they did in simulation. | The split by design and the withheld band. |
| [E4](../EVALS.md#e4-a-planner-that-can-be-trusted-with-the-search) planner: `e4_planner.json` | 2,000 designs on week-long runs, logit and log targets, a safety margin from the 90th percentile of over-prediction, 300 designs made after the models were frozen. | Validation 1.37, test 1.42, withheld band 1.43, prospective 1.34 (0.68 near the service level). 5 of 7: the margin is 1.24 points, more than the one point of room above 99% service, so the planner offered no design in any case. | The models shortlist; the simulator confirms every design. |
| [E5](../EVALS.md#e5-teaching-the-planner-where-it-searches) active learning: `e5_active.json` | Two rounds of simulating what the planner picks and retraining on it. | The planner picked nothing, so both rounds added 0 designs and the model stayed at 1,271 training designs. 1 of 3. | The simulator stays in the loop for each decision. |
| [E6](../EVALS.md#e6-identifying-the-twin-from-telemetry) identification: `e6_identify.json` | One two-parameter Kalman filter per vehicle on telemetry; 500 vehicles, 7 days, median 1,607 readings. | Median error after 7 days: driving energy 2.5%, always-on load 3.1%, against 5.4% and 5.2% for the vehicle type's figure; 91.8% of vehicles within 8% on both. 3 of 4: always-on load fell short of halving. | The plan reads identified energy figures, not type figures. |

## 5. Leakage and fairness controls

- **Chronological blocks.** Train, then 28 days to stop, 28 to size the bound, then the test days. Rows whose label crosses a block edge are dropped. No random split anywhere. In E24 an hour's outcome moves the adaptive level only once that hour has ended. In E13 the last four weeks of each donor series stop the trees, and the 25 hours before them are left out (`transfer.split`), so no training label falls among the stopping rows at any horizon.
- **Feature timing.** Every feature from the ride series is a backward shift. The calendar fields and the target-hour weather describe the hour being predicted, which starts one step plus the horizon after the row's time stamp; both are known in advance, the weather as a forecast. A unit test rewrites every value after a moment and checks that no feature at that moment moves, and another checks that the calendar is the target hour's (`tests/test_features.py`).
- **The split file.** `data/splits.json` gives each window of each series one purpose: development, test or, for E24's run of weeks, backtest, which names the weeks other tests had scored. `tests/test_contracts.py` holds the dates in code to it.
- **Weekly shape from training days only.** The demand shape the simulator runs on leaves out the last 116 days of the San Francisco series, the stop, calibration and held-out blocks.
- **Thinning draws.** New York and Chicago are brought to a depot's 500 rides an hour by keeping each ride with one fixed chance. `newsite.thinned` takes that chance from the whole series' mean, a scale constant under a scale-free target. One draw can decide a close comparison, so E17 reports the mean of six draws and E18 of three, and counts the draws that agree. E24 uses one draw and takes its spread from 26 weeks.
- **Generated rows.** In E13 the generated demand used in each held-out-donor fold is generated again from the donors that fold keeps. The code refuses generated rows for calibration and scoring. It refuses them for stopping as well, with one stated exception: the generated-only arm of E13 has nothing real, so it stops its trees on the last four weeks of its own generated rows.
- **Matched coverage and paired differences.** Bounds are compared at the same achieved coverage, read off each arm's frontier, never at the same nominal level. E24 pairs by week and resamples whole weeks; E17 pairs by day and resamples week-long blocks. Hours within a week are not treated as independent. Neighbouring weeks are not independent either, so E24's ranges were taken again with the weeks resampled in blocks of four consecutive weeks (`data/derived/e24_blocks.json`, built by `depot-twin data blocks`): the range of a paired difference is 0.98 times as wide at the median and 1.23 times at the widest, and every difference that was clear of zero week by week is clear of zero in blocks. Chicago one hour ahead, pretrained less trained here: 0.33 to 0.56 points in blocks against 0.32 to 0.58.
- **Clock-change hours.** `contracts.steady_clock` runs wherever a series is loaded: the San Francisco five-minute counts, the donor panel behind E13, E17, E18 and E24, E1's hourly frame and E7's Chicago table. It fills the March hour that does not exist with the mean of the hours either side, and halves the November hour that New York and Chicago count twice. San Francisco's feed holds a single November hour, which is left as it is. No model is trained or scored on either artefact.
- **What Chronos-2 saw.** The last 2,048 hours of the series up to the forecast moment, and nothing else: no covariates, no fitting here. Its median is the forecast. The model commit (`29ec3766`), package version (`chronos-forecasting` 2.3.2) and context length are stored in the E18 and E24 records. The loader takes the hub's current revision, so a later run should check the commit it prints against the one recorded before comparing figures.

## 6. What this evidence does not support

- **Any San Francisco figure as a clean score.** Every single-window result on that series (E7, E7b, the first-hour study, the workbench, one row of E13) measures a model through one city's reporting break, on held-out days that several tests share.
- **A forecast of East Oakland demand.** The site has no ride history. Its demand is simulated from other cities' taxi and ride-hail records at a level I set, and those records count rides served, not rides wanted.
- **Sensitivity to weather or events.** Events are not modelled. Weather is an archive of forecasts that stitches together the first hours of successive runs, so the value for an hour 24 hours ahead is closer to what happened than a forecast issued a day earlier would be. That touches the trees at 6 and 24 hours and not the one-hour figures the documents quote. It moved error by under a point at every horizon, and Chronos-2 saw none, so where it helps it helps the reference and not the candidate.
- **A zero-shot claim in New York.** Pretraining overlap with earlier years cannot be ruled out there, and the lead rests on a few disrupted weeks. Chicago is the reading to quote: a lead of 0.45 points at one hour. On the 18 New York weeks not opened before, the lead is 0.40 points in ride-hail, with a range that includes zero, and 0.55 in yellow taxi.
- **The donor model's validation error.** Its tree settings are chosen on the same rows that stop its trees (the grid search in `transfer.fit_pooled`), so validation there is optimistic. The E13 scores do not rest on it: the test is a held-out city, which that choice does not touch.
- **Coverage in a given hour.** The bounds are marginal, not conditional: 95% is an average over hours. Weeks fall well under it, and the mean forecast runs low in the busiest hours.
- **More than 26 weeks.** The backtest covers half a year, three series in two cities and one thinning draw. Its ranges describe week-to-week variation, not other seasons or other cities.

## 7. Related work

- "Forecasting at Uber" describes boosted trees beside seasonal baselines with prediction intervals always reported. That is the form used here: trees, last week in every table, a bound with every forecast. Pooled tree models won the M5 competition; E13 pools every donor series in one model and tells it the size of the place.
- Ansari et al., Chronos (2024), and the Chronos-2 model card (2025, Apache 2.0): the pretrained arm of E18 and E24, used zero-shot and univariate.
- Gibbs and Candes (2021), adaptive conformal inference: the adaptive bound in E24. Tibshirani et al. (2019) treat intervals under shift. Neither gives a guarantee before a site's first real rides, so E13 sizes bounds on donor cities held out in turn.
- RegionTrans (Wang et al. 2019) and MetaST (Yao et al. 2019) transfer between cities but need some data from the target. A depot not yet open has none, so E13 holds each city out entirely. Yan, Liu and Zhao (2020) predict the level of ride-hail trips from demographics and land use. Here the level at a new site stays an input.
