# How each model was trained

This is the training record for the depot twin, one section per model. Each section says what the model is for, the data it was trained on, the label, the features, the split, the settings, how overfitting was guarded against, the result, and how to rebuild it. It's written for the fleet operations team and for the engineers who clone the repository.

Results are quoted from [EVALS.md](../EVALS.md), where each test's bars were fixed before its run. The reasoning behind the choices is in [BUILD_LOG.md](BUILD_LOG.md). Not everything here is a trained model: the depot and fleet simulator is built from physics and public figures, the hourly plan is a linear program solved fresh each hour, and the planned controller is an optimization, not a model.

## 1. Demand forecast (week ahead)

| | |
|---|---|
| Purpose | Hourly ride demand a week out, for depot planning. Supplies the weekly demand shape the simulation runs on. |
| Model | XGBoost, Poisson objective |
| Data | City of Chicago ride-hail trips counted per hour, 1 January 2025 to 31 August 2026: 14,592 hours |
| Label | Trips in the hour being predicted |
| Features (11) | Hour, weekday, month, holiday, day before a holiday; trips in the same hour one, two, three and four weeks earlier; the mean of those four; the mean of all hours over the four weeks ending a week ago |
| Leakage rule | Nothing newer than one week is used |
| Split | Chronological. The last 91 days (2,184 hours) are held out; training stops on 1 June 2026. Never a random split. |
| Settings | 400 trees, learning rate 0.05, depth 6, column sample 0.9. Fixed before the evaluation and not tuned on the held-out days. |
| Baseline | Trips in the same hour last week |
| Metric | Total absolute error over total trips |

**Result.** The forecast scored 6.24% against 6.29% for the baseline, which removes 0.7% of the error. The bar was 15%, so this is a miss.

**Walk-forward check.** We ran four earlier four-week windows, each trained only on what came before. The forecast removed 4%, 26%, 10% and 15% of the baseline's error.

**Tried and declined.** We tried early stopping on the preceding four weeks. It was worse in three of the four windows.

**Limits.** The data is from the wrong city. It counts trips served, not trips requested. There is no weather and there are no events.

**Rebuild.** Run `depot-twin eval e1` and `depot-twin eval e1-walk`.

## 2. Recall policy (reinforcement learning)

| | |
|---|---|
| Purpose | Each hour, set the battery level under which vehicles are called in and the level at which they are released |
| Model | PPO with a small fully connected network (Stable-Baselines3 defaults) |
| Environment | The fleet and depot simulator. One step is one hour; one episode is one week. |
| Training scenario | A quarter-scale copy of the 1,000-vehicle depot: 250 vehicles, 687.5 kW, 33 chargers. Same power and chargers per vehicle. |
| Observation (12) | Hour of day as sine and cosine; weekday; share of fleet on the road; mean charge on the road; share under 30% and under 60%; share of chargers in use; queue over chargers; demand over capacity for the next hour, the next 1 to 4 hours and the next 4 to 12 |
| Action (15) | A call-in level from 15%, 25%, 35%, 50%, 65% and a release level from 60%, 75%, 90% |
| Reward | Rides lost in the hour, as a negative share of an average hour's demand |
| Settings | 120,000 steps across 8 parallel environments; 168 steps per environment per update; batch 336; discount 0.995; learning rate 0.0003; entropy bonus 0.01 |
| Seeds | Training episodes use seeds from 1,000 up. Development used 1 and 2. Evaluation uses 101 to 110. |

**Why everything it sees is a ratio.** Everything in the observation is a ratio so that a policy trained on 250 vehicles can be run on 1,000. Whether that works is a registered test, not an assumption.

**Speed-up used in training only.** Training uses a three-minute power step instead of a one-minute step.

**Result.** At 1,000 vehicles, four times the size it trained on, the policy served 76.4% of rides. A fixed threshold served 74.7% and the best hand-written rule served 76.7%. At 500 vehicles, a regime it never saw, it was the weakest rule at 96.5%.

**Limits.** It sits 0.3 points behind a simple rule. It carries no explicit constraints. We keep it as a baseline for the controller to beat.

**Rebuild.** Run `python -m depot_twin.first_version.train --steps 120000` (the first version's trainer, kept apart from the product's command line), then `depot-twin eval e2`.

## 3. First stand-in for the simulator (evaluation E3)

