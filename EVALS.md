# Evaluations

Every test is written down with what's measured, on what data, against which baseline, and the bar it has to clear, and its bars are fixed before the run reported under it. A miss stays on the page.

The index of every test and how it came out lives in [docs/SCOREBOARD.md](docs/SCOREBOARD.md), generated from the result files. Where a later test overturned an earlier one, the earlier one is marked and kept.

## What every test shares

The site's load manager draws at most 95% of the connection (`DepotConfig.usable_share`; the reasoning is in `docs/SITE.md`), so one feeder is 2,612 kW usable of 2,750. A rider waits up to ten minutes for a free vehicle and is counted lost after that, and rides served means rides served over rides served plus rides given up on. The depot records of E8, E9, E12 and E22 carry the cadence each arm ran at and the share of its vehicles that arrived at the low-battery floor, so an arm named for a rule shows whether that rule was the one deciding. Each result file carries a stamp of the code it ran on (`provenance.py`); the scoreboard shows a record as current only while that code is unchanged.

## E1. Week-ahead demand forecast

Registered 2026-10-04.

- **Question.** Does the forecast predict hourly ride-hail demand a week ahead better than "same hour last week"?
- **Data.** City of Chicago public ride-hail trips, counted per hour, January 2025 to the latest full month available. (The city's 2023 to 2024 dataset timed out on hourly counts, so the series starts in 2025.) Chicago is used because robotaxi trip times are redacted in public filings and no Bay Area city publishes ride-hail trips by the hour.
- **Split.** The final 91 days are held out. The model is trained once on everything before them. Hyperparameters are fixed in `models/demand.py` and are not tuned on the held-out days.
- **Metric.** Weighted absolute percentage error: total absolute error divided by total trips.
- **Baseline.** The count for the same hour one week earlier.
- **Bar.** The model removes at least 15% of the baseline's error.
- **What a miss would mean.** The calendar and trend features add nothing a planner could not get from last week's numbers, and the depot should plan on last week.

### Result

Run 2026-10-08. **0 of 1 bars.** Numbers are in `data/derived/e1_demand.json` and `data/derived/e1_walk_forward.json`; reproduce with `depot-twin eval e1` and `depot-twin eval e1-walk`.

The forecast is XGBoost with a fixed 400 trees, trained on 1 January 2025 to 1 June 2026 and scored on 2,184 held-out hours to 31 August 2026.

| | Error |
|---|---|
| Forecast | 6.24% |
| Same hour last week | 6.29% |

| Bar | Result | |
|---|---|---|
| The forecast removes at least 15% of the baseline's error | 0.7% | **Miss** |

Reported without a bar: four earlier four-week windows, each scored by a model trained only on what came before it. All four end before the held-out period.

| Window ending | Forecast | Same hour last week | Error removed | With early stopping |
|---|---|---|---|---|
| 9 March 2026 | 5.04% | 5.25% | 4% | 5.08% |
| 6 April 2026 | 7.93% | 10.77% | 26% | 7.83% |
| 4 May 2026 | 4.05% | 4.50% | 10% | 4.35% |
| 1 June 2026 | 6.81% | 8.00% | 15% | 6.94% |

What this says:

- **On the registered days the forecast is no better than last week's numbers.** At city scale, hourly ride-hail demand repeats week to week within about 6%, and the calendar and trend features find almost nothing more.
- **It helps where last week is a poor guide.** It beat the baseline in all four earlier windows, by 4% to 26%, and most in the window where last week's figure was furthest off (10.77%). It does not clear 15% reliably, and the registered result is a miss.
- **So the depot plans on last week's demand**, as the registration said a miss would mean. The simulation uses the weekly shape the model produces, not its edge over the baseline, so nothing downstream depends on the missed bar.
- **Setting the number of trees by early stopping did not help.** It was worse in three of the four windows, so the model keeps its fixed 400 trees.
- Weather and local events, which a week-old history cannot see, were not tried.

## E2. Recall rules on a power-constrained depot

> **Superseded.** Every rule here ran with power going to the emptiest vehicle first, which E11 later showed to be the wrong rule when power is short. The ranking of recall rules among themselves stands; the levels do not. See E11.

Registered 2026-10-04.

- **Question.** When the site cannot deliver all the energy the fleet wants, does a smarter rule for calling vehicles in serve more rides than a fixed battery threshold?
- **Setup.** The East Oakland depot on one 2.75 MW service, with 500 and with 1,000 vehicles, simulated for eight days with the last seven measured (the first day is the fleet settling from its starting charge). Ten seeds, 101 to 110. Development used seeds 1 and 2; policy training uses seeds from 1,000 up.
- **Rules.** Threshold (call in at 20%, release at 85%). Headroom (call in the emptiest vehicles when the road can spare them and a charger is free). Plan (an hourly linear program over the next day). Learned (a PPO policy trained on a quarter-scale copy of the 1,000-vehicle scenario and run at full size).
- **Metric.** Share of offered rides served, averaged over the ten seeds. Share of the fleet on the road at peak is reported alongside.
- **What development showed.** On seeds 1 and 2 the plan trailed headroom at 1,000 vehicles. The learned policy had not been trained.
- **Bars.** Five are counted: bar 2 is two bars.
  1. Headroom beats threshold by at least 2 points at 1,000 vehicles.
  2. Plan against headroom: (2a) no worse at 500; (2b) within 0.5 points at 1,000. Development suggests 2b will miss.
  3. Learned beats threshold at 1,000 vehicles, a fleet four times the size it trained on.
  4. Learned is within 1 point of the best hand-written rule at 1,000.
- **What a miss would mean.** For 1: the simple rule is enough and the extra logic is not worth operating. For 2: the fluid plan is too coarse when power is the limit. For 3 and 4: the policy does not transfer across fleet sizes, or learned nothing the hand rules lack.

### Result

Run 2026-10-08. **3 of 5 bars.** Numbers are in `data/derived/e2_recall.json`; reproduce with `depot-twin eval e2`.

| Rule | 500 vehicles | 1,000 vehicles | On the road at peak, 1,000 |
|---|---|---|---|
| Threshold | 98.0% | 74.7% | 32.3% |
| Headroom | 99.1% | 76.7% | 34.7% |
| Plan | 98.8% | 75.9% | 32.5% |
| Learned | 96.5% | 76.4% | 32.8% |

Mean of ten seeds. At 1,000 vehicles the seeds of every rule lie within 1.5 points of each other. At 500 the plan ranges from 97.7% to 99.6% and the learned policy from 93.9% to 97.3%. No vehicle was stranded in any run.

| Bar | Result | |
|---|---|---|
| 1. Headroom beats threshold by 2 points at 1,000 | 2.0 points | **Pass** |
| 2a. Plan no worse than headroom at 500 | 98.8% against 99.1% | **Miss** |
| 2b. Plan within 0.5 points of headroom at 1,000 | 0.8 points behind | **Miss** |
| 3. Learned beats threshold at 1,000 | 1.7 points | **Pass** |
| 4. Learned within 1 point of the best hand-written rule at 1,000 | 0.3 points behind headroom | **Pass** |

What this says:

- **Headroom is the best hand-written rule at both sizes.** The hourly plan trails it by 0.3 points at 500 and 0.8 at 1,000, so the fluid plan is too coarse at this depot whether or not power is the limit.
- **The learned policy carried from 250 vehicles to 1,000.** It serves 1.7 points more than the threshold there and sits 0.3 points behind headroom, inside the spread between seeds.
- **The learned policy is the weakest rule at 500 vehicles,** a size it never trained at, and the least steady from seed to seed. It is not a drop-in replacement.
- **Two points is the most any rule recovers at 1,000 vehicles.** The best rule still loses 23 points of rides, and that is the grid, not the rule.

## Growth study

Run 2026-10-08. A study, no bars. Numbers are in `data/derived/growth.json`; reproduce with `depot-twin eval growth`.

The East Oakland depot at fleets of 200 to 2,000 under three grid options: one 2.75 MW feeder, the same feeder with a 4 MWh battery, and two feeders. Headroom rule, demand drawn from the average week, three seeds. Runs are eight days with the last seven measured: the first day is the fleet settling from its starting charge. Chargers follow the sizing rule at every size.

| Fleet | One feeder | One feeder with battery | Two feeders | Queue wait, one feeder | Grid use, one feeder | On the road at peak, one feeder |
|---|---|---|---|---|---|---|
| 200 | 99.7% | 99.7% | 99.7% | 1 min | 33% | 82% |
| 400 | 99.7% | 99.9% | 99.9% | 1 min | 64% | 79% |
| 500 | 99.2% | 100.0% | 100.0% | 25 min | 77% | 73% |
| 600 | 97.6% | 98.5% | 100.0% | 108 min | 86% | 62% |
| 700 | 93.9% | 96.0% | 99.1% | 210 min | 90% | 52% |
| 800 | 88.8% | 91.4% | 99.6% | 242 min | 92% | 44% |
| 1,000 | 76.5% | 79.2% | 99.2% | 343 min | 95% | 35% |
| 1,200 | 66.0% | 67.7% | 97.5% | 408 min | 97% | 30% |
| 1,500 | 53.7% | 54.5% | 91.2% | 490 min | 98% | 22% |
| 2,000 | 41.4% | 41.6% | 76.7% | 530 min | 99% | 17% |

| Grid option | Largest fleet serving 99% | Largest serving 95% | Hand arithmetic, energy alone |
|---|---|---|---|
| One feeder | 500 | 600 | 613 |
| One feeder with battery | 500 | 700 | 613 |
| Two feeders | 1,000 | 1,200 | 1,227 |

What this says:

- **One feeder carries 500 vehicles at 99% and 600 at 95%.** Hand arithmetic on energy alone says 613. The simulation is lower because the queue forms before the energy runs out: at 500 vehicles the site uses 77% of its usable power and a vehicle already waits 25 minutes for a charger.
- **A battery buys one step at the 95% level and nothing at 99%.** It lifts 600 vehicles from 97.6% to 98.5% and 700 from 93.9% to 96.0%.
- **A second feeder doubles the site:** 1,000 vehicles at 99%, 1,200 at 95%.
- **2,000 vehicles do not fit on this parcel's grid:** 76.7% on two feeders.
- Every run here used the headroom rule with power going to the emptiest vehicle first. E11 found that power rule costs rides when power is short, so these levels are a floor; the second version of the study adds an arm with in-order feeding.

## E3. A fast stand-in for the simulator

> **Superseded.** Its runs measure only two quiet weekdays, and it is built on the first version of the simulator. E4 measures a full week. Kept because the money gap it shows is part of the record.

Registered 2026-10-04.

- **Question.** Can gradient-boosted trees (XGBoost) predict what the simulator would say about a depot design well enough to search designs with, without having memorized the designs they were trained on?
- **Data.** 1,600 designs drawn at random from the ranges in `surrogate.py` (fleet 150 to 2,200, grid connection 1 to 9 MW, fast and slow charger counts, charger power, battery, demand level and peakiness, energy per mile, staffing, recall and release levels). Each is simulated for three days and measured on the last two. The first 200 designs are simulated a second time under another seed.
- **Split.** By design, never by row, so both runs of a design sit on the same side.
  - Designs with a fleet of 900 to 1,150 are withheld from training and validation entirely (the gap set).
  - The rest are split at random 70% train, 15% validation, 15% test.
  - Hyperparameters are chosen by 5-fold cross-validation inside the training set, from a grid of 12. The number of trees is set by early stopping on the validation set. The test and gap sets are held out of every choice.
- **Metric.** Mean absolute error on the share of rides served, in points.
- **Baseline.** The spreadsheet answer: energy the site can deliver over energy the fleet wants, capped at 100%.
- **Bars.**
  1. Test error is 1.5 points or less.
  2. Test error is at most half the spreadsheet's error on the same designs.
  3. On test designs where the simulator says fewer than 99% of rides are served (the cases that matter), error is 3 points or less.
  4. No overfitting: test error is at most 1.3 times validation error. Training error is reported beside both.
  5. On the gap set, error is 2.5 points or less.
  6. In use: for three cases (500 and 1,000 vehicles on 2.75 MW, 1,500 vehicles on 5.5 MW), the design the trees pick as most profitable is simulated. The simulated share of rides served is within 2 points of the prediction, and the simulated contribution per vehicle within 5%.
- **Also reported, no bar.** The seed-to-seed difference between two runs of the same design, which is the error no model can get under. Errors for the other three predicted quantities. The features the trees lean on most.
- **What a miss would mean.** For 1 to 3: the trees are not accurate enough to search with, and sizing stays in the simulator. For 4 and 5: they memorized the sampled designs and cannot be trusted between them. For 6: the search finds designs that look good only to the trees, which is the failure that matters most.

### Result

Run 2026-10-08. **4 of 6 bars.** Numbers are in `data/derived/e3_surrogate.json`; reproduce with `depot-twin eval e3`.

| | Error on share of rides served |
|---|---|
| Training (1,019 designs) | 0.19 points |
| Validation (219 designs) | 0.43 points |
| Test (219 designs) | 0.62 points |
| Gap set (143 designs, fleets of 900 to 1,150) | 0.78 points |
| Test designs under 99% service (53 designs) | 2.06 points |
| Spreadsheet, on the test designs | 6.22 points |
| Two runs of the same design | 0.29 points |

The three designs the trees picked, simulated:

| Case | Rides served, predicted | Simulated | Contribution per vehicle, predicted | Simulated |
|---|---|---|---|---|
| 500 vehicles on 2.75 MW | 100.0% | 100.0% | $444.34 | $387.90 |
| 1,000 vehicles on 2.75 MW | 88.3% | 89.7% | $398.23 | $353.89 |
| 1,500 vehicles on 5.5 MW | 99.8% | 99.3% | $454.81 | $395.78 |

| Bar | Result | |
|---|---|---|
| 1. Test error at most 1.5 points | 0.62 | **Pass** |
| 2. At most half the spreadsheet's error | A tenth of it | **Pass** |
| 3. Constrained designs at most 3 points | 2.06 | **Pass** |
| 4. Test at most 1.3 times validation | 1.45 times | **Miss** |
| 5. Gap set at most 2.5 points | 0.78 | **Pass** |
| 6. Picked designs hold up in simulation | Service within 1.5 points in all three cases; contribution predicted 13% to 15% above the simulated figure in all three | **Miss** |

What this says:

- **The trees predict service well across sampled designs.** They interpolate across fleet sizes they never saw, and they lean on grid power per vehicle (51% of the gain) and the energy ratio (33%), which is what the physics says should matter.
- **Bar 4 is a real warning.** Test error is small in absolute terms, about twice the seed-to-seed difference, but training error is a third of it. The models fit their training designs more closely than they generalize.
- **The money does not hold in any case.** The simulated contribution counts the rides of the two days each run measures, a Tuesday and a Wednesday. The prediction assumes an average day's demand. No design here was judged on a Friday or Saturday peak.
- **The error sits in the designs that matter:** 2.06 points where service is under 99%, against 0.62 overall, because most random designs are overbuilt and serve everything.
- This search carries no service floor. E4 measures a full week, samples where the decision lives, and tests a search that must hold 99%.

## E4. A planner that can be trusted with the search

> **Superseded.** First-version simulator: emptiest-first power, one energy figure for every vehicle, demand drawn from an average week. The method and what it showed about searching with a model stand. It chose no depot design.

Registered 2026-10-04. Runs are eight days with the last seven measured, so every weekday counts once (E3's three-day runs measured only two quiet days); to pay for the longer runs the pool is 1,000 plus 1,000 designs and the random reference set is 100 per case. E4 is E3 rebuilt around one point: an optimizer does not sample a surrogate fairly, it hunts for the designs the surrogate likes best, so average error says little about whether the chosen design is real.

- **What changed from E3.**
  - Runs measure a full week, not two weekdays.
  - Sampling: half the designs are space-filling (Sobol), half are placed where the site delivers 0.8 to 1.3 times the energy the fleet wants and the chargers 0.9 to 2.5 times, because that edge is where the planner searches.
  - Targets are trained on a logit or log scale, so no prediction can leave its physical range.
  - Two features added: chargers per vehicle and battery kWh per vehicle. The peak-draw model is dropped; the capacity subscription is costed at the full connection.
  - The planner accepts a design only if predicted service, less the 90th percentile of the model's over-prediction on validation designs it predicts to pass, is still 99%.
  - A design can be chosen to hold 99% service in 95% of demand scenarios (level varying by 8%, peak from slightly flatter to sharper), not only on the expected week.
- **Data.** 1,000 Sobol designs and 1,000 boundary designs, one simulation each; the first 100 of each simulated again under a second seed. Fleets of 900 to 1,150 are withheld as before. The rest are split by design 70/15/15. Hyperparameters by 5-fold cross-validation grouped by design, inside the training set; trees by early stopping on validation.
- **Prospective set.** 300 new designs (150 Sobol, 150 boundary, new seeds) are generated and simulated only after the models are frozen.
- **Search test.** Three cases the site can serve: 400 and 600 vehicles on 2.75 MW, 1,000 on 5.5 MW. For each, the planner ranks 20,000 candidate designs; its top 50 and 100 candidates drawn at random are all simulated.
- **Bars.**
  1. Prospective error on rides served is 1.5 points or less, and 1.5 points or less on the designs the simulator puts between 95% and 99.9% service.
  2. No overfitting: prospective error is at most 1.3 times validation error.
  3. Gap-set error is 2.5 points or less.
  4. Regret: in each case, the simulated contribution of the planner's first pick is within 2% of the best simulated design that truly serves 99% (among all 150 simulated). At least 40 of its top 50 truly serve 99%, and none serves under 97%.
  5. For 1,000 vehicles on 2.75 MW, which the growth study shows cannot reach 99%, the planner returns no design.
  6. Robustness: the design chosen across demand scenarios, simulated under 20 fresh scenarios, serves 99% in at least 18. The design chosen on expected demand alone is reported beside it.
  7. No prediction on the prospective set or the candidates falls outside its physical range.
- **Also reported, no bar.** Rank correlation between predicted and simulated contribution; the seed-to-seed noise floor; the margin; how the robust design differs from the expected-demand design.
- **Limits stated in advance.** Trip length is fixed at the filed 4.92 miles and is not an input. Regret is measured against the best of 150 simulated designs per case, not a true optimum, which is unknown.
- **What a miss would mean.** For 1 to 3: as in E3. For 4: the search finds designs that look good only to the model. For 5: the margin is too loose. For 6: planning on expected demand is not enough, and the scenario method does not fix it.

### Result

Run 2026-10-08. **5 of 7 bars.** Numbers are in `data/derived/e4_planner.json`; reproduce with `depot-twin eval e4`.

| | Error on share of rides served |
|---|---|
| Training (1,271 designs) | 0.27 points |
| Validation (272 designs) | 1.28 points |
| Test (273 designs) | 1.40 points |
| Gap set (184 designs, fleets of 900 to 1,150) | 1.44 points |
| Prospective (300 designs made after the models were frozen) | 1.34 points |
| Prospective, designs between 95% and 99.9% service (129) | 0.68 points |
| Spreadsheet, on the prospective designs | 4.79 points |
| Two runs of the same design | 0.23 points |

The margin is 1.35 points, so a design needs a predicted 100.35% to be accepted, and no prediction passes 100%. The planner offered no design in any of the three cases, on expected demand or across scenarios. With nothing offered there is no first pick, no top 50 and no regret to measure.

| Bar | Result | |
|---|---|---|
| 1. Prospective error at most 1.5 points, overall and in the 95% to 99.9% band | 1.34 and 0.68 | **Pass** |
| 2. Prospective at most 1.3 times validation | 1.05 times | **Pass** |
| 3. Gap set at most 2.5 points | 1.44 | **Pass** |
| 4. Regret at most 2%; 40 of the top 50 truly at 99%; none under 97% | Nothing offered in any case | **Miss** |
| 5. No design offered for 1,000 vehicles on 2.75 MW | None offered | **Pass** |
| 6. Robust design holds in 18 of 20 scenarios, every case | No design chosen in any case | **Miss** |
| 7. Predictions inside their physical range | All inside | **Pass** |

What this says:

- **The planner declines to choose.** Its margin, 1.35 points, is wider than the one point of room any candidate has above the 99% service level. A stand-in whose error near the service level is larger than the room above it cannot be trusted with the search, and a planner honest about that error offers nothing.
- **Average accuracy does not show it.** Held-out, gap and prospective errors agree at 1.3 to 1.4 points, under a third of the spreadsheet's, and the band near the service level is at 0.68. The margin is the 90th percentile of over-prediction among designs predicted to pass, and that tail is what the planner has to hold back.
- **Bar 5 passes without telling the cases apart.** The planner returns nothing for the fleet the feeder cannot serve, and nothing for the three it can.
- **The models fit their training designs closely,** 0.27 points against 1.28 on validation.
- Planning on expected demand against planning across scenarios is not measured: neither had a design to simulate.

## E5. Teaching the planner where it searches

> **Superseded.** First-version simulator, as E4.

Registered 2026-10-04.

E4's margin is measured on validation designs, not on the designs a search goes hunting for, and an optimizer selects for the model's errors. The method registered here is the standard one: simulate what the search picks, add those runs to the training data, and repeat, so the model learns the region the optimizer visits.

- **Method.**
  1. Round one: 30 situations drawn at random (fleet 200 to 1,800; a grid connection that can deliver 1.05 to 1.8 times the fleet's energy; demand level, peakiness and energy per mile from their ranges). For each, the E4 planner ranks 5,000 candidate designs and its top 20 are simulated for a full week. Those runs join the training set and the models are retrained, with hyperparameters chosen again by grouped cross-validation.
  2. Round two: the same with 30 new situations and the retrained planner.
  3. Margin: 12 further situations, top 20 each, simulated but never trained on. The margin becomes the 90th percentile of over-prediction on these searched designs; with none picked, the margin from training stands.
- **Test.** The three E4 cases, searched afresh with the final planner: its top 50 and the same 100 random candidates are simulated. These cases were seen once in E4; none of their designs is in the training or margin data.
- **Bars.**
  1. The E4 search bar, unchanged: regret at most 2% in every case, at least 40 of the top 50 truly at 99% service, none under 97%.
  2. The first pick itself truly serves 99% in every case.
  3. Accuracy elsewhere is not traded away: error on the E4 prospective designs stays at or under 1.5 points and 1.3 times validation error.
- **Also reported.** Over-prediction on searched designs after each round; the margin; how many candidates remain acceptable in each case.
- **What a miss would mean.** For 1 and 2: two rounds are not enough, or the simulator's own week-to-week noise near 99% is too large for any model to rank through, and the simulator must stay in the loop for every decision. For 3: the model has been bent toward the searched region at the expense of the rest.

### Result

Run 2026-10-08. **1 of 3 bars.** Numbers are in `data/derived/e5_active.json`; reproduce with `depot-twin eval e5`.

With nothing picked there is nothing to retrain on. Both rounds hold 0 designs, the margin stays at the 1.35 points from training, and none of the 20,000 candidates is acceptable in any of the three cases. The model is E4's, on the same 1,271 training designs.

| Bar | Result | |
|---|---|---|
| 1. Regret at most 2%; 40 of the top 50 at 99%; none under 97% | Nothing offered in any case | **Miss** |
| 2. First pick truly serves 99% | No first pick in any case | **Miss** |
| 3. Prospective accuracy kept | 1.34 points, 1.05 times validation | **Pass** |

What this says:

- **The loop never starts.** It learns from what the search picks, and a planner that accepts nothing picks nothing. Bar 3 passes because the model is unchanged.
- **Across E3 to E5, the stand-in is accurate on average and not near the edge that matters.** It can shortlist, and the simulator decides.
- The registration's reading of a miss on bars 1 and 2 holds: the simulator stays in the loop for every decision.

## E6. Identifying the twin from telemetry

Registered 2026-10-04.

- **Question.** No two vehicles use the same energy, and the true figures are not public. Can each vehicle's driving energy (kWh per mile) and always-on load (kW), and each vehicle type's charge curve, be recovered from the telemetry the vehicle already produces?
- **Why it is a test and not an assumption.** In the simulator each vehicle is given true values the estimator never sees: its type's figure moved by a random 8% (one standard deviation), separately for driving and for always-on load. The estimator starts from the type's figure and sees only, every five-minute simulation step, the miles driven, the time elapsed and the change in the battery gauge, which is noisy (0.1% of the pack per reading).
- **Setup.** 500 vehicles (60% I-PACE at 0.30 kWh per mile and 2.0 kW; 40% Ojai at 0.27 and 1.8), 2.75 MW, 60 kW chargers, seven days, headroom rule.
- **Method.** One two-parameter Kalman filter per vehicle for energy. For charge curves, the median power delivered in each 5% band of charge, using only readings where the vehicle received all it could take.
- **Baseline.** Using the type's figure for every vehicle, which is what the twin does without identification.
- **Bars.**
  1. Driving energy: median error across vehicles at most 3%, and at most half the baseline's.
  2. Always-on load: median error at most 5%, and at most half the baseline's.
  3. At least nine vehicles in ten are within 8% on both.
  4. Each type's charge curve is within 3 kW on average of the truth (the lower of what the battery accepts and what the charger delivers), over the bands seen.
- **Also reported.** Error after one day against seven.
- **Limit stated in advance.** This shows the estimator works on the simulator's own vehicles. It says nothing about what the true figures are for a real fleet; it says they would not need to be assumed.
- **What a miss would mean.** For 1 to 3: miles and hours move together too closely in service for the two effects to be separated, and the twin would have to identify one combined figure. For 4: sessions are too often power-limited for the battery's own limit to be seen.

### Result

Run 2026-10-08. **3 of 4 bars.** Numbers are in `data/derived/e6_identify.json`; reproduce with `depot-twin eval e6`.

| | Using the type's figure | Identified after 1 day | Identified after 7 days |
|---|---|---|---|
| Driving energy, median error | 5.4% | 4.2% | 2.2% |
| Always-on load, median error | 5.2% | 4.8% | 3.0% |

| Bar | Result | |
|---|---|---|
| 1. Driving energy within 3% and half the baseline | 2.2% against 5.4% | **Pass** |
| 2. Always-on load within 5% and half the baseline | 3.0% against 5.2%: inside 5%, short of half | **Miss** |
| 3. Nine vehicles in ten within 8% on both | 91.4% | **Pass** |
| 4. Charge curves within 3 kW | 0.04 kW over 16 bands and 0.00 kW over 15 | **Pass** |

A vehicle gave a median of 1,627 readings in the week.

What this says:

- **Driving energy separates cleanly.** A week of telemetry cuts the error of the type's figure by more than half, and one day already removes a fifth of it.
- **Always-on load is harder.** A week takes its error from 5.2% to 3.0%, which is useful and short of the halving the bar asked for.
- **Nine vehicles in ten are within 8% on both figures,** with little to spare.
- Bar 4 is weaker evidence than it looks. Power readings in the simulator carry no noise, so the charge-curve result mostly shows that discarding power-limited readings is the right logic. A real meter would need the same test with noise.
- As stated in advance, this shows the method works on the simulator's own vehicles, not what the true figures are.

## E7. Ride forecasts for the controller

Registered 2026-10-04. Exact repeats of records are dropped (6% to 15% of records, depending on the month), and a break in the series is noted below.

- **Question.** A controller that decides every five minutes needs to know how many rides to expect in an hour, one, six and twenty-four hours ahead, and how wrong that could be. Can it be told, with honest error bars?
- **Data.** San Francisco taxi trips from the city's open data, 1 December 2022 to 31 May 2024, counted in five-minute steps. A record counts as a ride if it is not paratransit, covers at least 300 metres and lasts at least a minute. Hourly weather from a public archive of forecasts.
- **A break in the data, found before fitting.** From mid-February 2024 reported rides rise by about half, with dispatched trips roughly doubling, while the number of cabs reporting stays near 790. That looks like a change in what is reported, not in demand. It falls just before the calibration and held-out blocks. It is left in: a controller's forecasts have to survive a shift like this, and the test will show whether these do.
- **What is forecast.** Rides in the hour that starts h after the moment of prediction, for h of 1, 6 and 24 hours. One model per horizon.
- **Label.** The value later observed. Nothing else in a row comes from after the moment of prediction, except the weather forecast for the target hour and the target hour's calendar. That is checked by a unit test (`tests/test_features.py`), which changes every value after a moment and checks that no feature at that moment moves.
- **Features (21).** From the series: the hourly rate now, 1 hour, 24 hours and 7 days ago; the target's own slot on the latest earlier day and week available; spread within the last hour; mean, maximum and minimum over the last day; the rate now against the same time last week. Calendar of the target hour: hour, weekday, weekend, holiday, month, minute of day. Weather: temperature and rain now, and forecast for the target hour.
- **Split, in time order.** The last 60 days are held out. Before them, 28 days calibrate the intervals. Before those, 28 days set the number of trees by early stopping. Everything earlier trains. Rows whose label reaches into the next block are dropped, so no label is shared across a boundary. Training rows are taken every 15 minutes, since hourly sums five minutes apart overlap almost entirely.
- **Tuning.** Depth (4, 6) and minimum child weight (1, 5): four combinations, chosen by expanding-window cross-validation inside the training block. Learning rate 0.05, row and column sample 0.8, Poisson objective.
- **Intervals.** Split conformal: the error on the calibration block, scaled by the square root of the prediction, gives the bound. The controller plans against the upper 95% bound.
- **Baselines.** The last hour's rate; the same time on the latest earlier day; the same time last week. The best of the three on the early-stopping block is the one to beat.
- **Bars, for each horizon.**
  1. Model: removes at least 15% of the best baseline's error on the held-out days (total absolute error over total rides).
  2. Intervals: the upper 95% bound holds for between 93% and 97% of held-out hours.
  3. At the peak: over the busiest tenth of held-out hours, the forecast is not low by more than 3% on average. Under-predicting the peak is the error that costs rides.
- **Also reported, no bar.** The same models without weather; the inputs they lean on most; the same pipeline on Chicago's hourly ride-hail series, as a check that the method is not tuned to one city.
- **Limits stated in advance.** Taxis, not ride-hail. Trips served, not trips requested. The weather "forecast" is from an archive that is a little better than a real forecast a day ahead would have been. The series ends in May 2024.
- **What a miss would mean.** For 1: recent history adds nothing the calendar and last week do not, and the controller plans on the baseline. For 2: the intervals cannot be planned against as they stand. For 3: the model is right on average and wrong when it matters.

### Result

Run 2026-10-08. **0 of 9 bars.** Numbers are in `data/derived/e7_forecasts.json`; reproduce with `depot-twin eval e7`.

San Francisco, on the 60 held-out days:

| Horizon | Forecast error | Best baseline | Error removed | Upper bound held | At the peak |
|---|---|---|---|---|---|
| 1 hour | 15.5% | 15.4% (same time yesterday) | -0.6% | 91.7% | 24% low |
| 6 hours | 24.3% | 15.4% (same time yesterday) | -58% | 90.4% | 40% low |
| 24 hours | 24.3% | 14.9% (same time last week) | -63% | 88.8% | 43% low |

The same pipeline on Chicago's hourly series, reported without a bar:

| Horizon | Forecast error | Best baseline | Error removed | Upper bound held | At the peak |
|---|---|---|---|---|---|
| 1 hour | 4.1% | 6.4% | 36% | 95.1% | 1.1% low |
| 6 hours | 4.6% | 6.4% | 28% | 95.3% | 0.5% low |
| 24 hours | 4.9% | 6.3% | 22% | 97.4% | 0.4% low |

| Bar | Result | |
|---|---|---|
| 1. Removes 15% of the best baseline's error | Adds 0.6%, 58% and 63% at 1, 6 and 24 hours | **Miss** at every horizon |
| 2. Upper bound holds 93% to 97% of the time | 91.7%, 90.4%, 88.8% | **Miss** at every horizon |
| 3. Not low by more than 3% at the peak | 24%, 40%, 43% low | **Miss** at every horizon |

Without weather the error moved by less than a point at 1 and 6 hours (15.4% and 23.8%) and rose to 26.8% at 24.

What this says:

- **The break in the data decided it.** Training ends before the mid-February 2024 rise noted in the registration, and the held-out days sit after it. A tree model predicts by averaging training examples that look alike, so it cannot predict a busier hour than it has seen. At the peak it ran 24% to 43% low. "Same time last week" has no such ceiling: it moves with the level by construction.
- **The method is not broken where the level is stable.** On Chicago the forecast removes 22% to 36% of the baseline's error, the bounds hold 95% to 97% of the time, and at the peak it is low by about 1% or less.
- **The peak bar earned its place.** Average error at one hour was level with the baseline. Scored only on the busiest tenth of hours, the forecast came in a quarter low. A controller planning on it would have run short exactly when it mattered.
- **What follows, as registered.** The controller plans on the baseline, not on these models.

The reading suggests a fix: forecast the ratio to last week instead of the count, so the model has no ceiling. That is a new test, E7b.

## E7b. The same forecasts on a scale-free target

Registered 2026-10-04, after E7's result.

- **Question.** If E7 failed because tree models extrapolate poorly beyond the level they trained on, does forecasting the ratio to the same time last week, instead of the count, fix it?
- **Change from E7.** The objective becomes squared error on the ratio, where E7 fitted counts. The label becomes rides in the target hour divided by rides in the same hour last week. Every feature taken from the series is divided by the same reference. Rows are weighted by the reference, so busy hours count for more. The prediction is the predicted ratio times the reference. Data, split, tuning grid, bounds, baselines and bars are E7's.
- **An honest caveat.** The held-out days are the same ones E7 was scored on, so this is a second look at them, made knowing why the first failed. It tests a diagnosis; it is not fresh evidence. Fresh evidence will be the controller's own running under replayed demand in E8.
- **Bars.** E7's three, for each horizon.
- **What a miss would mean.** The level shift was not the whole story, and the controller stays on the baseline.

### Result

Run 2026-10-08. **5 of 9 bars.** Numbers are in `data/derived/e7b_scale_free.json`; reproduce with `depot-twin eval e7b`.

| Horizon | Forecast error | Same hour last week | Baseline the bar used | Error removed (bar) | Upper bound held | At the peak |
|---|---|---|---|---|---|---|
| 1 hour | 11.4% | 14.9% | 15.4% (same time yesterday) | 26% | 92.8% | 7.8% low |
| 6 hours | 11.9% | 14.9% | 15.4% (same time yesterday) | 23% | 93.3% | 10.9% low |
| 24 hours | 12.3% | 14.9% | 14.9% (same time last week) | 17% | 93.8% | 8.0% low |

| Bar | Result | |
|---|---|---|
| 1. Removes 15% of the best baseline's error | 26%, 23% and 17% at 1, 6 and 24 hours | **Pass** at every horizon |
| 2. Upper bound holds 93% to 97% of the time | 92.8%, 93.3%, 93.8% | **Miss** at 1 hour, by 0.2 points; **Pass** at 6 and 24 |
| 3. Not low by more than 3% at the peak | 7.8%, 10.9%, 8.0% low | **Miss** at every horizon |

What this says:

- **The ceiling was the problem.** Changing the target from a count to a ratio to last week took the error from E7's 15.5%, 24.3% and 24.3% to 11.4%, 11.9% and 12.3%, across a level shift the models never trained on. The forecast went from worse than the baseline to 17% to 26% better.
- **The better simple rule on the held-out days is "same hour last week" at every horizon.** At 1 and 6 hours the bar used "same time yesterday", the best on the early-stopping block, which scored 15.4% against last week's 14.9%. Against last week the forecast still removes 24% and 20% of the error, so bar 1 holds on either rule.
- **The bounds are close to honest, slightly thin.** They hold 93% to 94% of the time against a stated 95%. The calibration days sat inside the shift, which is the likely reason.
- **The peak bar is missed at every horizon,** by far less than in E7, where the forecast ran 24% to 43% low. The bar picks the busiest tenth of hours by what actually happened, and any forecast looks low on hours chosen for having turned out high. It stays recorded as a miss. E8 measures whether the upper bound, which the controller plans against, holds in the busiest hours.
- **Weather did not help.** Without it the error was lower at 1 and 24 hours (10.6% and 11.6%) and higher at 6 (12.8%). It stays in the feature set as registered.
- **As the caveat said, this is a second look at the same days.** It confirms why E7 failed. The controller uses these scale-free models.

## E8. The heartbeat controller

> **Read with E11.** E11 showed the gain over headroom came from the power rule the controller shipped with, not from its plan.

Registered 2026-10-04, after development on other days (18 to 31 March 2024). The session design below came out of that development, for the reasons given under it.

- **Question.** Does a depot run as a heartbeat (short time-boxed charging sessions, arriving in small phased groups, with the number called in each hour set by an optimization against the upper bound of the ride forecast) serve more rides, draw power more evenly, and keep its promises, compared with the headroom rule that fills every free charger at once?
- **What is new in the test itself.** Demand is not drawn from an average week. It is replayed from real days: San Francisco taxi rides in five-minute steps, scaled so the fleet is offered 25 rides a vehicle a day on average. The controller sees only the forecasts made at each moment by the E7b models from the history up to that moment, so its forecast errors are real ones.
- **Days.** 14 days from Monday 15 April 2024, inside the block E7 held out. The first seven are warm-up (the fleet settles and the controller learns its own plan error); the last seven are scored. Five seeds, 201 to 205.
- **Setup.** East Oakland on one 2.75 MW feeder, 500 and 1,000 vehicles, 60 kW chargers, each vehicle type with its own energy use and each vehicle differing from its type by a random 8%. The controller uses energy figures identified from telemetry as in E6, not the true ones.
- **The controller.**
  - Tick: five minutes.
  - A session is one slot: the energy a charger delivers in a 60-minute beat at full rate (about 56 kWh), ending at 85% charge at most. A vehicle is called only if it has room for at least 90% of a slot.
  - No more vehicles are plugged in than the site can feed at full rate (40 on this feeder), and they are fed in order of plugging in.
  - Chargers are worked in twelve phases, so at most a twelfth of them turn over per tick.
  - **Why an hour, measured in energy.** On the development days, 30-minute sessions cut off by the clock served far fewer rides than the headroom rule at both sizes, for two reasons. Every visit costs the road over an hour whatever it delivers (15 minutes each way, plugging, cleaning), so two or three short top-ups a day take more vehicle-hours than they return in energy; and with 60 kW chargers the charge rate is flat up to about two thirds full, so short sessions buy no speed. And when the site is short of power, a slot measured in minutes sends vehicles away half fed. The public figure of about three short sessions a day may reflect faster chargers or chargers nearer the riders than this depot's.
  - Each hour a linear program plans the next 24 against the upper 95% bound of demand and returns how many vehicles to call in this hour. The emptiest vehicles under 75% are called, timed to arrive as chargers come free.
  - Ledger: at the start of each hour the controller commits a number of vehicles on the road for that hour: its plan, less the 95th percentile of its own plan error over the previous seven days.
- **Compared with.** The headroom rule and the fixed threshold, given the same forecasts and the same replayed demand.
- **Bars.**
  1. Product: at 1,000 vehicles the heartbeat serves at least 1 point more rides than headroom. At 500 it is no more than 0.2 points worse.
  2. Product: the ledger is kept in at least 95% of scored hours, at both sizes.
  3. Product: no vehicle is stranded.
  4. Grid: at 500 vehicles the minute-to-minute variation of grid draw (standard deviation over mean) is at most half of headroom's.
  5. System: a tick takes under 50 ms at the median and under 500 ms at the 99th percentile.
- **Also reported, no bar.** Sessions per vehicle per day and energy per session (public filings suggest about three and about 29 kWh); energy delivered per charger-hour; share of the fleet on the road in the busiest hours; how often the forecast's upper bound held, overall and in the hours forecast to be busiest (E7's peak check, read on the hours forecast to be busiest).
- **Limits stated in advance.** Taxi demand, scaled. The same days E7 and E7b were scored on, though the controller is scored on rides and promises, not forecast error. One site, one week.
- **What a miss would mean.** For 1: at a site this short of energy, orchestration does not buy rides, only smoothness. For 2: the plan is too optimistic about itself to be promised against. For 4: phasing does not flatten the draw in practice. For 5: the optimization is too slow to run on the tick.

### Result

Run 2026-10-08. **4 of 5 bars.** Numbers are in `data/derived/e8_heartbeat.json`; reproduce with `depot-twin eval e8`.

| | Threshold | Headroom | Heartbeat |
|---|---|---|---|
| Rides served, 500 vehicles | 99.8% | 100.0% | 100.0% |
| Rides served, 1,000 vehicles | 80.8% | 82.4% | 87.6% |
| Fleet on the road in the busiest hours, 500 | 81.6% | 82.0% | 87.7% |
| Fleet on the road in the busiest hours, 1,000 | 41.8% | 42.9% | 47.8% |
| Grid draw variation, 500 | 0.39 | 0.56 | 0.22 |
| Energy per charger-hour, 500 | 26.8 kWh | 26.8 kWh | 28.3 kWh |
| Sessions per vehicle per day, 500 | 1.4 of 61 kWh | 1.6 of 52 kWh | 1.6 of 56 kWh |
| Trips per visit, 500 and 1,000 | 18.0 and 23.0 | 15.3 and 21.8 | 15.6 and 21.3 |
| Share of the plan's calls made by the low-battery floor, 500 and 1,000 | | | 0.0% and 97.6% |
| Vehicles stranded | 0 | 0 | 0 |

Mean of five seeds over the last seven of fourteen days.

| Bar | Result | |
|---|---|---|
| 1. At least 1 point more rides than headroom at 1,000; no more than 0.2 worse at 500 | 5.2 points more at 1,000; level at 500 | **Pass** |
| 2. Ledger kept in 95% of scored hours | 98.6% at 500, 93.3% at 1,000 | **Miss** |
| 3. No vehicle stranded | None | **Pass** |
| 4. Grid draw variation at most half of headroom's at 500 | 0.22 against 0.56 | **Pass** |
| 5. Tick under 50 ms at the median and 500 ms at the 99th percentile | 0.4 ms and 15.9 ms at worst | **Pass** |

The forecast's upper bound held in 92.2% of scored hours, and in every one of the hours forecast to be busiest.

What this says:

- **At 1,000 vehicles the heartbeat serves 5.2 points more rides than headroom on the same feeder.** E11 found that this gain comes from the power rule the controller ships with, not from its plan.
- **At that size the floor, not the plan, is calling vehicles in.** 97.6% of the plan's calls at 1,000 vehicles were made by the low-battery floor, and every visit arrived at the floor, under headroom as well. A site this short of energy leaves the plan nothing to choose.
- **Where the site is not short, the heartbeat buys smoothness and availability.** At 500 the rides are level, the grid draw varies less than half as much as under headroom, and six points more of the fleet is on the road in the busiest hours.
- **The ledger holds at 500 and over-promises at 1,000:** 93.3% of commitments kept against a stated 95%, while promising 87.7% of what was delivered. E9 rebuilds the ledger.
- **The forecast bound is a little thin overall and sound where it matters:** 92% of all hours, and every hour that was expected to be busy.
- **The controller is cheap to run,** under 16 ms a tick at the 99th percentile.

## E9. A ledger that keeps its word, and E8 again on fresh days

Registered 2026-10-04.

- **Question.** E8's ledger kept its promises 93% of the time at 1,000 vehicles against a stated 95%. Can it be made to hold, without becoming a promise of nothing? And does E8's main result repeat on days it was not run on?
- **What changed in the ledger, found on the development days (18 to 31 March 2024).**
  - The promise starts from what is on the road at the start of the hour, moved by the change in how many vehicles the plan calls in. E8's version used the plan's steady-state figure, which ignores vehicles already on their way in or out; at 1,000 vehicles that figure was so far off that a wider margin drove the promise below zero.
  - The margin is built to keep 97.5% of promises, so that 95% can be stated and met over a single week of 168 promises.
  - The margin corrects itself: each broken promise widens it, each kept one narrows it slightly.
  - Nothing else in the controller changes. The ledger does not feed back into control.
- **Days.** 14 days from Monday 13 May 2024: later than every day used so far. Seven warm-up, seven scored. Five seeds, 301 to 305. Same depot, fleets and demand scaling as E8.
- **Bars.**
  1. The ledger is kept in at least 95% of scored hours, at 500 and at 1,000 vehicles.
  2. It is not vacuous: what was promised adds up to at least 90% of what was delivered.
  3. E8 repeats: the heartbeat serves at least 1 point more rides than headroom at 1,000 vehicles and is no more than 0.2 points worse at 500.
  4. No vehicle is stranded.
- **What a miss would mean.** For 1 and 2: the depot cannot yet state a dependable hourly commitment. For 3: E8's gain belonged to one week.

### Result

Run 2026-10-08. **4 of 4 bars.** Numbers are in `data/derived/e9_ledger.json`; reproduce with `depot-twin eval e9`.

| | 500 vehicles | 1,000 vehicles |
|---|---|---|
| Ledger kept | 98.0% of hours | 96.5% of hours |
| Promised, as a share of what was delivered | 93.7% | 97.3% |
| Rides served, heartbeat | 100.0% | 88.6% |
| Rides served, headroom | 100.0% | 84.3% |
| Grid draw variation, heartbeat against headroom | 0.21 against 0.58 | flat out against 0.19 |
| Trips per visit, heartbeat against headroom | 14.9 against 13.9 | 20.4 against 21.6 |
| Share of the plan's calls made by the low-battery floor | 0.0% | 97.7% |
| Vehicles stranded | 0 | 0 |

Mean of five seeds.

| Bar | Result | |
|---|---|---|
| 1. Ledger kept in 95% of scored hours, both sizes | 98.0% and 96.5% | **Pass** |
| 2. Promised at least 90% of what was delivered | 93.7% and 97.3% | **Pass** |
| 3. At least 1 point more rides than headroom at 1,000; no more than 0.2 worse at 500 | 4.3 points more at 1,000; level at 500 | **Pass** |
| 4. No vehicle stranded | None | **Pass** |

What this says:

- **The depot can state an hourly commitment and keep it.** It promises 94% to 97% of the vehicles it goes on to deliver and keeps the promise in 96% to 98% of hours.
- **A promise built from the fleet's present state holds where E8's did not.** At 1,000 vehicles E8's ledger kept 93.3% of commitments; this one keeps 96.5% while promising more of what is delivered.
- **E8's comparison repeats on later days:** 88.6% against 84.3% at 1,000 vehicles, level at 500.
- **At 1,000 vehicles the floor, not the plan, is calling vehicles in:** 97.7% of the plan's calls. The gain over headroom there is measured with each rule's own power rule, and E11 separates the two.

## E10. A guard for when the forecast breaks

Registered 2026-10-04.

- **Question.** The controller trusts the forecast's upper bound. If the forecast goes wrong, does a guard that watches the bound notice in time and limit the damage, without raising false alarms when the forecast is sound?
- **The guard.** Each hour it compares the rides actually offered with the upper bound it was given for that hour. The bound is meant to be broken about one hour in twenty. If it is broken in half or more of the last 12 hours, control passes to the fixed-threshold rule, which uses no forecast. It passes back after at least 24 hours, once the bound is broken in a quarter of recent hours or fewer.
- **The fault.** From the start of day 8, every forecast handed to the controller is 33% of what the models said: a feed that has gone stale on a quiet day. The demand itself is untouched.
- **Days and runs.** 14 days from 13 May 2024; days 8 to 14 scored. 500 and 1,000 vehicles, three seeds (311 to 313). Five runs each: the controller with a sound forecast, with and without the guard; the controller with the fault, with and without the guard; and the threshold rule.
- **Bars.**
  1. No false alarm: with a sound forecast the guard never passes control away, at either size.
  2. Detection: with the fault, the guard passes control within 12 hours of its start, in every run.
  3. Damage limited: with the fault, the guarded controller serves at least as many rides as the unguarded one, to within 0.2 points, at both sizes.
- **Also reported.** What the fault costs the unguarded controller, and how the guarded one compares with running the threshold rule all along.
- **What a miss would mean.** For 1: the guard is too jumpy to leave switched on. For 2: it is too slow to matter. For 3: falling back does not help, either because the controller shrugs off a bad forecast by itself or because the fallback is worse than a misinformed controller.

### Result

Run 2026-10-08. **2 of 3 bars.** Numbers are in `data/derived/e10_guard.json`; reproduce with `depot-twin eval e10`.

| Rides served, days 8 to 14 | 500 vehicles | 1,000 vehicles |
|---|---|---|
| Controller, sound forecast | 100.0% | 88.7% |
| Controller, sound forecast, guarded | 100.0% | 88.7% |
| Controller, stale forecast | 100.0% | 88.7% |
| Controller, stale forecast, guarded | 100.0% | 87.4% |
| Threshold rule, with the controller's power rule | 100.0% | 88.9% |

No vehicle was stranded in any run.

| Bar | Result | |
|---|---|---|
| 1. No false alarm with a sound forecast | No run fell back | **Pass** |
| 2. Falls back within 12 hours of the fault | Every run, within 6 hours | **Pass** |
| 3. Guarded serves at least as many rides under the fault | 87.4% against 88.7% unguarded at 1,000; level at 500 | **Miss** |

What this says:

- **The guard works as a detector.** It never fired on a sound forecast, and it caught a stale one within six hours in every run.
- **The controller did not need it.** Handed forecasts a third of the truth, the unguarded controller served exactly as many rides as with sound ones. The guard then cost rides at 1,000 by switching rules mid-stream.
- **The last row is the one that matters.** A plain threshold rule, given the controller's way of sharing power, serves as many rides as the whole controller: 100.0% at 500 and 88.9% at 1,000. The forecast cannot matter much to rides if a rule that ignores it does as well.
- **Why a bad forecast cannot move the controller at 1,000.** On these same days E9 records that the low-battery floor made 97.7% of the plan's calls at that size. E11 takes the controller apart to say which part delivers its rides.

## E11. Taking the controller apart

Registered 2026-10-04, after E10.

- **Question.** E8 and E9 compared the heartbeat controller, with its own power rule, against simpler recall rules with a different one. Which part delivers the gain: how vehicles are called in, or how power is shared among those plugged in?
- **Grid.** Three ways of calling vehicles in (fixed threshold, headroom, heartbeat plan) crossed with two ways of sharing power (lowest charge first, which the simple rules used; in order of plugging in, which the heartbeat used). Every cell on the same days (from 13 May 2024), 500 and 1,000 vehicles, three seeds (321 to 323).
- **Reported for every cell.** Rides served; share of the fleet on the road in the busiest hours; variation of grid draw.
- **No bars.** This is an attribution, not a claim. What is written in advance is what each outcome would mean.
  - If the power rule carries the gain: the result of E8 and E9 is "feed vehicles in turn at full rate", and the plan, the forecasts behind it and the ledger have to justify themselves on grid smoothness and on being able to make a promise, not on rides.
  - If the plan carries it: E10's last row was a coincidence of that week.
  - If both matter: say how much each.

### Result

Run 2026-10-08. An attribution, no bars. Numbers are in `data/derived/e11_apart.json`; reproduce with `depot-twin eval e11`.

**The power rule carries the gain in rides. The plan does not.**

Rides served:

| Vehicles called in by | Power to lowest charge first | Power in order of plugging in |
|---|---|---|
| **1,000 vehicles** | | |
| Threshold | 82.9% | 88.8% |
| Headroom | 84.2% | 86.0% |
| Heartbeat plan | 85.6% | 88.6% |
| **500 vehicles** | | |
| Threshold | 100.0% | 100.0% |
| Headroom | 100.0% | 100.0% |
| Heartbeat plan | 100.0% | 100.0% |

The variation of grid draw at 500 vehicles came out at 0.41 and 0.25 for the threshold, 0.57 and 0.40 for headroom, and 0.22 and 0.21 for the heartbeat. No vehicle was stranded in any cell.

What this says:

- **At a site short of energy, in-order feeding lifts every rule:** by 5.9 points under a threshold, 3.0 under the plan and 1.9 under headroom.
- **With in-order feeding the plan adds no rides.** A plain threshold serves 88.8% at 1,000 vehicles and the full controller 88.6%. With lowest-charge-first the plan is 2.6 points ahead of the threshold, so its calling partly makes up for a poor power rule, and adds nothing to a good one.
- **This reframes E8 and E9.** The heartbeat's gain over headroom at 1,000 vehicles came from the power rule it shipped with.
- **Where energy is not short, nothing separates the cells.** Every one serves 100.0% at 500 vehicles.
- **Headroom is the weakest way to call vehicles in once power is fed in order:** 86.0% at 1,000, and the smallest share of the fleet on the road in the busiest hours at 500.
- **What the plan is left with.** A slightly smoother grid draw than a threshold with the same power rule, 0.21 against 0.25; more of the fleet on the road in the busiest hours at 500, 87.2% against 84.8%; and the ability to make and keep an hourly promise. Not rides. On the same days E9 records that the floor made 97.7% of the plan's calls at 1,000 vehicles.

Why lowest-charge-first loses is measured in the staffing study: site power goes unused while finished vehicles wait on chargers to be unplugged. Where a plan could still earn its place is money, which E12 tests.

## Growth study, second version

Run 2026-10-08. A study, no bars. Numbers are in `data/derived/growth_v2.json`; reproduce with `depot-twin eval growth-v2`.

The first growth study again, with each vehicle type's own energy use and demand replayed from 15 to 28 April 2024, the second week scored, three seeds. Two arms at every size: the headroom rule with power to the emptiest vehicle first, and the heartbeat controller with in-order feeding.

Rides served:

| Fleet | One feeder, headroom | One feeder, heartbeat | Two feeders, headroom | Two feeders, heartbeat |
|---|---|---|---|---|
| 400 | 100.0% | 100.0% | 100.0% | 100.0% |
| 600 | 100.0% | 100.0% | 100.0% | 100.0% |
| 700 | 99.6% | 99.9% | 100.0% | 100.0% |
| 800 | 95.6% | 98.0% | 100.0% | 100.0% |
| 1,000 | 82.8% | 87.6% | 100.0% | 100.0% |
| 1,200 | 71.7% | 75.8% | 100.0% | 100.0% |
| 1,500 | 58.6% | 62.1% | 97.9% | 99.2% |
| 2,000 | 45.7% | 46.8% | 83.0% | 87.6% |

No vehicle was stranded in any run.

- **One feeder carries 700 vehicles at 99% and 800 at 95%,** under either arm. The heartbeat arm is 2.4 points ahead at 800 and 4.7 at 1,000.
- **Two feeders carry 1,500 vehicles at 99% with the heartbeat arm** (99.2%) and 1,200 with headroom (97.9% at 1,500).
- **2,000 vehicles still do not fit:** 87.6% at best on two feeders.
- **The grid saturates before service breaks.** With the heartbeat arm the feeder runs at 93% of its usable power at 600 vehicles and 99.8% at 700, where 99.9% of rides are still served. From 800 up it is at its limit around the clock.
- **A 4 MWh battery makes no difference to the heartbeat arm at any size:** 99.9% at 700 and 87.6% at 1,000, with or without. A battery moves energy in time and adds none; with power fed in order there is no queue for it to relieve. Under headroom it is worth 2.6 points at 800 (98.2% against 95.6%) and about 2.5 at 1,000, and it moves neither capacity figure.

## E12. Does a plan that knows the price of energy earn its place?

Registered 2026-10-04.

- **Question.** E11 showed that the day-ahead plan adds no rides over a fixed threshold once power is shared in order. Energy at this site costs $0.36 per kWh from 4 pm to 9 pm and $0.13 to $0.15 the rest of the day. Can the plan move charging out of the expensive hours without losing rides, and does it take a plan to do that, or would a threshold that knows the clock do as well?
- **Arms.** All with in-order feeding.
  - Threshold: call in at 20%, release at 85%.
  - Clock-aware threshold: the same, but call in at 40% in the four hours before the peak and at 15% during it. No forecast, no plan.
  - Plan: the heartbeat controller as in E9.
  - Plan with prices: the same controller told the tariff. Its hourly program weighs fares against the cost of each hour's energy; in the four hours before the peak it also calls vehicles that would otherwise run down during it; during the peak it calls only vehicles under 15%.
  - Plan, clock only (reported, no bar): the plan with prices, with its hourly program unable to see them. It separates the steering by the clock from the program's own use of prices.
- **What development showed (18 to 31 March 2024, two seeds).** Putting the price in the hourly program alone moved nothing. Steering which vehicles are called before and during the peak moved a great deal. At 500 vehicles the plan with prices bought energy cheaper at unchanged service; the clock-aware threshold bought it cheaper still and lost rides. At 1,000 vehicles, with the site flat out, nothing could move, and the clock-aware threshold lost more rides.
- **Days.** 14 days from Monday 29 April 2024, the last unused part of the held-out block. Seven warm-up, seven scored. Five seeds, 401 to 405. 500 and 1,000 vehicles.
- **Bars, at 500 vehicles, plan with prices against the plain threshold.**
  1. Energy is at least 5% cheaper per kWh.
  2. Rides served are no more than 0.1 points below the threshold's.
  3. Fares less energy cost, per vehicle per day, is higher.
  4. No vehicle is stranded under the plan with prices, at either size.
- **Attribution, reported without a bar.** The plan with prices against the clock-aware threshold on fares less energy, at both sizes. If the clock-aware threshold matches it, the plan is still not needed.
- **What a miss would mean.** The plan has no case left at this site, and the depot should run a threshold with in-order feeding.

### Result

Run 2026-10-08. **4 of 4 bars.** Numbers are in `data/derived/e12_cost.json`; reproduce with `depot-twin eval e12`.

A fifth arm ran beside the four registered: the plan with its tariff-clock steering and an hourly program that cannot see prices.

| 500 vehicles | Threshold | Clock-aware threshold | Plan | Plan with prices | Plan, clock steering only |
|---|---|---|---|---|---|
| Rides served | 99.9% | 94.8% | 100.0% | 100.0% | 100.0% |
| Energy bought in the peak hours | 23.9% | 14.8% | 23.5% | 12.3% | 12.2% |
| Price paid per kWh | $0.1955 | $0.1759 | $0.1950 | $0.1716 | $0.1714 |
| Energy cost per vehicle per day | $18.90 | $16.08 | $19.09 | $16.74 | $16.72 |
| Fares less energy, per vehicle per day | $494.53 | $471.26 | $494.93 | $497.27 | $497.30 |
| Trips per visit | 17.7 | 16.2 | 15.9 | 16.0 | 16.0 |
| Share of the plan's calls made by the floor | | | 0.0% | 5.9% | 5.7% |

At 1,000 vehicles the site draws its limit around the clock, so no rule can move when energy is bought: every arm pays $0.190 per kWh. The three plan arms are identical there at 84.0% of rides, the threshold serves 84.2% and the clock-aware threshold 80.0%. At that size the floor, not the plan, is calling vehicles in: 97.4% of the plan's calls. No vehicle was stranded.

| Bar | Result | |
|---|---|---|
| 1. Energy at least 5% cheaper per kWh | 12.2% cheaper | **Pass** |
| 2. Rides no more than 0.1 points below the threshold | 0.1 points higher | **Pass** |
| 3. Fares less energy higher | $2.75 more per vehicle per day | **Pass** |
| 4. No vehicle stranded under the plan with prices | None, at either size | **Pass** |

What this says:

- **Told the tariff, the plan halves the energy bought in the peak hours and pays 12% less per kWh, with no loss of rides.** On 500 vehicles that is about $1,400 a day.
- **The saving is the clock steering, all of it.** The plan whose hourly program cannot see prices pays $0.1714 against $0.1716 and earns three cents a vehicle-day more. Putting the price in the program adds nothing. What moves energy is calling, before the peak, the vehicles that would otherwise run down during it, and holding calls during it.
- **It still takes the plan to steer safely.** A threshold that simply knows the clock pays 10% less per kWh and loses 5.1 points of rides doing it, $23.26 a vehicle a day worse than not trying. It pulls vehicles in before the peak whether or not the road can spare them. The plan paces the same idea by how many vehicles the road needs and how many chargers are free.
- **It only works with slack.** At a site drawing its limit all day there is no cheaper hour to move into.
- **The size of it.** $2.75 on $494.53 a vehicle a day is 0.6%, and energy is under 4% of fares at these prices. The plan is worth having. It is not what makes a depot work. The power rule from E11 is worth far more and costs nothing.

## Session length study

Run 2026-10-08. A study, no bars. Numbers are in `data/derived/session_length.json`; reproduce with `depot-twin eval session-length`.

How far does the case against short charging sessions depend on two things the depot does not have to accept: how far it sits from the riders, and how powerful its chargers are? The controller was run with slots of 20, 30, 45 and 60 minutes, at a drive of 5, 10 and 15 minutes each way, with 60 kW and 150 kW chargers, on the development days (from 18 March 2024), 500 and 1,000 vehicles, two seeds.

Rides served at 500 vehicles, with the energy per session in brackets:

| Drive each way | Chargers | 20 min slot | 30 min | 45 min | 60 min |
|---|---|---|---|---|---|
| 5 minutes | 60 kW | 63.0% (16 kWh) | 87.7% (26) | 100.0% (41) | 100.0% (55) |
| 15 minutes | 60 kW | 56.8% (16 kWh) | 82.7% (26) | 100.0% (41) | 100.0% (55) |
| 5 minutes | 150 kW | 100.0% (40 kWh) | 100.0% (65) | 100.0% (67) | 100.0% (67) |
| 15 minutes | 150 kW | 99.9% (40 kWh) | 100.0% (64) | 100.0% (68) | 100.0% (68) |

At 1,000 vehicles, with the site short of power, the 60-minute slot was best in every case: 86.9% to 89.2% of rides, against 53.6% to 84.0% with 20-minute slots. No vehicle was stranded.

What this says:

- **Distance is not what sinks short sessions.** Moving the depot from 15 minutes away to 5 lifts a 20-minute slot at 60 kW from 57% to 63%. Every visit also carries plugging in, unplugging and cleaning, whatever the drive.
- **Charger power is what rescues them.** At 150 kW a 20-minute slot delivers 40 kWh and serves 99.9% or more, as well as an hour at 60 kW does.
- **So the rule is about energy, not minutes.** A visit that delivers about 40 kWh serves all or nearly all rides; one that delivers 26 kWh loses 12 to 17 points; one that delivers 16 kWh loses 37 to 43. Fast chargers make a full visit a short one; slow ones make it a long one.
- **When the site is short of power, fewer and fuller visits win.** At 1,000 vehicles a 150 kW charger on a 20-minute slot delivers only 23 kWh, because the feeder cannot feed it any faster, and every extra visit is overhead.

These runs clean a vehicle on every visit. E22 measures what cleaning less often changes.

## Staffing study

Run 2026-10-08. A study, no bars. Numbers are in `data/derived/staffing.json`; reproduce with `depot-twin eval staffing`.

E11 found that in-order feeding serves more rides than lowest-charge-first at a site short of power. This measures why. A threshold rule was run with each power rule at 1,000 vehicles on one feeder, on the development days (14 days from 18 March 2024, the second week scored), seeds 31 and 32, with 25, 50, 100 and 200 people on the depot floor. The scenario has 25. Each run recorded where vehicles were at every step, and rides served is read from those steps: rides served over rides offered in the scored week.

| People | Power rule | Rides served | Grid power used | Vehicles between stations | Vehicles waiting for a charger |
|---|---|---|---|---|---|
| 25 | Emptiest first | 80.7% | 2,415 kW | 32.5 | 384 |
| 25 | In order | 87.2% | 2,612 kW | 2.7 | 330 |
| 50 | Emptiest first | 83.1% | 2,517 kW | 21.0 | 363 |
| 50 | In order | 87.2% | 2,612 kW | 2.7 | 330 |
| 100 | Emptiest first | 84.2% | 2,559 kW | 16.4 | 354 |
| 100 | In order | 87.2% | 2,612 kW | 2.7 | 330 |
| 200 | Emptiest first | 84.3% | 2,566 kW | 15.4 | 352 |
| 200 | In order | 87.2% | 2,612 kW | 2.7 | 330 |

"Between stations" counts vehicles at the depot that are not in the queue, not charging and not being cleaned: waiting for a person to plug them in or unplug them, being plugged or unplugged, or waiting for a bay.

What this says:

- **The loss is unused power.** In-order feeding draws 2,612 kW around the clock, all the site can use. Emptiest-first draws 7.5% less with the scenario's 25 people. At a site short of energy, rides follow energy: 7.5% less energy, 6.5 points fewer rides.
- **Why the power goes unused.** Feeding the emptiest first evens out the charge of every vehicle plugged in, so they reach their target together. Each then needs a person to unplug it, and the people are also cleaning. Finished vehicles stand on chargers, 32 at a time on average against 3 with in-order feeding, while several hundred wait in the queue.
- **More people recover a little over half of it.** From 25 to 100 people the gap closes from 6.5 points to 3.0. Past 100 it stops closing: 2.9 points with 200.
- **About three points remain however many people there are.** Emptiest-first still draws 1.7% less power with 200 people, with 15 vehicles between stations. Vehicles that finish together are unplugged and replaced together, and for those minutes their chargers draw nothing. This last part is read from the counts, not isolated by a further experiment.
- **In-order feeding does not need the people.** Its result is the same at every staffing level. It finishes vehicles one after another, so the work arrives one vehicle at a time.
- **What this says about E11.** The gain from in-order feeding at this site is between 3 and 6.5 points depending on how well staffed the depot is. A depot with automated connectors would see the low end.

## E13. Can a forecast be built for a place with no ride history?

Registered 2026-10-04.

- **Question.** Every forecast so far was trained on the history of the city it serves. A new site has none. Can demand be generated for it from other cities, a forecast trained on that, and its likely error stated in advance? The new site cannot answer this, so cities that do have data stand in for it: each is treated in turn as if it had no history.
- **Data.** Hourly pickups: New York ride-hail and yellow taxi by area (January 2023 to June 2026), Chicago ride-hail for the whole city (January 2025 to August 2026), San Francisco taxi by area (December 2022 to May 2024). Each series is labelled with a kind of place: core, inner, outer, airport or whole city.
- **Generated demand.** For a target series, from donor series in other cities only: a weekly profile mixed from donors of the same kind; the donors' holiday pattern and response to rain, applied to the target's own calendar and weather; week-long blocks of the donors' leftover variation; a slow drift in level; then counts drawn at a level picked at random over a wide range. The target's own rides are never used.
- **Model.** One XGBoost model per horizon (1, 6 and 24 hours) pooled over all donor series and the generated series, predicting the ratio to the same hour last week. No city identifier, no month, no temperature: only features that mean the same thing in every city. Trained only on donor data from before the target's test days.
- **Bounds.** A relative error plus counting noise. Sized on donor cities the model was not trained on (each donor city held out in turn), not on errors inside a city. Where only one donor city exists, one service is held out in its place.
- **Test days.** The last 60 days of each target city's series, scored on the whole-city series. Development used the 60 days before those, and never the test days.
- **Arms, per held-out city and horizon.**
  - Same hour last week, and the best of three naive rules.
  - In-city: the same model trained on the city's own history. What having history is worth.
  - Donors only.
  - Donors plus generated demand for the target. The arm the bars are on.
  - Generated demand only.
- **Bars.**
  1. In all three cities and at all three horizons, the donors-plus-generated model has lower error than the best naive rule.
  2. In at least 7 of the 9 cells its error is no more than 1.25 times the in-city model's.
  3. In all 9 cells the upper bound holds between 90% and 99% of the time (it is sized for 95%).
  4. The depot reaches the same answer on generated demand as on real days: for San Francisco, with demand generated from other cities and scaled to the same rides per day, rides served by a threshold with in-order feeding is within 1.5 points of the figure on real days (15 to 28 April 2024), at 500 and at 1,000 vehicles. Ten generated scenarios, three seeds.
- **Reported without a bar.** Whether generated demand adds anything over donors alone. How close the generated weekly profile, spread and persistence are to the real ones. The worst cell's error, which is the figure a new site will be quoted.
- **Known weaknesses, stated before the run.** Three cities, all dense and served by transit. For San Francisco the only donor city with earlier data is New York. Taxi and ride-hail records are trips served, not trips wanted. Nothing here tests the level of demand at a new site; the level is an input.
- **What development showed.** Three rounds on the development days set the method.
  - *The model is told the size of the place* (the log of last week's level), and every large donor is also trained on thinned to 300 and to 2,000 rides an hour. Without this, a model that had learned from San Francisco's 200 rides an hour distrusted last week's figure in New York, where it is precise.
  - *The generator does not carry a small donor's counting noise* to places of another size. With that noise left in, generated demand made the New York forecast much worse.
  - *Trust.* The forecast is last week's figure moved part of the way to the model's. How far is measured on donor cities the model was not trained on. Where the donors transfer badly to each other, the forecast stays near last week's figure. This costs accuracy where transfer would have been good, as it did for Chicago at one hour in development.
  - *Bounds are sized on donor series of the target's kind and nearest its size.*
  - *Added, reported without a bar:* the same scores with New York and Chicago thinned to 500 rides an hour, the scale of a depot.
  - *What development showed.* On the development days the donors-plus-generated arm matched or beat the best naive rule in every cell; one was an exact tie, so bar 1 may miss. Upper bounds ran at or past both edges of bar 3.
- **What a miss would mean.** On bar 1 or 2: a new site should run on last week's curve until it has a few weeks of its own rides, and the plan should not be offered at a site without history. On bar 3: the bounds cannot be trusted across cities and the guard from E10 becomes mandatory at a new site. On bar 4: generated demand is not fit for sizing a depot.

### Result

Run 2026-10-08. **1 of 4 bars.** Numbers are in `data/derived/e13_new_site.json`; reproduce with `depot-twin eval e13`.

Error as a share of rides, on each city's last 60 days, with the city never seen in training. In every cell the best naive rule is the same hour last week.

| Held-out city | Ahead | Same hour last week | Trained on its own history | Donors only | Donors plus generated |
|---|---|---|---|---|---|
| New York | 1 h | 8.21% | 4.35% | 7.69% | 7.62% |
| | 6 h | 8.23% | 5.26% | 7.90% | 8.23% |
| | 24 h | 8.09% | 6.04% | 8.09% | 8.09% |
| Chicago | 1 h | 6.44% | 4.06% | 5.15% | 5.39% |
| | 6 h | 6.43% | 4.83% | 5.68% | 5.69% |
| | 24 h | 6.34% | 7.68% | 5.90% | 6.09% |
| San Francisco | 1 h | 14.90% | 10.77% | 11.16% | 11.44% |
| | 6 h | 14.90% | 14.89% | 13.15% | 13.20% |
| | 24 h | 14.94% | 12.99% | 13.53% | 13.94% |

| Bar | Result | |
|---|---|---|
| 1. Beats the best naive rule in all 9 cells | 7 of 9, by 0.25 to 3.46 points; New York at six and 24 hours is level with last week's figure | **Miss** |
| 2. Within 1.25 times the in-city model in 7 of 9 | 5 of 9; New York is 1.34 to 1.75 times, Chicago at one hour 1.33 times | **Miss** |
| 3. Upper bound holds 90% to 99% of the time in all 9 | New York about 97% in all three; Chicago 98.9% to 99.1%, over the top edge in two cells; San Francisco 92.4%, 88.0% and 86.4% | **Miss** |
| 4. Depot on generated demand within 1.5 points of real days | 500 vehicles: 100.0% against 100.0%. 1,000 vehicles: 88.0% against 88.2% | **Pass** |

Reported without a bar:

- **Generated demand does not help the forecast.** Beside donors alone it lowered error in one cell, left one level and raised it in seven, by up to 0.4 points. Donors alone beat last week's figure in eight cells and tie in the ninth.
- **Generated demand alone is not enough.** A model trained only on it is worse than last week's figure in New York, 9.1% to 13.0%, and in San Francisco at six and 24 hours.
- **At a depot's scale**, with New York and Chicago thinned to 500 rides an hour, the forecast has 8.1% to 9.0% error in New York and 6.6% to 7.6% in Chicago, against 9.7% to 9.8% and 8.1% to 8.3% for last week's figure. A model trained on the city's own thinned history is 0.8 to 2.4 points better.
- **How like the real thing generated demand is.** Its weekly shape is off by 13% to 21% of the average hour. It varies more than the real series in New York and Chicago, 0.23 and 0.28 against 0.13 and 0.16 in log terms, and about as much in San Francisco.
- **The figure a new site is quoted**, against last week's curve on the same days: 77% to 93% of its error an hour ahead, 88% to 100% at six and 24 hours. The worst cell is New York six hours ahead, 8.23% against 8.23%.

What this says:

- **A forecast built without the place's own history beats last week's curve in seven cells, by most an hour ahead, and not at all in New York beyond the hour.** In New York at six and 24 hours the donors transfer so poorly that the forecast is given no trust and is last week's figure exactly. Against a model trained on the place's own rides it is ahead in two cells and behind in seven. A new site should run on last week's curve until it has a few weeks of its own rides, as the registration said a miss would mean.
- **Bar 3: the bounds cannot be trusted across cities.** For San Francisco the only earlier data was New York's, so the bounds were sized between New York's two services, which share a city and its shocks, and they came out too narrow. With two donor cities they came out on the wide side. The guard from E10 is mandatory at a new site.
- **Bar 4: the depot reaches the same answer on generated demand.** At 1,000 vehicles the real fortnight's 88.2% sits inside the ten scenarios' range, 86.2% to 90.7%, 0.2 points from their mean. Generated demand is fit for sizing a depot even though it does not improve the forecast.
- **Limits.** Three cities, all dense. The level of demand at a new site is still an input.

## E14. Do the power-rule findings hold on fresh days from another city, and does the textbook rule beat in-order feeding?

Registered 2026-10-05.

- **Question.** Three things rest on thin evidence. E11 found that in-order feeding beats "emptiest first" at a site short of power; the staffing study explained why and said the gain shrinks with more people, but it was a study on development days. And scheduling theory names a rule this project never tried: feed the vehicle with the least energy still to take.
- **Demand.** Real ride-hail days from Chicago: 14 days from Monday 2 March 2026, hourly counts thinned to a depot's scale and spread over five-minute steps. No depot run has used Chicago before. Seven days warm-up, seven scored.
- **Arms.** A fixed threshold (call in at 20%, release at 85%) with each of three power rules: emptiest first, in order of plugging in, least energy left first. 1,000 vehicles on one feeder. 25 people (the scenario) and 100. Five seeds, 601 to 605.
- **What development showed (San Francisco, 18 to 31 March 2024, two seeds).** In-order feeding served more rides than emptiest first, by less with 100 people than with 25. Least-left matched in-order feeding.
- **Bars.**
  1. With 25 people, in-order feeding serves at least 2 points more rides than emptiest first.
  2. With 100 people the gap is smaller than with 25, and still above zero.
  3. With 25 people, emptiest first leaves at least 4% of the site's power unused and in-order feeding less than 1%.
  4. Least-left serves no fewer rides than in-order feeding, to within a tenth of a point, at both staffing levels.
- **What a miss would mean.** On 1 to 3: the power-rule finding belongs to San Francisco's days and the headline claim must be withdrawn or narrowed. On 4: the textbook rule does not carry over to a depot, and the reason needs finding.

### Result

Run 2026-10-08. **4 of 4 bars.** Numbers are in `data/derived/e14_power_rules.json`; reproduce with `depot-twin eval e14`.

| Power rule | People | Rides served | Usable site power drawn | Vehicles between stations |
|---|---|---|---|---|
| Emptiest first | 25 | 78.0% | 92.4% | 32.9 |
| Emptiest first | 100 | 81.9% | 98.0% | 16.6 |
| In order of plugging in | 25 or 100 | 85.3% | 100.0% | 2.6 |
| Least energy left first | 25 or 100 | 85.4% | 100.0% | 2.7 |

No vehicle was stranded in any run.

| Bar | Result | |
|---|---|---|
| 1. With 25 people, in-order serves at least 2 points more than emptiest first | 7.3 points | **Pass** |
| 2. With 100 people the gap is smaller and still above zero | 3.4 points | **Pass** |
| 3. With 25 people, emptiest first leaves at least 4% of power unused and in-order under 1% | 7.6% and 0.02% | **Pass** |
| 4. Least-left serves no fewer rides than in-order, to a tenth of a point | 0.1 points more, at both staffing levels | **Pass** |

What this says:

- **The finding holds on another city's days.** In-order feeding serves 7.3 points more rides than emptiest first with 25 people and 3.4 points more with 100. On San Francisco's days the staffing study measures 6.5 and 3.0.
- **The mechanism holds.** Emptiest first leaves 7.6% of the site's usable power undrawn with 25 people. In-order feeding draws all of it.
- **The textbook rule ties with in-order feeding:** 85.4% against 85.3%. At a site short of energy, rides follow energy delivered, and both rules deliver all of it. Which vehicle gets full power first does not matter once none is wasted.
- **So the rule to state is broader than "in order".** Feed at full rate in any order that finishes vehicles one after another. Emptiest first is the one natural choice that breaks it.

## Sensitivity study

Run 2026-10-08. A study, no bars. Numbers are in `data/derived/sensitivity.json`; reproduce with `depot-twin eval sensitivity`.

Several inputs sit at the edge of what is public, as recorded in `docs/RELATED_WORK.md`. This study moves each one, alone, and reads rides served on one feeder with a threshold and in-order feeding, on the development days (14 days from 18 March 2024, the second week scored), seeds 31 and 32. Energy per mile and depot visits per day are read at 700 vehicles.

| Input moved | 600 vehicles | 700 | 800 | 1,000 | Energy per mile | Depot visits per day |
|---|---|---|---|---|---|---|
| As modelled (25 rides a vehicle a day) | 100.0% | 100.0% | 98.7% | 87.2% | 0.53 kWh | 1.32 |
| 21.5 rides a vehicle | 100.0% | 100.0% | 100.0% | 95.3% | 0.56 kWh | 1.29 |
| 18 rides a vehicle | 100.0% | 100.0% | 100.0% | 99.9% | 0.60 kWh | 1.26 |
| Energy per mile 10% lower | 100.0% | 100.0% | 100.0% | 93.6% | 0.49 kWh | 1.23 |
| Energy per mile 10% higher | 99.9% | 99.1% | 93.9% | 81.5% | 0.57 kWh | 1.33 |
| Called in at 40% charge | 99.4% | 98.7% | 95.2% | 84.9% | 0.52 kWh | 1.85 |
| Called in at 55% charge | 86.8% | 87.0% | 88.3% | 81.1% | 0.51 kWh | 2.35 |
| Twice the people | 100.0% | 100.0% | 98.7% | 87.2% | 0.53 kWh | 1.32 |

What this says:

- **The site's capacity is a number of rides, not of vehicles.** On these days, at 25 rides a vehicle, 700 vehicles serve 100.0% and 800 serve 98.7%, just under the 99% floor. At 21.5 rides, 800 vehicles serve 100.0%. At 18 rides, 1,000 serve 99.9%. Public figures put a vehicle at 18 to 24 rides a day, so a capacity quoted at 25 rides is the cautious end.
- **Energy per mile moves the limit by about a fleet step for every 10%.** At 800 vehicles the depot serves 100.0% of rides with 10% less energy per mile and 93.9% with 10% more; with 10% more, 700 vehicles sit at the floor (99.1%).
- **More depot visits cost rides when every visit is cleaned.** Calling vehicles in at 40% gives 1.9 visits a day and costs 1.3 points at 700 vehicles. Calling them in at 55% gives 2.4 visits and costs 13 points. E22 finds that cleaning is the cost: at 500 vehicles three visits a day lose nothing with a wash every fourth visit, and serve 99.7% of rides with one every second.
- **People do not matter once power is fed in order.** Doubling them changes nothing, as the staffing study found.
- These runs use a threshold. The day-ahead plan is not part of this study.

## E15. Is the worst generated scenario a safe reading of a constrained depot?

Registered 2026-10-05.

- **Question.** In E13 the depot at 1,000 vehicles served 88.2% of rides on San Francisco's real days and 88.0% on generated demand, inside the ten generated scenarios' range of 86.2% to 90.7%: the average of generated scenarios is close to the real figure, and the scenarios spread four points around it. A constrained site is safer read from the worst scenario than from the average. Is that safe in other cities?
- **Demand.** Chicago and New York ride-hail, each for 14 days from Monday 2 March 2026, thinned to a depot's scale: the real fortnight, and ten fortnights generated for the city from the other cities only. Seven days warm-up, seven scored.
- **Arms.** 1,000 vehicles on one feeder, a fixed threshold with in-order feeding. Three seeds, 701 to 703.
- **Bars, one per city.** Rides served on the real fortnight are no more than half a point below the worst of the ten generated scenarios.
- **Reported without a bar.** The gap between the real fortnight and the average generated one.
- **No development was possible** without using the days, so the generator is as E13 left it. San Francisco's result is the only prior evidence: its real figure, 88.2%, sits two points above its worst generated scenario, 86.2%.
- **What a miss would mean.** Generated demand cannot bound a constrained site's capacity even at its worst scenario, and the generator needs harder weeks before a new site's capacity is quoted at all.

### Result

Run 2026-10-08. **2 of 2 bars.** Numbers are in `data/derived/e15_worst_scenario.json`; reproduce with `depot-twin eval e15`.

Rides served, 1,000 vehicles on one feeder:

| City | Real fortnight | Generated, average of ten | Generated, worst | Generated, best |
|---|---|---|---|---|
| Chicago | 85.3% | 89.2% | 82.4% | 96.7% |
| New York | 91.2% | 92.2% | 88.4% | 96.9% |

| Bar | Result | |
|---|---|---|
| Chicago: real no more than half a point below the worst generated scenario | 2.9 points above it | **Pass** |
| New York: the same | 2.8 points above it | **Pass** |

What this says:

- **The worst scenario is a safe reading.** In both cities the real fortnight lands almost three points above the worst of ten generated ones.
- **The average is not.** It is 3.9 points kinder than Chicago's real days and 1.0 points kinder than New York's.
- **Shape matters as much as level.** The same depot, fleet and rides per day serves 91% on New York's days and 85% on Chicago's. A site's kind of place is a first-order input to its capacity.
- **The spread is wide.** Ten generated fortnights for one city run from 82% to 97% of rides served at this size. That is what not knowing the place costs.
- **Rule for a new site.** Generate ten scenarios. Quote the worst for capacity, and quote the spread beside it.
- **Limit.** Two cities are checked here, once each. The generator's typical weeks are kinder than the real ones, and the rule above works around that without changing the generator.

## First-hour forecast study

The plan has no model for the hour already under way: its figure is last week's rides for that hour, adjusted by what the one-hour model says about the hour after. This study trains a fourth model for that hour, exactly as the other three, and asks two things: how much better the forecast is over the four replay windows (56 days), and whether the plan does better with it, on E9's days and, told the tariff, on E12's days, at 500 and 1,000 vehicles on seeds 801 to 803. Every window has been used before, so nothing here is a test.


Run 2026-10-08. A study, no bars. Numbers are in `data/derived/first_hour.json`; reproduce with `depot-twin eval first-hour`.

The forecast of the hour under way, over the four windows:

| | Error | Upper bound held |
|---|---|---|
| Interpolated from the one-hour model | 14.15% | 89.8% |
| Its own model | 9.18% | 96.0% |

The plan:

| Arm | Fleet | Forecast of the first hour | Rides served | Promises kept | Share of deliveries promised | Energy, per kWh |
|---|---|---|---|---|---|---|
| Plan | 500 | Interpolated | 100.0% | 97.6% | 94.2% | |
| Plan | 500 | Own model | 100.0% | 97.6% | 95.6% | |
| Plan | 1,000 | Interpolated | 88.7% | 95.8% | 97.3% | |
| Plan | 1,000 | Own model | 88.7% | 95.8% | 97.3% | |
| Plan with prices | 500 | Interpolated | 100.0% | | | $0.1719 |
| Plan with prices | 500 | Own model | 100.0% | | | $0.1695 |
| Plan with prices | 1,000 | Interpolated | 84.05% | | | $0.1899 |
| Plan with prices | 1,000 | Own model | 84.05% | | | $0.1899 |

No vehicle was stranded in any run.

What this says:

- **The forecast is much better.** About a third less error, and a bound that holds 96.0% of the time where the interpolated one holds 89.8%, short of the 95% it is sized for.
- **The plan does not notice.** Rides served and promises kept come out the same with either forecast, in every arm. At 1,000 vehicles nothing moves at all: the site is flat out, so the plan has no choice to make.
- **What moves is small and at 500 vehicles.** The plan with prices buys energy 1.4% cheaper, worth $0.24 a vehicle a day, and the plain plan commits to a little more of what it delivers, 95.6% against 94.2%.
- **This agrees with E10 and E11.** The plan's decisions at this depot are set by energy and by the peak, not by the fine detail of the next hour's rides.
- **What is done with it.** The model is kept as an option, the `now:` windows in the runner, which is the right choice for a live depot where the guard watches that bound. The registered tests run on the interpolated figure.

## E16. What is a forecast worth to the plan, and does that depend on what binds?

Registered 2026-10-05. Days: the `sf_e8` window (15 to 28 April 2024). It has been used by E8 and the workbench, so this is a prospective hypothesis on days already seen, and is labelled as such; the hypothesis itself was written before any of these runs.

- **Question.** The workbench found the plan's results unchanged by the forecast at this depot. A sharper claim follows from it: the value of forecast accuracy depends on which constraint binds. Energy bound: no value. Vehicles bound: value. This test looks for both regimes on the same days.
- **Arms**, each the price-aware plan fed a different forecast: *perfect foresight* (the rides that came, as forecast and bound); *the model* (the reference forecast); *last week's curve* (no model, with a bound sized the same way); *a broken feed* (the model's forecast cut to a third from the second week, unwatched).
- **Regimes**, all on one feeder with in-order feeding, three seeds (1001 to 1003):
  - *Slack:* 500 vehicles at 25 rides a vehicle a day.
  - *Edge:* 700 vehicles at 25.
  - *Energy bound:* 1,000 vehicles at 25.
  - *Vehicles bound:* 500 vehicles at 32 rides a vehicle a day, so that at the peak every vehicle on the road is busy and energy is not short.
- **Measures.** Rides served; fares less energy cost per vehicle-day; energy per kWh; promises kept; vehicles held in reserve for the bound; peak grid draw. *Regret* is perfect foresight's figure less an arm's, on rides and on money.
- **Bars.**
  1. Energy bound: rides served differ by less than 0.5 points across all four arms.
  2. Vehicles bound: perfect foresight serves at least 1 point more rides than last week's curve, and the model recovers at least half of that gap.
  3. The model's regret on fares less energy is at most 2% of perfect foresight's figure in every regime.
  4. The broken feed loses more rides against perfect foresight in the vehicles-bound regime than in the energy-bound one.
- **What a miss would mean.** On 1: the forecast does matter where we said it did not, and the workbench's conclusion must be withdrawn. On 2: either forecast quality does not matter even where vehicles bind, and forecasting should stop being a priority for this depot, or the model is far from perfect foresight and has room to earn. On 3: the plan is leaving money on the table that a better forecast would find. On 4: a broken feed does uniform damage, and the guard matters everywhere.

### Result

Run 2026-10-08. **3 of 4 bars.** Numbers are in `data/derived/e16_regret.json`; reproduce with `depot-twin eval e16`.

Rides served, second week, three seeds:

| Regime | Perfect foresight | The model | Last week's curve | Broken feed |
|---|---|---|---|---|
| Slack (500 at 25 rides) | 100.00% | 100.00% | 100.00% | 100.00% |
| Edge (700 at 25) | 99.86% | 99.86% | 99.86% | 99.86% |
| Energy bound (1,000 at 25) | 87.71% | 87.71% | 87.71% | 87.71% |
| Vehicles bound (500 at 32) | 99.70% | 99.53% | 99.53% | 99.56% |

Vehicles held in reserve for the bound came to 50, 69, 99 and 63 by regime under the model; 64, 90, 128 and 82 under last week's curve; and none under perfect foresight. Promises were kept in 96.4% to 98.2% of hours in every arm. No vehicle was stranded.

| Bar | Result | |
|---|---|---|
| 1. Energy bound: rides within 0.5 points across arms | Identical to four decimals | **Pass** |
| 2. Vehicles bound: foresight worth 1 point over last week, model recovers half | Foresight is worth 0.17 points; the model recovers none of it | **Miss** |
| 3. Model's money regret at most 2% everywhere | At most 0.12%, $0.71 a vehicle-day | **Pass** |
| 4. Broken feed hurts more where vehicles bind | 0.14 points there, nothing where energy binds | **Pass** |

What this says:

- **Where energy binds, and at the edge, the forecast is worth exactly nothing.** All four arms serve the same rides and earn the same money.
- **Where vehicles bind, perfect foresight is worth a sixth of a point, and nothing short of it is worth anything.** The model, last week's curve and a feed cut to a third land within 0.03 points of each other. The hypothesis holds in direction and fails in size.
- **A forecast's value at this depot is a reserve, not rides.** The bound decides how many vehicles the plan keeps on the road for safety. The model's bound asks for 50 to 99 vehicles and last week's curve for 64 to 128. That is where a better forecast shows.
- **Money follows rides.** The model's regret against perfect foresight is at most 0.12% of fares less energy.
- **What is decided.** Forecast error is not a priority for this depot's results. The forecast work that remains is justified by the bound, meaning calibration and sharpness, which set the reserve, and by sites with no history.

## E17. Do the model fixes improve the forecast's bound, and does that hold on days held back for it?

Registered 2026-10-05.

- **Question.** E16 settled what a forecast is for at this depot: its bound sets the vehicles held in reserve. The workbench named four fixes to the way the forecast is built. Do they make the bound tighter at the same reliability, and the forecast more accurate, on days held back for the purpose?
- **Arms**, each one change from the reference, and one with all of them:
  - *Reference:* ratio to the same hour last week; trees stopped on one block; a symmetric bound sized on the calibration block.
  - *Steadier denominator:* ratio to the mean of that hour over the last four weeks.
  - *Rolling-origin stopping:* the number of trees chosen on four expanding folds of the training block, then refit.
  - *Normalized counts:* the fair form of a count target: rides divided by the trailing four-week level, scale restored afterwards.
  - *Calibrated quantile bounds:* a 95th-percentile model for the bound, corrected on the calibration block by time of day.
  - *Bagging:* five models on different seeds and row samples, averaged.
  - *All of them* (with the ratio target).
- **Development.** San Francisco, hourly, scored on its forecast holdout. Development evidence only: those days have been inspected before.
- **Confirmation.** Chicago and New York, thinned to a depot's volume (500 rides an hour), on the reserved windows 5 January to 1 March 2026, with models trained only on days before them. Each figure is the mean over six draws of the thinning, and the draws that agree with the mean are counted.
- **Measures.** Error one hour ahead (and at 6 and 24); bound coverage (sized for 95%); sharpness, as the vehicles a 500-vehicle fleet would hold in reserve for the bound; paired-day differences from the reference with a 90% block-bootstrap interval (weeks as blocks).
- **Bars, on the confirmation windows, the all-fixes arm against the reference.**
  1. Lower error one hour ahead in both cities, with the paired-day interval excluding zero in both.
  2. Coverage between 93% and 97% in both cities.
  3. Fewer vehicles held in reserve in both cities, at coverage no lower than the reference's.
  4. Lower error at six and 24 hours ahead as well, in both cities.
- **Reported without a bar.** Each single fix on its own; the normalized-count arm against the ratio arm.
- **What a miss would mean.** On 1 or 4: the fixes are San Francisco's, and the reference stands. On 2 or 3: the bound is not better in the way that matters to the plan, and the first-hour study's guard rule stays mandatory.
- **What development showed, on San Francisco.** The calibrated quantile bound was no better than the symmetric bound at any horizon (lower coverage and a wider bound), while the other three fixes each helped. The all-fixes arm therefore keeps the symmetric bound; the quantile bound stays as a single-fix arm, reported.

### Result

Run 2026-10-08. **0 of 4 bars.** Numbers are in `data/derived/e17_fixes.json`; reproduce with `depot-twin eval e17`.

Each city is thinned to a depot's scale by keeping rides at random, and every figure is the mean over six draws of that thinning (seeds 17 to 22). The models are trained on every hour of the day. Below: error one hour ahead, bound coverage and vehicles held in reserve (fleet of 500). "Error" is the aggregate figure, rides missed over rides that came. The paired-day difference is the mean of the day-by-day differences from the reference, which weighs quiet days as much as busy ones, with its 90% block-bootstrap interval; the two do not subtract to each other. The last column counts the draws in which the arm's error was below the reference's.

| City | Arm | Error | Same hour last week | Coverage | Reserve | Mean paired-day difference (90% interval) | Draws lower, of 6 |
|---|---|---|---|---|---|---|---|
| Chicago | Reference | 7.95% | 12.60% | 96.0% | 38.2 | | |
| Chicago | Steadier denominator | 8.08% | | 93.7% | 32.2 | +0.06 points (-0.51 to +0.93) | 0 |
| Chicago | Rolling stopping | 8.07% | | 95.7% | 37.8 | +0.15 (+0.06 to +0.19) | 0 |
| Chicago | Normalized counts | 7.86% | | 95.5% | 36.7 | -0.11 (-0.31 to +0.12) | 6 |
| Chicago | Quantile bound | 7.95% | | 94.7% | 39.7 | same point forecast | |
| Chicago | Bagging | 7.88% | | 95.9% | 37.5 | -0.07 (-0.19 to -0.03) | 5 |
| Chicago | All three fixes | 8.19% | | 93.5% | 32.1 | +0.19 (-0.42 to +1.11) | 1 |
| New York | Reference | 9.53% | 16.11% | 93.1% | 34.4 | | |
| New York | Steadier denominator | 8.37% | | 92.1% | 28.9 | -1.48 (-3.19 to +0.12) | 5 |
| New York | Rolling stopping | 9.52% | | 93.0% | 34.2 | -0.01 (-0.04 to +0.02) | 4 |
| New York | Normalized counts | 8.60% | | 92.9% | 31.6 | -0.80 (-2.40 to +0.99) | 4 |
| New York | Quantile bound | 9.53% | | 90.8% | 35.1 | same point forecast | |
| New York | Bagging | 9.15% | | 93.0% | 33.6 | -0.46 (-0.90 to -0.05) | 5 |
| New York | All three fixes | 8.43% | | 91.8% | 28.8 | -1.37 (-3.04 to +0.19) | 5 |

At six and 24 hours the all-fixes arm has 11.07% and 12.66% error in New York against the reference's 12.23% and 13.80%, lower in six and five draws of six. In Chicago it has 9.78% and 10.05% against 8.16% and 8.77%, lower in no draw.

| Bar | Result | |
|---|---|---|
| 1. Lower error at 1 h in both cities, intervals excluding zero | New York lower, in 5 draws of 6, with an interval that reaches +0.19; Chicago higher, lower in 1 draw of 6 | **Miss** |
| 2. Coverage 93% to 97% in both | Chicago 93.5%; New York 91.8% | **Miss** |
| 3. Fewer reserve vehicles at no lower coverage, both cities | Six fewer vehicles in each city, and coverage fell in each | **Miss** |
| 4. Lower error at 6 and 24 h in both | New York yes; Chicago no | **Miss** |

What this says:

- **The combined recipe helps in New York and not in Chicago.** It takes about a point off the error in New York at every horizon and adds 0.2 to 1.6 points in Chicago. New York's spread between draws, and its wide intervals, come from two storm days (25 January and 23 February 2026, rides at 46% and 23% of normal) and their echo a week later through the ratio target, not from the thinning draw. The reference stands as the default.
- **The steadier denominator buys sharpness and pays for it in coverage.** On its own it holds 32.2 vehicles against 38.2 in Chicago and 28.9 against 34.4 in New York, with about 2 points and 1 point less coverage. The combined recipe's smaller reserve is this fix.
- **Bagging is the one fix whose interval excludes zero in both cities**, and it is small: 0.07 points of error in Chicago and 0.38 in New York, lower in five draws of six in each.
- **Normalized counts are not settled either way.** An hour ahead they have lower error in both cities, in six draws of six in Chicago and four in New York, with intervals that include zero. At six and 24 hours they are worse in Chicago and better in New York.
- **Coverage at depot volume runs under 95% in New York for every arm**, 90.8% to 93.1%, where Chicago's reference holds 96.0%. No recipe here closes that.
- **The quantile bound holds less often and asks for more vehicles** than the symmetric bound in both cities.

## E18. How cheaply can the fleet buy a required level of demand certainty?

Registered 2026-10-05, after E16 and E17. The question is theirs: E16 found that a forecast's value at this depot is the reserve its bound asks of the fleet; E17 found that fixes to the point forecast move error more than they move the bound, and that the bound holds under 95% at depot volume in New York however the point forecast is built.

- **Question.** At a required reliability, which forecasting architecture asks the fleet to hold the fewest vehicles in reserve? The point forecast and the uncertainty estimate are separated and judged separately.
- **The measure.** The reserve–coverage frontier: for required coverage at 29 levels from 85% to 99%, the bound is sized on the calibration block at that level and the vehicles held in reserve and the coverage achieved are read on the test days. Arms are compared at matched *achieved* coverage, by interpolation on their frontiers, never at matched nominal coverage. The headline is reserve at 95% achieved.
- **Arms.**
  - *A, reference:* the reference point forecast with its symmetric bound, which grows with the square root of the forecast.
  - *B, calibration only:* the same point forecast with a volume-aware bound, a relative part and a counting part combined in quadrature, both sized on the calibration block. This is the form the cross-city model already uses.
  - *C, pretrained model:* Chronos-2 (Amazon, Apache 2.0) zero-shot as the point forecast, with the same bound as B sized the same way. Its version is pinned by model file and commit.
  - *D, ensemble:* the mean of the reference and Chronos-2 point forecasts, with the same bound as B.
  - Reported beside them: perfect foresight (no reserve) and last week's curve with the B bound.
- **Where.** *Exploratory, labelled as a second look:* Chicago and New York ride-hail on the E17 windows, which E17 opened once. *Confirmation:* New York yellow taxi, thinned to 500 rides an hour, 5 January to 1 March 2026, trained on days before; a series no forecast has ever been scored on. New York series appear in public pretraining corpora, so any Chronos-2 figure in New York is an engineering result about an available component, not a zero-shot claim; Chicago, whose series begins in 2025, is the cleaner read for that claim.
- **Bars, on the confirmation series, reserve at 95% achieved coverage.**
  1. B holds fewer vehicles than A.
  2. The best of C and D holds no more than B plus one vehicle, or fewer (a pretrained point forecast does not make the bound worse).
  3. At least one arm reaches 95% achieved coverage with a bound sized for 95% on the calibration block, within one point (the calibration carries from the calibration block to the test days).
  4. Reported, no bar: whether any arm holds fewer than B by more than two vehicles. If none does, the finding is that the bound, not the point forecast, was the problem.
- **After this, the forecast work stops**, whatever the result. The remaining open items are in the roadmap.
- **What a miss would mean.** On 1: the symmetric bound is adequate and the under-coverage has another cause (the calibration block itself). On 2: the pretrained model's errors have a shape the bound cannot absorb, and it should not be used for the bound. On 3: bounds do not carry from the calibration block to new days at this volume, and the guard must be sized on live days.

### Result

Run 2026-10-08. **2 of 3 bars.** Numbers, frontiers and the pinned versions are in `data/derived/e18_reserve.json`; reproduce with `depot-twin eval e18`. Chronos-2 is at commit `29ec376`, `chronos-forecasting` 2.3.2, context 2,048 hours, no covariates.

Each series is thinned to 500 rides an hour by keeping rides at random, and every figure is the mean over three draws of that thinning (seeds 18 to 20). The trained models see every hour of the day. Each arm's frontier is read on 29 reliability levels, 85% to 99%, and arms are compared at matched achieved coverage, never nominal.

The confirmation series is New York yellow taxi, forecast one hour ahead:

| Arm | Point forecast | Bound | Error (aggregate) | Coverage at nominal 95% | Reserve at 95% achieved |
|---|---|---|---|---|---|
| A | Reference trees | Symmetric | 9.64% | 94.6% | 40.7 vehicles |
| B | Reference trees | Volume-aware | 9.64% | 95.0% | 52.8 |
| C | Chronos-2 | Volume-aware | 7.65% | 96.4% | 35.7 |
| D | Mean of the two | Volume-aware | 8.14% | 96.3% | 37.4 |
| Last week's curve | | Volume-aware | 17.49% | 93.0% | 135.6 |

At six and 24 hours on the same series Chronos-2 holds 47.9 and 54.5 vehicles against the reference's 57.0 and 59.4.

Exploratory, a second look at E17's window, one hour ahead, arm A against arm C:

| Series | Reference trees, error | Reserve | Chronos-2, error | Reserve |
|---|---|---|---|---|
| Chicago ride-hail | 8.02% | 35.3 | 6.47% | 26.3 |
| New York ride-hail | 10.09% | 40.9 | 6.16% | 26.7 |

New York ride-hail's window holds two storm days (25 January and 23 February 2026, rides at 46% and 23% of normal). They and their echo a week later through the ratio target, not the thinning draw, are what spreads its draws.

| Bar | Result | |
|---|---|---|
| 1. The volume-aware bound holds fewer vehicles than the symmetric one at 95% achieved | More: 52.8 against 40.7 | **Miss** |
| 2. The best pretrained arm holds no more than the calibration arm plus one | 35.7 against 52.8 | **Pass** |
| 3. Some arm reaches 95% within a point at nominal 95% | A 94.6% and B 95.0%; C and D hold 96.4% and 96.3% | **Pass** |
| Reported: any arm beats the calibration arm by more than two vehicles | Chronos-2 by 17.1; the ensemble by 15.4 | |

What this says:

- **The volume-aware bound does not win the reserve.** It holds 12 more vehicles than the symmetric bound at the same achieved coverage on the confirmation series, and more in both exploratory series as well. E17 pointed at the bound as the place to cut the reserve; here the reserve fell only where the point forecast got better. That rules out this bound. It does not show that no bound could do better.
- **The size of the pretrained model's advantage, on the confirmation series:** 7.65% error against 9.64% for the trees trained on this city, and 35.7 vehicles held against 40.7 at 95% achieved coverage, 5.0 fewer. It used no covariates and no training here.
- **Which claim each series supports.** New York taxi data is in the pretrained model's public training corpora, so the New York figures show that an available component helps this system, not that a pretrained model transfers zero-shot. Only Chicago supports a zero-shot reading, and that look is exploratory: 6.47% against 8.02%, and 26.3 vehicles against 35.3.
- **The bounds carry from the calibration block.** Sized for 95%, the reference's two bounds hold 94.6% and 95.0% on the test days. The pretrained arms hold a little over, 96.3% to 96.4%, which is why arms are compared at achieved coverage.
- **The ensemble sits between its two parts** at 8.14% and 37.4 vehicles. There is no case for keeping the trained model inside an ensemble at one hour.
- **What is decided.** The forecast work stops here, as registered. The trained trees remain the controlled reference: locally trained and reproducible from public data. Chronos-2 is the preferred pretrained candidate where its dependency and its provenance are acceptable. No change of default is claimed.

## E19. Where is the sweet spot, and what binds on either side of it?

Registered 2026-10-05. The fortnight is the `sf_e8` window (15 to 28 April 2024, the second week scored), used before by E8, E16 and the workbench; as with E16, the hypotheses are prospective and the days are not.

- **Question.** With every component settled, the question the project began with: across fleet size, feeders, chargers and the way vehicles are called in, which design earns the most at the required service, and which resource binds on either side of it? And does a plan that knows the price of energy earn its place at every size, including under wholesale prices?
- **The frozen fortnight.** Real San Francisco rides and the trained forecasts; PG&E's BEV-2 tariff; California ISO net demand and emissions; and, new, the day-ahead and real-time prices at the PG&E load point for the same days, from the system operator's public archive. Every input dated and pinned.
- **Designs.** Fleet 400, 500, 600, 700, 800, 1,000 and 1,200 vehicles; one feeder (2.75 MW) or two (5.5 MW); chargers at the sizing rule's count or one and a half times it; people at one per forty vehicles. Three ways of calling vehicles in: a fixed threshold; the plan told the tariff; the plan told the day-ahead price instead (a scenario for an operator with a pass-through supply contract). In-order feeding throughout. Two seeds.
- **The account** (`finance.py`): revenue at the published average fare; energy under the tariff (base case) and under the day-ahead and real-time scenarios with an assumed delivery charge; the capacity subscription; chargers, storage, connection, land and people annualized; vehicles at a parameter of $60,000 a vehicle-year, on a slider from $30,000 to $100,000 on the money page. Contribution per site-day, per vehicle-day and per ride; payback on site capital; availability; and what binds: the share of scored steps with the grid at its limit, with vehicles waiting for a charger, and with rides lost while neither the grid nor the chargers were short (vehicles bind).
- **Required service.** 99% of rides served; for the plan arms, promises kept at least 95% of hours.
- **Bars, base case (tariff, $60,000 a vehicle-year).**
  1. A sweet spot exists on one feeder: among designs that meet service, the best contribution per day is at a fleet smaller than 1,200, and the contribution per day falls on the fleet sizes above it.
  2. The plan told the tariff has higher contribution than the threshold at every design where both meet service.
  3. Where service breaks on one feeder, the grid binds: at the smallest fleet that fails service, the grid is at its limit in more than half of the scored steps; at the largest fleet that meets it, in fewer than a fifth.
  4. Under the day-ahead scenario, the plan told the day-ahead price buys energy at least 10% cheaper than the plan told the tariff, at 500 vehicles on one feeder, with rides within 0.2 points.
- **Reported without a bar.** The real-time scenario; payback years; the same figures on two feeders.
- **What a miss would mean.** On 1: at this site more vehicles always pay, and the answer is the biggest fleet the grid allows. On 2: the plan has a size at which it costs more than it saves. On 3: service breaks for another reason than the feeder, and the capacity figure needs a new explanation. On 4: the plan's price response is tuned to the tariff's three periods and does not follow an hourly price.

### Result

Run 2026-10-08. **0 of 4 bars.** Numbers are in `data/derived/e19_sweet_spot.json`; reproduce with `depot-twin eval e19`. Base case: the tariff, $60,000 a vehicle-year, $100 a vehicle-day to run it, and $20 for each ride lost beyond its fare.

A ride pays the published average fare, $19.69, on average at every fleet size. Busy pricing moves price between hours and not between designs: the share of steps sold at the busy price runs from 10% at 400 vehicles to 69% at 1,200 on one feeder, and the average fare is the same at both.

One feeder, the sizing rule's chargers:

| Fleet | Threshold: contribution a day, rides served | The plan, told the tariff: contribution a day, rides served | Rides lost a day (threshold, plan) | Grid at its limit (threshold, plan) |
|---|---|---|---|---|
| 400 | $68,200, 100.0% | $69,400, 100.0% | 0, 0 | 1%, 9% |
| 500 | $87,600, 100.0% | $88,800, 100.0% | 0, 0 | 23%, 19% |
| 600 | $105,800, 99.95% | $106,200, 100.0% | 8, 0 | 64%, 43% |
| 700 | $126,200, 99.98% | $125,600, 99.89% | 5, 20 | 98%, 97% |
| 800 | $134,900, 98.5% | $130,800, 98.0% | 295, 400 | 100%, 100% |
| 1,000 | $68,100, 88.1% | $65,400, 87.8% | 3,024, 3,093 | 100%, 100% |
| 1,200 | -$39,900, 77.6% | -$58,400, 76.1% | 6,795, 7,261 | 100%, 100% |

The best design in the sweep is 1,200 vehicles on two feeders under the plan told the tariff: $219,700 a day with 100.0% of rides served. The best on one feeder at the required service is 700 vehicles under the threshold: $126,200 a day with 99.98% of rides served.

Reported without a bar: at the designs that meet service with the sizing rule's chargers, site capital is paid back in 0.15 to 0.19 years of contribution, and energy under the real-time scenario costs $0.100 to $0.103 a kWh, within a tenth of a cent of the day-ahead scenario.

| Bar | Result | |
|---|---|---|
| 1. A sweet spot inside the range on one feeder, with contribution falling above it | At the required service the best fleet is 700. Contribution still rises to $134,900 at 800, where 98.5% of rides are served, and falls steeply after | **Miss** |
| 2. The plan beats the threshold wherever both meet service | Ahead at 400, 500 and 600 on one feeder by $300 to $1,200 a day and at every size on two feeders; at 700 on one feeder the threshold earns $600 to $1,200 more | **Miss** |
| 3. The grid binds where service breaks: over half at the smallest failing fleet, under a fifth at the largest passing one | 100% at 800; but 98% at 700, where service still holds | **Miss** |
| 4. The plan told the day-ahead price buys at least 10% cheaper under that scenario | $0.1011 against $0.1018 a kWh at 500 vehicles: 0.7% | **Miss** |

What this says:

- **The sweet spot on one feeder is 700 vehicles, and the account pulls one step past it.** 800 vehicles earn $8,700 a day more than 700 while serving 98.5%, because 295 lost rides a day cost $5,900 at $20 each against the fares of a hundred more vehicles. Past 800 the account turns hard: 1,000 vehicles lose 3,024 rides a day, $60,500 at $20 each, and earn half of what 700 do. 1,200 lose money.
- **Scarcity does not pay.** A fleet too small for its demand sells more of its hours at the busy price and earns the same $19.69 a ride, so a lost ride is only ever a loss.
- **The grid saturates before service breaks.** At 700 vehicles the feeder is at its limit 98% of the time and 99.98% of rides are still served, because the fleet's batteries carry the day. Service breaks at 800. The bar's "under a fifth" is wrong about where the band starts: the grid is at its limit 64% of the time at 600.
- **The plan's worth is its energy price, and it closes as the grid saturates.** It pays $0.1628 against $0.1915 a kWh at 400 vehicles, $0.1865 against $0.1948 at 600, and the same $0.1901 at 700, where the plan loses 20 rides a day to the threshold's 5 and comes out $600 behind. Above 700 the plan loses more rides than the threshold at every size.
- **The plan's price response follows the tariff's clock, not an hourly price.** Told the day-ahead price it buys 0.7% cheaper under that scenario. E20 tests the steering directly.
- **Two feeders.** Contribution rises through 1,200 vehicles, with the grid at its limit 41% to 63% of the time there. The sweet spot lies beyond the sweep.
- **One and a half times the chargers buy nothing.** Under the threshold they cost $500 to $900 a day at 400 to 700 vehicles on one feeder for the same rides, and above 700 they make the plan worse: 96.7% against 98.0% at 800.
- **Under the wholesale scenario** energy would cost about $0.10 a kWh against $0.16 to $0.19, worth $3,500 to $5,500 a day at 400 to 700 vehicles. It is a scenario for an operator with a pass-through contract and an assumed delivery charge of $0.08 a kWh, not a figure for this site.

## E20. Can the plan follow an hourly price?

Registered 2026-10-05. E19 found the plan's price response tuned to the tariff's three periods: told the day-ahead price, it did what it did with the tariff. For this test the steering reads a price curve: the expensive hours are the dearest quarter of the next 24 that also sit at least 20% above the median hour, and the pre-peak window precedes whatever stretch that is. On the tariff nothing changes: the peak is still 4 pm to 9 pm.

- **Days.** The `sf_e8` fortnight, second week scored, 500 vehicles on one feeder, three seeds (2001 to 2003). Days used before; hypotheses written first.
- **Arms.** The plan told the tariff (as E12 and E19); the plan told the day-ahead price with that steering; and, as a check that it changes nothing where it should not, the plan told the tariff *as a price curve* through the same path.
- **Bars.**
  1. Under the day-ahead scenario, the plan told the day-ahead price buys energy at least 10% cheaper per kWh than the plan told the tariff, with rides within 0.2 points.
  2. The plan told the tariff as a curve matches the plan told the tariff: energy per kWh within 2%, rides within 0.2 points.
  3. Promises are kept at least 95% of hours in every arm.
- **What a miss would mean.** On 1: the day-ahead prices that fortnight have too little shape for steering to matter, or the dearest-quarter rule is the wrong window; report the price spread. On 2: the price-curve path moves the tariff case, and E12's result does not describe the plan. On 3: price steering costs the promise.

### Result

Run 2026-10-08. **2 of 3 bars.** Numbers are in `data/derived/e20_price_steering.json`; reproduce with `depot-twin eval e20`.

500 vehicles, one feeder, three seeds:

| Arm | Rides served | Promises kept | Energy per kWh under the tariff | Under the day-ahead scenario |
|---|---|---|---|---|
| The plan told the tariff | 100.0% | 97.8% | $0.1682 | $0.1019 |
| The plan told the tariff as a curve | 100.0% | 97.8% | $0.1682 | $0.1019 |
| The plan told the day-ahead price | 100.0% | 96.4% | $0.1925 | $0.1011 |

| Bar | Result | |
|---|---|---|
| 1. Day-ahead steering buys 10% cheaper under day-ahead prices, rides within 0.2 points | 0.8% cheaper; rides level | **Miss** |
| 2. The tariff as a curve matches the tariff path | Identical to four decimals | **Pass** |
| 3. Promises kept 95% in every arm | 96.4% to 97.8% | **Pass** |

What this says:

- **The plan can follow a price curve, and on the tariff it does exactly what the tariff path does.** The curve path is a generalization of the tariff path.
- **This fortnight's day-ahead prices gave it almost nothing to follow.** Steering by them buys energy 0.8% cheaper under the day-ahead scenario, worth about $40 a day in contribution at 500 vehicles.
- **Steering by the wrong price is expensive.** Billed on the tariff, the arm that steered by day-ahead prices pays $0.1925 a kWh against $0.1682, 14% more, and earns $1,200 a day less. The price the plan is told has to be the price the depot pays.
- **So the price response is real and conditional.** It pays where the price has a shape worth paying for. The tariff's evening peak has one; this fortnight's day-ahead curve at this load point does not.

## E22. Does the twin survive the real visit cadence?

Registered 2026-10-07.

- **Question.** The filings count charging sessions and chargers. Over six quarters a vehicle charged once every 7.5 to 9.4 trips, and each charger saw 14 to 21 sessions a day. The twin under long sessions visits the depot 1.3 to 1.5 times a vehicle-day for about an hour, with a fifteen-minute leg each way and cleaning on every visit, and its own sensitivity study found that 2.5 visits a day cost 13 points of rides. Can the twin reproduce the real cadence with plausible settings, and do its findings hold under it?
- **The record.** `data/derived/footprint.json`: 2025 Q1 to 2026 Q2, trips per session 9.34, 9.39, 8.93, 8.41, 7.84, 7.45; sessions per charger-day 15.7, 16.9, 14.4, 19.3, 21.0, 19.2. The target is the last three quarters: 7.5 to 8.5 trips a session, 19 to 21 sessions a charger-day. Charging data covers the whole passenger fleet, pilot and deployment; trips are the deployment's. A session in the filing is one plug-in; a visit in the twin is one plug-in.
- **Arms.** The twin at 500 vehicles on one feeder on the `sf_e8` fortnight, a threshold rule, in-order feeding, seeds 2201 to 2203. Capacity is read on fleets of 400 to 1,000 in steps of 100, as the largest fleet serving 99% of rides with every smaller one serving it too, once under the chosen setting and once under long sessions (called in at 20%, cleaned every visit, a fifteen-minute leg). The plan arm runs 30-minute slots, about 26 kWh, seven to eight trips' worth. The settings swept: depot leg 15, 8 and 5 minutes (miles in proportion); cleaning on every visit, every second, every fourth; call-in at 20%, 40% and 55% charge with release at 85%; chargers at the sizing rule's count (66) and at one per five vehicles (100), the filings' ratio.
- **Measures.** Trips per visit; visits per charger-day; rides served; energy per kWh under the plan; vehicles waiting for a charger. Every arm records the cadence it actually ran at and the share of its vehicles that arrived at the low-battery floor, so an arm named for a rule shows whether that rule was the one deciding.
- **Bars.**
  1. Some setting with a depot leg of at most 8 minutes and cleaning at most every second visit reproduces both of the filings' counts within 15%: 7.5 to 8.5 trips a visit and 19 to 21 sessions a charger-day.
  2. Under that setting, in-order feeding beats emptiest-first at 1,000 vehicles on one feeder by at least one point of rides served (E11's finding, under the real cadence).
  3. Under that setting, the one-feeder capacity at the 99% floor is within 100 vehicles of the capacity under long sessions.
  4. Under that setting, the plan told the tariff buys energy at least 5% cheaper per kWh than the threshold at 500 vehicles, with rides within 0.5 points, and the plan's own trips a visit sit inside the filings' range, within the same 15%.
- **What a miss would mean.** On 1: the twin's visit is too expensive and the real operation does something the twin does not model (depots inside the service area, cleaning off the charging path). On 2: the power-rule finding was an artefact of long sessions. On 3: capacity depends on the cadence, and every capacity figure has to say which cadence it is for. On 4: the plan's energy worth depends on long sessions.

### Result

Run 2026-10-08. **4 of 4 bars.** Numbers are in `data/derived/e22_cadence.json`; reproduce with `depot-twin eval e22`.

The sweep, 54 settings, three seeds each, 500 vehicles on one feeder. What decides cadence is the charge level that calls a vehicle in. The rows below are at a five-minute leg and the sizing rule's 66 chargers:

| Called in at | Cleaned | Visits a vehicle-day | Trips a visit | Visits a charger-day | Rides served |
|---|---|---|---|---|---|
| 20% | every visit | 1.5 | 17.3 | 11 | 100.0% |
| 40% | every visit | 2.0 | 12.3 | 15 | 99.5% |
| 55% | every visit | 2.4 | 9.4 | 18 | **87.7%** |
| 55% | every second | 3.0 | 8.4 | 23 | 99.7% |
| 55% | every fourth | 3.2 | 8.0 | 24 | 100.0% |

The setting chosen (bar 1): called in at 55%, released at 85%, cleaned every fourth visit, a five-minute leg, the sizing rule's chargers. It gives 8.0 trips a visit against the filings' 7.5 to 8.5, and 24 visits a charger-day against 19 to 21, above the range and inside the 15% margin. No vehicle arrived at the low-battery floor, so the threshold was the rule deciding. With cleaning on every visit the same call-in level loses 12 points of rides. The leg moves little: with cleaning on every visit, 87.7% at five minutes and 85.8% at fifteen; with cleaning every fourth visit, 100.0% at every leg. One charger per five vehicles, the filings' ratio, serves the same rides at 16 visits a charger-day.

The findings under that setting, each arm with the trips a visit it actually ran at:

| Finding | Result | Trips a visit as run |
|---|---|---|
| In-order feeding against emptiest-first, 1,000 vehicles, one feeder | 86.1% against 77.0% of rides, 9.1 points | 10.5 and 10.7 |
| One-feeder capacity at the 99% floor, chosen setting, fleets of 400 to 1,000 | 600 (600 serves 100.0%, 700 serves 98.6%) | 8.2 at 600, 8.7 at 700 |
| One-feeder capacity at the 99% floor, long sessions | 700 (700 serves 100.0%, 800 serves 98.5%) | 18.6 at 700, 20.9 at 800 |
| The plan told the tariff on 30-minute slots against the threshold, 500 vehicles | $0.1783 against $0.1915 a kWh, 6.9% cheaper; rides 100.0% both | 7.4 and 8.0 |

| Bar | Result | |
|---|---|---|
| 1. A setting with a leg of at most 8 minutes and cleaning at most every second visit reproduces both counts within 15% | 8.0 trips a visit and 24 visits a charger-day | **Pass** |
| 2. In-order feeding beats emptiest-first at 1,000 vehicles by at least a point | 9.1 points | **Pass** |
| 3. Capacity at the 99% floor within 100 vehicles of capacity under long sessions | 600 against 700 | **Pass** |
| 4. The plan buys at least 5% cheaper at 500, rides within 0.5 points, its own trips a visit in the filings' range | 6.9% cheaper, rides level, 7.4 trips a visit: just under 7.5 and inside the 15% margin | **Pass** |

What this says:

- **The filings' cadence is reachable.** Three visits a day of short sessions, with a wash every second to fourth visit, reproduce what the filings count on trips a visit and run a little hot on visits a charger-day.
- **Cleaning is the cost of a visit, not the drive.** Shorten the drive and little moves. Skip the wash on three visits in four and three visits a day serve as many rides as one and a half.
- **Capacity reads one step lower under frequent visits:** 600 at the 99% floor against 700 under long sessions. The bar passes at its edge, so a capacity figure should say which cadence it is for. At a fleet of 700, vehicles were waiting for a charger in about two thirds of steps under either cadence. The 600 is capacity under the threshold rule, which calls a vehicle in at 55% whether or not a charger is free: at 700 vehicles about 165 half-charged vehicles sit queued while the road is short. A rule that waits for a free charger might carry more.
- **The power rule matters under short sessions too:** nine points at 1,000 vehicles. At that size the depot does not hold the filings' cadence. Vehicles wait for a charger in every step and a visit stretches to 10.5 trips.
- **The plan keeps an energy edge at the filings' cadence, a smaller one.** On 30-minute slots it buys 6.9% cheaper at level rides, with 3.4 visits a vehicle-day. The plan chose most of its own calls: the floor made 9.8% of them.

## E21. What does East Oakland ask of a depot, and when?

Registered 2026-10-07; runs after E22, on the cadence E22 settles.

- **Question.** The twin sizes demand from the fleet. The filings give the other direction: residents served and trips, by quarter. What does the service area around the parcel produce in rides, how many vehicles is that, which feeder does it need, and when?
- **The record.** `data/derived/footprint.json`: the served tracts (1,496 then 1,796), their 2020 population (5.73 then 7.16 million), trips per resident a month: 0.106, 0.130, 0.125, 0.174, 0.182, 0.197 over 2025 Q1 to 2026 Q2. Service areas around the parcel as circles of straight-line distance over Alameda County tracts only (83 San Francisco and 33 Contra Costa tracts fall inside 20 km and are left out: across the bay, and another county's service): 8 km (421,000 residents), 15 km (912,000), 20 km (1,082,000).
- **Method.** Penetration from the last four quarters' residents and trips; a ramp from the constant-footprint quarters (2025 Q3 on), as a monthly growth rate with its range; a density elasticity from the nine donor areas (rides per resident against residents per square kilometre, log-log, ordinary least squares, leave-one-area-out) applied to the service area's density against the served footprint's, which needs the donor areas' populations; the twin's rides-per-vehicle-day turns rides into vehicles; the capacity figures turn vehicles into feeders.
- **Bars.**
  1. Leave-one-area-out error of the density fit within 35% on at least six of nine donor areas, with a positive elasticity. If the donor areas' populations are not built, the fit cannot be run and the bar is scored a miss.
  2. The 20 km area at today's penetration needs fewer vehicles than one feeder carries at the 99% floor.
  3. At the measured ramp, the month in which the 20 km area needs a second feeder is more than 24 months out and less than 120.
- **What a miss would mean.** On 1: density does not explain demand across donor areas, and the level stands on penetration alone, labelled so. On 2: the parcel is demand-bound, not grid-bound, today. On 3: the ramp is too fast or too slow for a lease-time decision to lean on.

### Result

Run 2026-10-08, on the capacity E22 measured: 600 vehicles on one feeder at the 99% floor. **1 of 3 bars.** Numbers are in `data/derived/e21_demand.json`; reproduce with `depot-twin eval e21`.

| Bar | Result | |
|---|---|---|
| 1. Density elasticity across donor areas | Scored a miss without a fit: the donor areas' populations it needs are not built. The level stands on penetration alone | **Miss** |
| 2. The 20 km area today needs fewer vehicles than one feeder carries | 241 vehicles against 600 | **Pass** |
| 3. The second feeder more than 24 months out and less than 120 | 19 months at the measured growth; 36 at half of it | **Miss** |

Penetration over the last four quarters: 0.169 trips a resident a month. Growth at a constant footprint (2025 Q3 to 2026 Q2): 5.2% a month, which doubles in about fourteen months. It is a scale-up phase, so half of it is shown beside it.

| Service area around the parcel | Residents | Rides a day today | Vehicles at 25 rides | Months until a second feeder, measured growth / half |
|---|---|---|---|---|
| 8 km | 421,000 | 2,350 | 94 | 37 / 73 |
| 15 km | 912,000 | 5,080 | 203 | 22 / 43 |
| 20 km | 1,082,000 | 6,030 | 241 | 19 / 36 |

What this says:

- **Today the parcel is demand-bound, not grid-bound.** The 20 km area at today's penetration is 241 vehicles; one feeder carries 600. A depot here opens with room to spare, and the question is when the room runs out.
- **At the measured growth it runs out in 19 months for the 20 km area; at half the growth, in three years.** Bar 3 asked for more than 24 months and missed at the measured rate. Read the timing as a scenario, not a forecast: it says what happens if the scale-up growth continues. The second feeder should be applied for at the lease.
- **The density adjustment is not built.** Without it a dense service area and a sparse one get the same rides per resident. The three areas here run from 3,000 residents a square kilometre at 8 km to 2,000 at 20 km.