| | |
|---|---|
| Purpose | Predict what the simulator would say about a depot design, fast enough to search thousands |
| Model | XGBoost, one model per output |
| Data | 1,600 designs drawn uniformly at random; each simulated for three days and measured on the last two. The first 200 simulated again under a second seed. |
| Inputs (15) | Fleet size; grid limit; fast chargers per 100 vehicles; fast charger power; slow chargers per 100; battery size; rides per vehicle per day; demand peakiness; energy per mile; staff per 100; call-in level; release level; and three ratios computed from them (grid power per vehicle, charger power per vehicle, deliverable energy over wanted energy) |
| Outputs (4) | Share of rides served; energy per vehicle per day; peak draw over the limit; share of energy bought in the peak tariff period |
| Split | By design, never by row. Fleets of 900 to 1,150 withheld entirely (143 designs). The rest 70/15/15: 1,019 train, 219 validation, 219 test. |
| Tuning | Depth (3, 4, 6), minimum child weight (1, 5), L2 penalty (1, 5): 12 combinations, chosen by 5-fold cross-validation grouped by design, inside the training set |
| Fixed settings | Learning rate 0.05, row sample 0.8, column sample 0.8 |
| Trees | Early stopping on validation, patience 60, up to 3,000 |
| Constraints | More grid power or battery may never predict fewer rides served. Charger count is left free, because under the headroom rule more chargers can pull more vehicles off the road at once. |

**Chosen for rides served.** The chosen settings were depth 6, minimum child weight 5 and penalty 1, at 111 trees.

**Result (error on share of rides served).** Training error was 0.19 points, validation 0.43, test 0.62 and the withheld band 0.78. The spreadsheet formula was 6.22. Two runs of the same design differed by 0.29.

**Two bars missed.** Test error was 1.45 times validation error, against a bar of 1.3. The picked designs were predicted 13% to 15% above their simulated money, because the three-day runs measured only a Tuesday and a Wednesday.

**Rebuild.** Run `depot-twin eval e3`.

## 4. The planner's models (evaluations E4 and E5)

The stand-in was rebuilt so that it can be searched.

| | |
|---|---|
| Data | 1,000 space-filling designs (Sobol) and 1,000 placed where the site delivers 0.8 to 1.3 times the energy the fleet wants and the chargers 0.9 to 2.5 times. Eight-day runs, the last seven measured, so every weekday counts once. The first 100 of each simulated again under a second seed. |
| Inputs (17) | The 15 above plus chargers per vehicle and battery per vehicle |
| Outputs (3) | Share of rides served; energy per vehicle per day; share of energy in the peak tariff period. Peak draw is not predicted; the capacity charge is costed at the full connection. |
| Target scale | Logit for the two shares, log for energy, so no prediction can leave its physical range |
| Split | By design. Withheld band 184; train 1,271; validation 272; test 273. |
| Prospective set | 300 new designs generated and simulated only after the models were frozen |
| Tuning, settings, constraints | As in section 3, with battery per vehicle added to the constrained inputs |
| Safety margin | The 90th percentile of over-prediction among validation designs the model predicts will reach 99% service. The planner accepts a design only if prediction less margin still reaches 99%. |

**Chosen for rides served.** The chosen settings were depth 6, minimum child weight 5 and penalty 1, at 322 trees.

**Result (E4).** Training error was 0.27 points, validation 1.28, test 1.40, the withheld band 1.44 and the prospective set 1.34, which is 1.05 times validation. Two runs of the same design differed by 0.23. The margin was 1.35 points.

**What the margin did.** A design needs a predicted 100.35% to be accepted, so the planner offered none in any of the three cases. The stand-in is accurate on average and not near the service level, where the room above 99% is one point.

**Retraining on searched designs (E5).** Two rounds: in each the planner ranks 5,000 candidates in 30 random situations, its top 20 per situation are simulated, and those runs join the training set. With nothing picked, both rounds held no designs, the model stayed at 1,271 training designs and 322 trees, and the margin stayed at 1.35 points.

**Standing rule.** These models shortlist. The simulator confirms every design before it is believed.

**Rebuild.** Run `depot-twin eval e4`, then `depot-twin eval e5`.

## 5. The twin's own parameters (identified, not trained; evaluation E6)

| | |
|---|---|
| Purpose | Each vehicle's driving energy (kWh per mile) and always-on load (kW); each type's charge curve |
| Method | Energy: one two-parameter Kalman filter per vehicle on energy = a x miles + b x hours. Charge curve: the median power delivered in each 5% band of charge. |
| Data | Telemetry the vehicle already produces. Every quarter hour: miles, elapsed time, and the change in the battery gauge, read with noise of 0.1% of the pack. Every minute while charging: power delivered. |
| Starting point | The type's published or estimated figure, with 15% uncertainty |
| What makes it testable | Simulated vehicles are given true values, moved 8% at random from their type, that the estimator never sees |
| Readings discarded | For charge curves, any reading where the site could not give the vehicle all it could take |

Nothing here is trained. Each vehicle tells us what it is by driving, and the filter listens.

**Result.** After seven days, with a median of 1,627 readings a vehicle, driving energy was off by a median of 2.2% and always-on load by 3.0%, against 5.4% and 5.2% for the type's figure. After one day the figures were 4.2% and 4.8%. Charge curves came within 0.04 kW, with the caveat that power readings are noiseless in the simulator.

**Rebuild.** Run `depot-twin eval e6`.

## 6. Ride forecasts for the controller (evaluations E7 and E7b)

| | |
|---|---|
| Purpose | Rides in the hour starting 1, 6 and 24 hours ahead, with an upper bound the controller plans against |
| Model | XGBoost, one per horizon |
| Data | San Francisco taxi trips, 1 December 2022 to 31 May 2024, in five-minute steps: 2.97 million rides after cleaning. Hourly weather from a public archive of forecasts. |
| Cleaning | Drop paratransit, trips under 300 metres or under a minute, and exact repeats of a record |
| Label | E7: rides in the target hour. E7b: that count divided by rides in the same hour last week. |
| Features (21) | Hourly rate now, 1 hour, 24 hours and 7 days ago; the target's own slot on the latest earlier day and week; spread within the last hour; mean, maximum and minimum over the last day; rate now against last week. Calendar of the target hour. Temperature and rain now and forecast for the target hour. In E7b the series features are divided by last week's value. |
| Leakage guard | Every series feature is a backward shift; a unit test rewrites the future and checks no feature moves |
| Split | In time order: train (40,789 rows, every third five-minute row, since neighbouring hourly sums overlap); 28 days for early stopping; 28 days for calibrating bounds; 60 days held out (17,257 rows). Rows whose label crosses a boundary are dropped. |
| Tuning | Depth (4, 6) and minimum child weight (1, 5), by expanding-window cross-validation in the training block with 300 trees |
| Fixed settings | Learning rate 0.05, row and column sample 0.8. Poisson objective for counts; squared error weighted by last week's level for ratios. |
| Trees | Early stopping, patience 60, up to 3,000 |
| Bounds | A residual quantile sized on the calibration block, with errors scaled by the square root of the prediction |
| Baselines | Last hour; same time on the latest earlier day; same time last week |

We ran the target two ways, and the second way is the one that survives.

**Result, counts as target (E7).** Predicting the count missed everything. Error was 15.5%, 24.3% and 24.3% at 1, 6 and 24 hours, against about 15% for the best baseline, and the model ran 24% to 43% low at the peak. The data's level rose by about 60% between training and the held-out days, and a tree model extrapolates poorly beyond the levels it has seen.

**Result, ratio as target (E7b).** Error was 11.4%, 11.9% and 12.3%, removing 26%, 23% and 17% of the baseline's error. The upper bound held 92.8%, 93.3% and 93.8% of the time, and the model ran 8% to 11% low at the peak. The search chose depth 6 at one hour and depth 4 beyond, with 725, 587 and 719 trees.

**Second city.** We ran the count pipeline on Chicago's hourly series, trained on every hour. It removed 36%, 28% and 22% of the baseline's error at one, six and twenty-four hours. Bounds held 95% to 97% of the time.

**Limits.** The data is taxis, not ride-hail, and it is trips served. It ends in May 2024. The weather archive is better than a real day-ahead forecast. E7b was scored on days E7 had already been scored on.

**Rebuild.** Run `depot-twin eval e7`, then `depot-twin eval e7b`.

**The hour under way (first-hour study).** The three horizons leave out the hour that starts now. The controller fills it by correcting last week's figure with the one-hour model's ratio, which gives 14.2% error over the four replay windows with the bound holding 89.8% of the time. A fourth model, trained for that hour on the same features, blocks and search, gave 9.2% error with the bound holding 96.0% of the time. It changed nothing in rides served. It is available to the replay builder and is not used by the registered tests.

## 7. The heartbeat controller (not trained; evaluation E8)

Nothing in the controller is fitted. It is listed here because it is what the trained and identified pieces feed.

| | |
|---|---|
| Tick | Five minutes |
| Hourly plan | A linear program over the next 24 hours: visits per hour that maximize rides served, given the vehicles each visit takes off the road, the energy it returns, and the site's power. It values energy in hand slightly and pays for dipping under a 30% reserve. |
| Planned against | The upper 95% bound of the ride forecast (section 6), not its expected value |
| Energy figures | The fleet means identified from telemetry (section 5), not the true values |
| Session | One slot of energy: 60 minutes at full charger rate, about 56 kWh, to 85% at most. A vehicle is called only with room for 90% of a slot. |
| Concurrency | No more vehicles plugged in than the site feeds at full rate; fed in order of plugging in |
| Phases | At most a twelfth of the chargers turn over per tick |
| Ledger | Each hour: planned vehicles on the road, less the 95th percentile of the plan's own shortfall over the previous seven days |
| Settings chosen on | 18 to 31 March 2024, two seeds. Beat length (30, 45, 60, 75 minutes), top charge and minimum fill were compared there. |
| Evaluated on | 15 to 28 April 2024, five other seeds, once |

**Result.** Rides served were 100.0% at 500 vehicles and 87.6% at 1,000. The headroom rule held 100.0% and 82.4%. Grid draw variation at 500 was 0.22 against 0.56. The ledger was kept in 98.6% and 93.3% of hours against a promised 95%. The tick took at most 0.4 ms at the median.

**Repeated on later days (E9, from 13 May 2024).** Rides served were 100.0% and 88.6% against 100.0% and 84.3%, and a ledger that starts from what is on the road was kept in 98.0% and 96.5% of hours.

**What the parts are worth (E11).** We crossed three ways of calling vehicles in with two ways of sharing power. The gain in rides comes from feeding vehicles in order at full rate. A fixed threshold with that power rule matches the full controller, at 88.8% against 88.6% at 1,000 vehicles and 100.0% at 500. The plan, and so the forecasts and identified energy figures that feed it, did not add rides. Under a forecast cut to a third of the truth the controller served the same (E10).

**So, for the pieces in sections 5 and 6.** They work as built. They do not move rides. Where the plan they feed does matter is cost.

**Cost (E12).** Told the tariff, the controller steers charging around the 4 pm to 9 pm price peak: before it, vehicles that would otherwise run down during it are called in, and during it only vehicles under 15% are called. At 500 vehicles that is 12.2% cheaper per kWh with no loss of rides, and $2.75 more per vehicle per day than a plain threshold. A threshold that only knows the clock lost 5.1 points of rides attempting the same. The settings, four hours before the peak and 15% during it, were chosen on the development days.

**Rebuild.** Run `depot-twin eval e7b` for the forecasts it reads, then `depot-twin eval e8`, `e9`, `e10`, `e11`, `e12`.

## 8. A forecast for a place with no history (evaluation E13)

**What it predicts.** This section predicts the same thing as section 6: rides in the hour starting 1, 6 or 24 hours ahead, for a place whose own rides the model has never seen.

**Data.** We use 15 hourly series from three cities (`depot_twin/data/donors.py`): New York ride-hail and yellow taxi by area, January 2023 to June 2026; Chicago ride-hail, January 2025 to August 2026; San Francisco taxi by area, December 2022 to May 2024. Each large series is used at its own size, and again thinned to 300 and to 2,000 rides an hour, by keeping each ride with a fixed chance.

**Generated series.** For the target, there are six series of 52 weeks from the generator (`depot_twin/synth.py`), on the target's own calendar and weather, built only from other cities' donors of the same kind of place.

**Target and features.** The target is the ratio to the same hour last week. The features are the series against its own past (the level now, an hour, a day and a week ago; the target's slot yesterday and last week; mean, maximum and minimum over 24 hours; this week against last), hour, weekday, weekend, holiday, rain now and forecast, and the log of last week's level. Left out on purpose: any city identifier, month, temperature, and the within-hour spread, since the panel is hourly.

| | |
|---|---|
| Model | XGBoost, squared error on the ratio, one model per horizon, pooled over all series |
| Weights | Last week's level over the series' own average: no series outweighs another, and busy hours count more than dead ones |
| Split | By city. The held-out city contributes nothing: no rows, no shape, no bounds. Donor rows end before the held-out city's test days begin |
| Stopping | Each series' last four weeks; up to 1,500 trees at a learning rate of 0.1, stopping after 40 rounds without gain |
| Settings searched | Depth 4 or 6, minimum child weight 1 or 5; chosen on the stop rows |
| Trust | The forecast is last week's figure plus a share of the model's correction. The share is the one with the lowest error on donor cities held out one at a time. Generated rows are built for each such fold without the group held out |
| Bounds | A relative width plus counting noise, sized so that 95% of held-out-donor errors fall inside; on donor series of the target's kind, at the size nearest the target's |
| Test | The last 60 days of each city's whole-city series. Development used the 60 days before |

**Result.** Against "same hour last week", the error is 7.6%, 8.2% and 8.1% in New York against 8.1% to 8.2%; 5.4%, 5.7% and 6.1% in Chicago against 6.3% to 6.4%; and 11.4%, 13.2% and 13.9% in San Francisco against 14.9%. The bounds held 97% in New York and 99% in Chicago, and 86% to 92% in San Francisco, where only one donor city had earlier data. That's 1 of 4 bars; see `EVALS.md`.

**What guards against overfitting here.** The unit held out is a city, the largest unit there is. The trust setting and the bounds are measured on cities the model wasn't fitted to. The settings search covers four combinations. The test days were scored once.

**What it does not guard against.** Three cities are a small sample of cities, and all three are dense. Every series is trips served, not trips wanted.

**Rebuild.** Run `depot-twin eval e13`, which downloads about 20 GB of New York trip files and keeps only hourly counts. For a new site, run `depot-twin new-site <name> --lat ... --lon ... --kinds outer=0.6,inner=0.4 --rides-per-hour ...`.

## 9. The model workbench (variants of section 6)

**What it is.** This is the one-hour, six-hour and day-ahead forecasts of section 6, built fourteen ways, the reference and thirteen variants, for the front end's forecast mode (`depot_twin/workbench.py`, `depot-twin data models`).

**What is held fixed.** The data, the blocks of days, the features' definitions and the tree settings the reference's search chose (depth 6 at one hour, 4 at six and 24; minimum child weight 1) are all held fixed. Each variant changes one thing only.

**What is measured.** We measure error on the 60 held-out days at each horizon and by hour of day; how often the upper bound held; error on training and validation rows as trees are added; the features' shares of gain; and the depot's fortnight from 15 April 2024 under the price-aware plan, over three seeds.

| Variant | Error, 1 h ahead | Upper bound held |
|---|---|---|
| Reference (725 trees, stopped early) | 11.4% | 92.8% |
| 10, 50, 200 trees | 12.1%, 9.8%, 10.1% | 92.8%, 95.4%, 95.1% |
| 3,000 trees, no early stopping | 12.3% | 90.9% |
| Lags only; lags and calendar | 11.3%; 10.6% | 93.9%; 94.4% |
| 1, 3, 6 months of history | 14.7%, 10.3%, 10.1% | 98.1%, 95.0%, 95.7% |
| Ride counts as the target | 15.5% | 91.7% |
| No local history | 11.3% | 92.4% |
| No model (same hour last week) | 14.9% | 92.1% |
| Pretrained (Chronos-2) | 8.4% | 96.9% |

**Read with care.** Several variants beat the reference on the held-out days. The reference was fixed first and these were scored afterwards, so adopting one on this evidence is tuning on the test set. What the table does suggest for a future round on fresh days is that early stopping on a block containing a level shift stops too late, and that older history may hurt after such a shift.

**Why rides served are the same for every variant.** On the fortnight the depot is run on (15 to 28 April 2024), the busiest hour, scaled to the rides the run offers, needs about 390 vehicles on the road, the chargers take about 100 off it at once, and the fleet is 500: the fleet just covers it, and rides served are 100.0% under every variant. It moves the price paid for energy (last week's curve pays $0.1716 per kWh against $0.1680 for the trained model) and the reserve (62.9 vehicles against 48.5). On that fortnight the trained model and last week's curve are also nearly indistinguishable, 10.8% against 11.1%, with the pretrained model at 8.1%, where the 60-day scores are 11.4%, 14.9% and 8.4%: a quiet fortnight flatters the simple rule. The page shows both scores and says so.

**Failure slices and two importances** (`depot-twin data trust`, on the 60 held-out days, one hour ahead). The model is worth most where last week's curve is worst, on the one holiday in the block, 27 May 2024 (13.8% against 52.8%), weekends (10.5% against 18.1%) and at midday (8.1% against 14.5%); barely ahead at the evening peak (13.8% against 14.2%) and behind late at night (16.1% against 15.2%). Permutation loss on the calibration block, shuffling the model's inputs after scaling and not the level the ratio forecast is multiplied by, puts the minute of the day first (+9.07 points) and the mean rate over the last day second (+8.85); gain puts this week against last and yesterday's slot first. The reference bound's frontier on this city: asked 90, 92.5, 95, 97.5 and 99%, held 85.6, 89.3, 92.8, 96.6 and 98.6%, for 34, 40, 47, 59 and 74 vehicles. The same figures are recorded for every workbench variant (`trust.json`, `variants`), so the page's slices, importances and card follow the chosen model.

## 10. The model fixes (evaluation E17)

The fixes are built in `models/lab.py` as recipes, each one change from the reference: the ratio to a four-week mean of the slot instead of one week; the number of trees chosen on four expanding folds of the training block; five bagged models; a 95th-percentile model corrected by time of day on the calibration block; and rides divided by the trailing four-week level as the fair count target. Every city uses hourly rows and is trained on every hour, and the tree settings are fixed at the reference's.

| | Chicago (confirmation) | New York (confirmation) |
|---|---|---|
| Reference, 1 h | 8.0% | 9.5% |
| All three fixes, 1 h | 8.2% | 8.4% |
| Reserve vehicles, reference to fixes | 38.2 to 32.1 | 34.4 to 28.8 |
| Coverage, reference to fixes | 96.0% to 93.5% | 93.1% to 91.8% |

On San Francisco, the development city, the three fixes kept each helped and the quantile bound did not.

The confirmation cities were thinned to 500 rides an hour, trained on days before 5 January 2026, and scored on 5 January to 1 March 2026; each figure is the mean over six draws of the thinning. The combined recipe is lower than the reference in five draws of six in New York and in one in Chicago. New York's spread between draws comes from two storm days (25 January and 23 February 2026) and their echo a week later through the ratio target, not from the thinning draw. That's 0 of 4 bars, and the reference remains the default; see `EVALS.md` for the bars.

## 11. The reserve–coverage frontier and a pretrained model (evaluation E18)

**What is measured.** At 29 reliability levels from 85% to 99%, we measure each arm's bound sized on the calibration block and read on the test days, the coverage achieved, and the vehicles a 500-vehicle fleet holds above the rides that came. The arms are compared at matched achieved coverage (`models/reserve.py`).

**Arms.** The arms are the reference trees with their symmetric bound; the same forecast with a volume-aware bound, a relative part and a counting part in quadrature; Chronos-2 with no local fitting, univariate, context 2,048 hours, no covariates, pinned to commit `29ec376`; and the mean of the two. Each figure is the mean over three draws of the thinning to depot scale.

| New York yellow, 1 h, confirmation | Error | Reserve at 95% achieved |
|---|---|---|
| Reference, symmetric bound | 9.6% | 40.7 vehicles |
| Reference, volume-aware bound | 9.6% | 52.8 |
| Chronos-2 | 7.7% | 35.7 |
| Ensemble | 8.1% | 37.4 |

**Read with care.** New York taxi data is in the model's public training corpora, so Chicago and San Francisco are the readings that can be called zero-shot. Chicago gives 6.5% error against 8.0% and 26.3 vehicles against 35.3. Nothing was trained here, so there's nothing to over-fit; what could mislead is the corpus overlap, which we state wherever a New York figure appears. The trees remain the default until the pretrained forecast is tested inside the plan.

**On the workbench's San Francisco days** (section 9, the `chronos` variant), the same model gives 8.4%, 9.3% and 9.8% error at one, six and twenty-four hours, against the reference's 11.4%, 11.9% and 12.3%. Its hourly forecasts are read for five-minute rows from the last complete clock hour, weighted over the two clock hours the label straddles, so no row sees its future. Its bound, sized the same way, holds 96.3% to 96.9% of hours against 92.8% to 93.8%, so the two are compared at matched achieved coverage off each one's frontier (`depot-twin data trust`): 95% costs last week's curve 79.3 vehicles, the reference 52.6 and the pretrained model 37.0. The plan's rides are identical, as for every variant.

## Practices used throughout

- A split by the unit that repeats: by design for the simulator stand-ins, by time for forecasts, never by row.
- Something always withheld that the tuning never sees: a band of fleet sizes, a block of days, or designs made after the models were frozen.
- Hyperparameter searches kept small on purpose.
- A test registered before it's run.
- Seeds kept apart: development, training and evaluation never share them.
- Average error isn't enough, so the cases that decide the outcome are scored on their own: designs near the service level, hours at the peak, and designs the search picked.
