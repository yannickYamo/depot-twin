# Build log

The turns, where a belief met a test and the roadmap moved, are summarized in [DECISIONS.md](DECISIONS.md). This log is every step in order.

How the project was built, in order: what was decided, why, what it replaced, what turned out to be wrong. Results and their registrations are in [EVALS.md](../EVALS.md), and how each model was trained is in [TRAINING.md](TRAINING.md).

The rule for this log: a decision that was reversed stays in, with the reason it was reversed.

## 1. The question

A robotaxi earns only while on the road. Every vehicle returns to a depot to charge and be cleaned. Chargers and staff get added in weeks; a grid connection takes years. So the pace of a city's fleet is set by a number usually taken from a spreadsheet: how many vehicles one site can carry.

The project is to answer that for a real parcel, with everything rebuildable from public data.

**Decided at the start:**

- Every claim has a test, with its bars fixed before its run. A miss is published.
- Every outside number carries its source. Every assumed number says it's assumed.
- The sizing method is wave sizing, charger-group arithmetic and the rule "charge the vehicles that need it most".

## 2. Choosing the site

**Decision.** A hypothetical depot at 7825 San Leandro Street, Oakland: a former foundry parcel of about 14.5 acres, zoned general industrial.

**Why this one.** The parcel, its zoning and the grid around it are all on the public record. The two strongest feeders passing it each show about 2.75 MW of load headroom in PG&E's published capacity analysis.

**What was rejected.**

- A former big-box site on Edgewater Drive: feeders show 15 to 999 kW of headroom, and it isn't industrially zoned.
- A city-owned parcel on Hegenberger Road: not industrially zoned.
- The Coliseum Way block beside a substation: stronger feeders, up to 4.6 MW, but no specific parcel could be verified.

**What the grid data settled early.** No single 12 kV feeder in the area shows more than about 4.6 MW. A 200-vehicle depot fits on one feeder. A 2,000-vehicle depot needs tens of megawatts. The growth study exists to find where between those the site breaks.

## 3. The simulator

**Decision.** Discrete events for things - arrivals, staff, cleaning bays - and fixed one-minute steps for power.

**Why.** Every charging vehicle draws on the same grid connection and battery, so no vehicle's finish time is computed alone. The cost is that finish times are accurate to two steps. The tests state that tolerance.

**Decision.** A control rule proposes; the simulator clamps every grant to what the battery accepts, the charger delivers and the site has left.

**Why.** It makes a learned or faulty rule safe to compare with hand-written ones. A rule can be bad, never physically impossible.

**Decision.** The planner's hand arithmetic is the first test. Before the simulator is trusted on cases nobody can check by hand, it must reproduce the cases somebody can.

**Decision.** The site's load manager draws at most 95% of the connection (`usable_share`), so one feeder is 2,612 kW usable of 2,750.

**Why.** The published headroom already carries the utility's planning margins: PG&E plans feeders to at most 67% of thermal rating and transformers to under 80% under normal conditions. On the depot side the electrical code treats EV charging as a continuous load, and with an automatic load manager the service is sized for the load the manager permits (NEC 625.42). What's left is the manager's own margin for metering and response, and 95% is in line with practice. It's labeled an assumption, and the 80% reading is available as the same parameter.

## 4. Public data: what was there and what was not

| Wanted | Found | Consequence |
|---|---|---|
| Robotaxi trips by time and place | The quarterly filings with the state utilities commission redact every trip-level field: dates, places, miles, charging records | Only the monthly statewide table is usable. It sets totals (trips, and miles split into passenger, pickup and empty), which the fleet model is calibrated to. |
| Hourly ride-hail demand in the East Bay | None exists publicly | Demand shape has to come from another place. |
| San Francisco ride-hail by hour | A 2016 county study, behind a bot check and nine years old | Not used. |
| A large, current ride-hail series | City of Chicago publishes every trip | Used for the first demand forecast. The city's 2023 to 2024 dataset timed out on every hourly aggregation, so the series starts in January 2025; even the current dataset only answers one day at a time, so the loader asks for each day separately. |
| Energy per mile of a robotaxi | No measured figure is public for any vehicle | Assumed at first (0.40 kWh per mile plus 1.5 kW), later studied; see section 12. |

## 5. First demand forecast, and its miss

**Decision.** A week-ahead forecast of hourly demand, using only information at least a week old, because depot planning happens a week out.

**Registered bar.** Remove 15% of the error of "same hour last week" on 91 held-out days.

**Result.** Missed. XGBoost with a fixed 400 trees came in at 6.24% against 6.29% for the baseline. The first model was LightGBM, and it missed on the same split. The library was never the limit: a week-old history plus the calendar knows almost nothing that last week's number does not.

**A second look, and a narrower conclusion.** A walk-forward check on four earlier windows, none touching the held-out period, showed the forecast beating the baseline in all four, by 4% to 26%. The fair reading is that it helps in unusual weeks and adds little in ordinary ones. The registered result still stands as a miss.

**A suggestion tested and declined.** Setting the number of trees by early stopping was worse in three of four windows. The model keeps a fixed 400.

**Consequence.** The simulation uses the weekly shape the forecast produces, not its edge over the baseline. Nothing downstream rested on the missed bar.

## 6. The fleet

**Decision.** Rides on the road are modeled in aggregate, in fixed steps. The depot is modeled vehicle by vehicle.

**Why.** The question is about the depot, so that is where the detail went.

**Calibration.** One free parameter, the average speed with no ride assigned, is set so the simulated split of miles matches the filed split: 58.9% with a passenger, 14.8% driving to a pickup, 26.3% with no ride assigned.

**Decision.** A rider waits up to ten minutes for a free vehicle and is counted lost after that. Rides served means rides served over rides served plus rides given up on.

**Decision.** Each vehicle carries a physical identity through its visits, separate from the id of the visit, so anything counted per vehicle follows the vehicle. Ride-minutes are conserved across vehicles: the minutes of the rides served in a step are shared among the working vehicles with a cap and redistribution, and the sum is asserted.

## 7. Deciding when to call vehicles in

We built four rules for deciding when a vehicle comes off the road and plugs in, in rising order of sophistication.

| Rule | What it does |
|---|---|
| Threshold | Call a vehicle in at 20% charge, release at 85% |
| Headroom | Call in the emptiest vehicles when the road can spare them and a charger is free |
| Plan | Solve a small linear program every hour over the next day |
| Learned | A policy trained by reinforcement learning sets the call-in and release levels each hour |

**What went wrong on the way.**

- The first plan fell back to "send in everything that fits" whenever its program was infeasible, which happened when the fleet ran low. The hard energy floor became a soft one. We removed the fallback.
- Training the learned policy at full scale was too slow. Two changes solved it: training on a quarter-scale copy of the 1,000-vehicle scenario, and a three-minute power step during training. Because the policy only sees shares and ratios, a registered test then checked that it carried to the full-size fleet.

**Result.** At 1,000 vehicles on one feeder: threshold 74.7%, headroom 76.7%, plan 75.9%, learned 76.4%. Headroom is the best hand-written rule at both sizes, and the learned policy carried from a quarter-scale fleet to 1,000. The most any rule recovers is two points; the other 23 are grid.

## 8. The growth study

One feeder carries 500 vehicles at 99% of rides served and 600 at 95%. Hand arithmetic on energy alone says 613; the simulation adds that queues form before the energy runs out. A battery buys one step at the 95% level and nothing at 99%. A second feeder doubles the site. Two thousand vehicles don't fit on this parcel's grid at all.

**What the chart showed.** Grid draw swings from hour to hour, because vehicles arrive in batches. That observation became section 13.

## 9. Money and a fast model of the simulator

**Decision.** Price each design with public figures - fare, tariff, charger and battery cost, staff, land - and train gradient-boosted trees to stand in for the simulator, so thousands of designs can be searched.

**Decision.** Prices aren't model inputs. The trees predict physical outcomes, and money is computed from them. A price can change without retraining.

**First version (evaluation E3).** 1,600 designs drawn uniformly at random, three-day runs.

**What it showed.**

- Service predicted well: 0.62 points of error on unseen designs, against 6.2 for the spreadsheet formula.
- The overfitting bar missed: test error 1.45 times validation error.
- Used to search, the trees picked designs that held up on service in all three cases. Contribution was predicted 13% to 15% above the simulated figure in all three.

**Behind the money gap.** The three-day runs measured a Tuesday and a Wednesday. Every design was judged on two quiet days, never on a Friday or Saturday peak. The predictions were right about the wrong days.

## 10. Testing the search itself, and the rebuild

One point decided the rebuild: an optimizer doesn't sample a model fairly, it hunts for the designs the model likes best. A model accurate on average can still hand over a depot that fails.

| Change considered | Decision |
|---|---|
| Test the search itself, by simulating what it picks | Adopted. It became the main test. |
| Space-filling sampling, with extra designs where capacity barely meets demand | Adopted. |
| Keep predictions inside their physical range | Adopted: targets trained on a logit or log scale. |
| Choose designs for a spread of demand, not the average | Adopted. |
| A test set generated only after the models are frozen | Adopted. |
| More ratio features | Two adopted (chargers per vehicle, battery per vehicle). A third was already present. |
| Split by design, not by row | Already in place. |
| A wider hyperparameter search | Declined. A few thousand rows do not justify it, and every extra option is another chance to fit noise. |
| Trip length as an input | Declined at the time for lack of data; reopened in section 14. |
| Weather and events in the demand model | Declined for an infrastructure question; reopened for the controller in section 14. |

**Rebuilt version (evaluation E4).** Full-week runs. 1,000 space-filling designs and 1,000 at the edge of "barely enough", plus 300 designs generated after the models were frozen. The planner accepts a design only if its predicted service, less a safety margin, still reaches 99%. The margin is the 90th percentile of over-prediction on validation designs the model predicts to pass.

**What E4 showed.**

- Accuracy held on the designs made afterwards: 1.34 points, 1.05 times validation error, and 0.68 points near the service level.
- The margin came to 1.35 points, wider than the one point of room any design has above 99%. The planner offered no design in any of the three cases, on expected demand or across scenarios.
- So the search itself went unmeasured: there was no pick to simulate.

**Rule adopted.** The fast model is accurate on average and not near the edge that matters. It can shortlist; the simulator decides.

## 11. Teaching the model where the search looks

**Decision (evaluation E5).** Simulate what the search picks, add those runs to the training data, retrain, repeat. Two rounds. Then a margin measured on searched designs never trained on.

**Result.** With nothing picked there was nothing to retrain on. Both rounds held no designs, the margin stayed at 1.35 points, and no candidate was acceptable in any case. The rule from section 10 stands.

## 12. Energy per mile, studied instead of assumed

There's no measured fleet figure public. The study combined official efficiency ratings, vehicle mass, published estimates of computer and sensor power, city traffic speeds, and one rider's report of remaining range.

**What it found.**

- Mass matters less than expected: about 0.009 kWh per mile per 100 kg at city speeds.
- Drivetrain matters more: two of the vehicles weigh the same and differ by half in official city consumption.
- Always-on load matters most: roughly 2 kW for about 21 hours a day, which is 40 to 45 kWh before the vehicle moves.

| Vehicle | Driving, kWh per mile | Always-on, kW | All-in at 154 miles a day |
|---|---|---|---|
| Jaguar I-PACE | 0.30 | 2.0 | 0.57 (0.50 to 0.65) |
| Ojai | 0.27 | 1.8 | 0.52 (0.45 to 0.62) |
| IONIQ 5 | 0.24 | 2.0 | 0.51 (0.44 to 0.58) |

These are estimates. The twin's single figure came to 0.59 all-in: about right in total, wrong in how it splits between miles and hours.

**Decision.** Each vehicle type gets its own driving figure and always-on load. These become starting values, then they're identified from each vehicle's own data (section 15).

## 13. From filling chargers to a heartbeat

**What the twin was doing wrong.** The headroom rule fills every free charger at once, so vehicles arrive and leave together. Grid draw swings on a two-hour cycle. It also charges from 20% to 85%, which spends a third of each session in the slow part of the charge curve.

**What public data suggests the real fleet does.** The redacted charging file in the state filings still has a row per session. Row count against filed miles works out at roughly 50 miles and 29 kWh per session, about three sessions a vehicle a day. The twin is running one and a half long ones.

**What was studied.** The adaptive scheduling approach published by Caltech, used commercially for workplace charging. Every few minutes, solve a convex optimization for the charging rate of every plugged-in vehicle, subject to its energy need, its departure time and the site's limits.

**Why it does not fit as it stands.** It's built for cars that sit for hours and arrive when their owners choose. A robotaxi depot is the reverse: every plugged-in minute is lost revenue, and the operator controls the arrivals.

**Decision.** Two coupled loops.

1. Time-boxed sessions of about 30 minutes in the fast part of the curve.
2. Chargers split into phased groups, so a few vehicles arrive every few minutes instead of a whole bank every half hour. The idea is the one used to cancel ripple in an interleaved power converter.
3. The number of vehicles in each beat set from the demand forecast: large in the troughs, small at the peak.
4. Inside the beat, power allocated so each vehicle lands on its target as its slot ends.

## 14. Pivot: forecast, identified twin, optimizing controller

This structure comes from home energy management. It fits the depot better than what the project had.

| Before | After |
|---|---|
| A reinforcement-learning policy chooses call-in levels | A controller solves an optimization every five minutes. It is not trained. The learned policy stays as a baseline to beat. |
| Vehicle energy use and charge curves are assumed constants | The twin is identified, not trained: each vehicle's parameters are estimated continuously from its own telemetry. |
| One week-ahead forecast | Forecasts at 1, 6 and 24 hours, with recent history and weather as inputs, and calibrated intervals around them |
| Demand spread assumed at 8% | Intervals measured from the forecast's own errors |
| Rides served is the only product measure | A ledger: vehicles promised on the road each hour at 95% confidence, with misses counted |
| Model and product measures | Three levels: model (error, and error at the peak specifically), system (solve time per tick), product (rides served, promises kept, none stranded) |

**Principles carried over.**

- Labels are free: a label is the value later observed, and features may use history up to the moment of prediction and nothing after it.
- Predict the disturbance, not the controller's own effect. Demand is a disturbance. A vehicle's charge on arrival is a consequence of control, never a prediction target.
- One feature builder shared by training and control, so the two can't drift apart.
- A model with good average error can still fail the product if it under-predicts at the peak, so the peak is scored on its own.

**Choices made for the controller.** Five-minute tick. Horizons of 1, 6 and 24 hours. Plan against the conservative end of the demand interval. Ledger in vehicles on the road per hour.

**A better demand source.** San Francisco publishes every taxi trip from December 2022 to May 2024: 4.1 million trips, times to the second, pickup and drop-off coordinates, distance and fare, in the public domain. It becomes the primary source, because it's the right city, and it supplies three things the Chicago series cannot: five-minute resolution, real trip lengths, and where trips start. The limits: these are taxis, not ride-hail, and updates stopped in May 2024. Chicago stays as a second city to test whether the method holds elsewhere. Both record trips served, not trips requested.

## 15. Identifying the twin

**Decision.** Each vehicle type gets its own driving energy and always-on load, and each vehicle differs from its type by a random 8%. The earlier scenarios keep their single figure so earlier results still rebuild. The new ones live under `scenarios/v2`.

**Decision.** One small Kalman filter per vehicle estimates its two energy figures from what it already reports every quarter hour: miles, time, and the change in a noisy battery gauge. Charge curves are estimated per type from the power delivered in each band of charge, using only readings where the vehicle got all it could take.

**Result (E6).** Three of four bars passed. A week of telemetry cut the median error of using the type's figure from 5.4% to 2.2% on driving energy, and from 5.2% to 3.0% on always-on load, which is inside 5% and short of the halving its bar asked for. 91.4% of vehicles ended within 8% on both figures.

**Caveat recorded with the result.** The charge-curve test is weak evidence: power readings in the simulator carry no noise. The whole test shows the method works on simulated vehicles, not what the true figures are.

## 16. Short-horizon forecasts: a dirty dataset, a miss, a diagnosis

**The data was dirtier than its description.** Inspection before any model was fitted found two things.

- Exact repeats of records, 6% to 15% depending on the month. Dropped.
- From mid-February 2024, reported rides rise by about half while the number of cabs reporting stays near 790, with dispatched trips roughly doubling. It looks like a change in what is reported. It was left in on purpose, as the kind of shift a forecast has to survive, and the registration says so.

**What the cleaned data says about rides.** 2.97 million rides. Median 3.2 miles, mean 7.2, because 31% start at the airport.

**Design choices.**

- The quantity forecast is the hourly rate (rides in the 60 minutes ending at a step), at five-minute steps, for the hour that starts 1, 6 or 24 hours ahead.
- One feature builder serves training and control.
- Calendar features describe the target hour, known in advance, not the moment of prediction.
- Blocks in time order: train; then 28 days to set the number of trees; then 28 days to calibrate the bounds; then 60 days held out. Rows whose label reaches into the next block are dropped.
- A unit test rewrites everything after a moment and checks that no feature at that moment changes.

**Result (E7).** All nine bars missed. Forecasts were level with the baseline at one hour and far worse beyond it, running 24% to 43% low at the peak.

**Diagnosis.** Training ended at the old level and the held-out days were at the new one. A tree model predicts by averaging training examples that look alike, so it can't predict a busier hour than it has seen. "Same time last week" has no ceiling. On Chicago, where the level is stable, the same pipeline behaved: bounds held 94% to 96% of the time, with nothing low at the peak.

**Fix tested (E7b).** Forecast the ratio to the same time last week instead of the count, and divide the series features by the same reference. Nothing else changed. Error fell by a quarter to a half. The forecast went from worse than the baseline to 17% to 26% better. Bounds held 93% to 94% of the time against a stated 95%.

**A flaw in a bar, recorded and not repaired after the fact.** The peak bar selected the busiest hours by what actually happened, and any forecast looks low on hours chosen for having turned out high. It should have selected hours expected to be busy. The miss stands. The controller's test measures the right thing instead: whether the upper bound holds in the busiest hours.

**Also learned.** Weather did not help on either city. It stays in the feature set as registered.

**Decision.** The controller uses the scale-free models and plans against their upper bound.

## 17. The heartbeat controller, and the design that did not survive

**Decision.** Test the controller on demand replayed from real days, not drawn from an average week. Rides offered are the real five-minute taxi counts, scaled to the fleet. What the controller is told about the next day is what the forecast models said at each moment. Development is 18 to 31 March 2024; evaluation is 15 to 28 April, run once.

**How three forecast horizons become a day plan.** Each model's output is read as a correction to last week's curve, and the corrections for the hours in between are interpolated.

**What was first built.** Thirty-minute sessions cut off by the clock, in six phases, as proposed in section 13.

**What happened on the development days.** It served far fewer rides than the headroom rule at both sizes. Four things in the design cost rides, and each changed it.

| What the 30-minute design did | What it cost | What the design does |
|---|---|---|
| The hourly plan counted vehicles driving in, being cleaned and driving out as if they occupied chargers | It thought the depot was full at a third of its real capacity and called in too few vehicles | The plan costs a visit as what it is: about an hour and a half off the road, one slot on a charger |
| The plan charged just in time | The fleet's average charge sat at the floor, which means many vehicles under it and forced returns | The plan holds a reserve and values energy in hand, so it charges whenever vehicles are spare |
| Vehicles were called in with little room | Nearly full vehicles spent an hour off the road for a 10 kWh top-up, and the fleet spiralled into shuttling | A vehicle is called only if it has room for most of a slot |
| Slots were measured in minutes, and a shortage was shared evenly | With the site short of power, every vehicle crawled and was then sent away half fed | Slots are measured in energy; no more vehicles are plugged in than the site can feed at full rate; they are fed in order |

**The finding underneath.** Short sessions are the wrong idea for this depot. A visit costs the road more than an hour whatever it delivers, because the depot is 15 minutes from the riders each way. With 60 kW chargers the charge rate is flat up to about two thirds full, so a short session buys no speed. The efficient session here is nearly a full one. The public hint of three short sessions a day (section 13) probably reflects chargers faster or closer to demand than this depot's. The heartbeat idea survived in a different form: steady phased arrivals, a plan that looks a day ahead, and never more vehicles plugged in than can be fed.

**Result (E8).** Four of five bars passed. At 1,000 vehicles the heartbeat served 87.6% of rides against 82.4% for headroom; at 500 both served 100.0%, with grid draw less than half as variable (0.22 against 0.56). No vehicle stranded. A tick costs under 16 ms at the 99th percentile. The ledger was kept in 98.6% of hours at 500 vehicles and 93.3% at 1,000 against a promised 95%: a miss.

**A sharing rule that was reversed.** The first power rule shared a shortage in proportion, which looks fair. Feeding vehicles in order at full rate is better: the first vehicles are back on the road sooner, and none of the others finishes later than it would have.

## 18. The ledger, rebuilt

**What E8's ledger did.** The promise for the coming hour was built from the plan's steady-state figure for vehicles on the road, which ignores vehicles already on their way in or out. At 1,000 vehicles it was so far off that widening the margin drove the promise below zero: always kept, worth nothing.

**The rebuilt ledger.** Start from what is on the road now. Move it by the change in how many vehicles the plan calls in. Build the margin to keep 97.5% of promises, so that 95% can be stated and met over a single week of 168 promises. Let the margin correct itself after each kept or broken promise.

**A measure added so the ledger could not cheat.** How much of what was delivered had been promised. A ledger that promises nothing is always kept.

**Result (E9, on days later than any used before).** Kept in 96% to 98% of hours while promising 94% to 97% of what was delivered. The E8 comparison repeated on those days: 88.6% against 84.3% at 1,000 vehicles.

## 19. A guard, and what it revealed

**Decision.** Wrap the controller in a guard that checks the one thing the forecast's bound claims, that rides stay under it about 95% of the time. It falls back to a rule that uses no forecast when the bound is being broken half the time. The same wrapper runs a new controller in shadow: asked every tick what it would do, never acted on.

**Result (E10).** As a detector it worked. No false alarm. A forecast cut to a third of the truth was caught within six hours every time. But the unguarded controller, given those broken forecasts, served exactly as many rides as with sound ones. And a plain threshold rule, given the controller's power rule, served as many rides as the whole controller.

**What that meant.** The comparisons in E8 and E9 had changed two things at once: how vehicles are called in, and how power is shared among those plugged in. The simple rules run with a different power rule from the controller's.

## 20. Taking the controller apart

**Decision.** Run every way of calling vehicles in with every way of sharing power, on the same days (E11).

**Result.** The gain in rides belongs to the power rule. At 1,000 vehicles a fixed threshold with in-order feeding serves 88.8% of rides, level with the full controller's 88.6%, and 5.9 points more than the same threshold with "lowest charge first". At 500 vehicles nothing separates the cells: every one serves 100.0%.

**Why "lowest charge first" loses.** When power is short, each newly arrived, emptier vehicle takes power from one that was nearly finished. Vehicles pile up half charged. Fed in order, they finish one after another and go back to work. *(Section 25 measures this.)*

**What this does to E2, E8 and E9.**

- The numbers in E8 and E9 stand; their explanation doesn't: the day-ahead plan, the forecasts feeding it and the identified energy figures did not buy rides.
- The first growth study and the recall-rule comparison (E2) ran every rule with "lowest charge first". Their rankings of recall rules hold among themselves; their absolute levels at power-short sizes were held down by the power rule.
- The forecast work (sections 5 and 16) is sound as forecasting. It isn't yet shown to matter to the depot.

**What the plan still offers.** A slightly smoother grid draw. An hourly promise that's kept. Whether that's worth a linear program and three forecast models over a threshold is an open question. The honest current answer for rides: no.

**Where a plan should matter and has not been tested.** Money. Energy between 4 pm and 9 pm costs more than twice the off-peak price at this site, and the capacity charge follows the highest draw of the month. A threshold can't move charging out of the expensive hours. A day-ahead plan can.

## 21. The growth study, second version

With each vehicle type's own energy use and demand replayed from real days, one feeder carries 700 vehicles at 99% and 800 at 95% under long sessions, with either arm. Two feeders carry 1,500 at 99% with the heartbeat arm and 1,200 with headroom. 2,000 still don't fit. The grid saturates before service breaks: the feeder is at its usable limit at 700 vehicles, where 99.9% of rides are still served.

A battery makes no difference under the heartbeat at any size. A battery moves energy in time and adds none, and with power fed in order there is no queue for it to relieve. What the battery bought in the first study was relief for a queue that in-order feeding removes for nothing.

## 22. The test the plan had to pass

**Decision.** Tell the plan the price of energy. Test it on cost at equal service, against a plain threshold and against a threshold that simply knows the clock. After E11, the second baseline went into the registration from the start, so a gain could not again be credited to the wrong part.

**What development showed first.** Adding the tariff to the hourly program moved nothing. The program decides how many vehicles to call, and that number was not what determined when energy was bought.

**What did move it.** Choosing which vehicles to call: before the peak, those that would otherwise run down during it; during the peak, only those that cannot wait. The program's part is to pace that by how many vehicles the road can spare.

**Result (E12, on the last unused days).** All four bars passed. At 500 vehicles the plan with prices paid 12.2% less per kWh with no loss of rides: $2.75 more per vehicle per day in fares less energy. A fifth arm, the plan with its clock steering and an hourly program that cannot see prices, paid the same. The saving is the clock steering, and the program's own price term adds nothing measurable beside it. The clock-aware threshold paid 10% less per kWh and lost 5.1 points of rides doing it, ending $23.26 a vehicle a day worse than a plain threshold. At 1,000 vehicles, the site at its limit around the clock, nothing could move.

**What the plan is for.** Not rides. Buying energy in the cheap hours safely, at sites with headroom. Making an hourly promise that is kept. The gain is real and small: 0.6% of fares less energy.

## 23. Guarding against regression

**Decision.** Before changing anything further, pin what exists.

**Pinned numbers.** Seven small, fully seeded runs have their headline figures stored. A change that moves one must regenerate the file on purpose.

**Invariants.** Each headline finding has a miniature that runs on every change: in-order feeding serves more rides when power is short; the heartbeat strands no vehicle and keeps its promises; identification beats the type's figure; the grid limit holds under every rule.

**Documents agree with results.** The scoreboard is generated from the result files. A test fails if the committed copy differs. Another fails if any registered test lacks a result. `facts.py` reads the headline figures from the result files and writes `docs/FACTS.json`, and a test fails when the README, the brief or the story says anything else.

**Records know their code.** Every result file carries a stamp of the code it ran on (`provenance.py`), and `depot-twin stale` lists any record whose code has since changed. Every depot arm records the cadence it ran at and the share of its vehicles that arrived at the low-battery floor, so an arm named for a rule shows whether that rule was the one deciding. `requirements-frozen.txt` records the exact versions the results were produced with.

**Structure.** The evaluations are a package of five modules by subject, with the registry in the package. `depot-twin eval` with no names refuses and lists them, since running all of them is hours and rewrites every record. The controller's hourly promise is a `PromiseLedger` and its question of which hours are expensive is `steering.expensive_window`, each with tests of its own. The simulator, the controller and the account are type-checked in CI.

**CI.** Lint. Tests on three Python versions. The learned-policy stack once. A smoke job that runs the commands a visitor would type from a clean checkout and uploads the report. A release workflow builds the package and the report from a tag, only after the same checks pass.

**Large files out of git.** Trained models and raw simulation sweeps are release artifacts. The small result files the documents quote stay in the repository.

## 24. When short sessions win

The first controller's 30-minute sessions failed, and section 17 blamed the 15-minute drive. A study of slot length against drive time and charger power showed otherwise. Distance barely matters. Every visit carries plugging and cleaning whatever the drive. Charger power does matter: at 150 kW a 20-minute slot delivers 40 kWh and serves as many rides as an hour at 60 kW.

The rule is about energy per visit, not minutes. A pulse of short sessions suits a depot with fast chargers.

## 25. The explanation that had not been measured

**What happened.** The browser simulator (section 26) is a second implementation, held to the first by a test. Its first version had no depot staff. It disagreed with the Python simulator in one place only: "emptiest first" at 1,000 vehicles, where it served more rides. In-order feeding agreed. The missing staff was the whole difference.

**What that meant.** Section 20 said emptiest-first loses because each new arrival takes power from a vehicle that was nearly done. Nobody had measured that. If it were the cause, staff would not matter.

**Decision.** Measure it: both power rules at 1,000 vehicles with 25, 50, 100 and 200 people, recording where every vehicle is (the staffing study in `EVALS.md`).

**Result.** The loss is site power left unused. Emptiest-first evens out the charge of everything plugged in, so vehicles finish together, then stand on chargers waiting for a person to unplug them: 32 at a time against 3. With 25 people, 7.5% of the site's power goes unused and 6.5 points of rides with it. With 100 or more people the gap is 3 points and stops closing.

**What this does to the story.** The numbers in E11 stand, and the explanation is the measured one. The claim is narrower: in-order feeding is worth 3 to 6.5 points at this site depending on staffing.

**What it says about method.** A second implementation caught what eleven registered tests had not, because the tests checked numbers and the explanation was prose. An explanation is a claim too.

## 26. A front end

**Decision.** The viewer is a static site, no server, no framework: TypeScript, canvas, Vite. One trace format, written by the Python simulator and by a simulator that runs in the browser. One set of views draws both.

**Why a second simulator.** A visitor should be able to change the fleet, the power and the rules and see the depot respond at once. That needs the model in the page. The cost is two implementations that can drift. Parity catches a disagreement between the two and cannot catch a mistake they share, so each simulator first asserts its own invariants: the minutes of the rides served add up across vehicles, and a vehicle is cleaned on every Nth of its own visits. Then a test holds the browser's rides served to the Python simulator's on matched definitions, under long sessions and at the filings' cadence, with both power rules: within half a point at 500 vehicles and a point and a half at 1,000. The page says what the browser model leaves out: the day-ahead plan and the forecasts.

**What was reversed.** The roadmap said React, and a compare mode with two floors side by side. The page has few moving parts and draws on canvas, so a framework added nothing. Comparison became a second depot run alongside under the other power rule, shown as a dashed line and one figure. Two floors would not fit a phone.

**What is in it.** The depot floor in plan view (road, lanes, queue, every charger filling, people, cleaning bays). The heartbeat strip: arrivals every five minutes over grid power against the site limit. Rides offered, served and lost per hour. Vehicles on the road against the plan's promise. Controls for fleet, grid power, chargers, charger power, staff, both rules, the call-in level and slot length. Replay of a run recorded from the full model.

## 27. Reading what others had done

**Decision.** Before more building, read the published work on fleet charging, shared electric fleets, depot practice and ride forecasting. The result is `docs/RELATED_WORK.md`.

**What it found.**

- The power-rule finding is a known result. Feeding the emptiest vehicle first is "most work remaining first", which makes jobs finish together, the worst rule for average completion time. Eleven tests and a study had rediscovered a theorem from 1968. The interaction with staff was not found in the literature.
- The same theory predicts a rule this project never tried: least energy needed first.
- The model's inputs mostly sit inside public figures (energy per mile in service 0.53 kWh against a public estimate of 0.49 to 0.60). Rides per vehicle are at the high edge. Depot visits per day are at the low edge.
- No open tool was found that models one depot's grid limit, queue, cleaning and staff together.
- No published method was found for validating a forecast for a city with no data.

**What changed.** The plan is reordered. A forecast that can be built for a new site, with an honest estimate of its error from held-out cities, moves to the front. See `docs/ROADMAP.md`.

**What it says about method.** The reading should have come first. It would have named the power-rule result on day one and pointed at the rule still untested.

## 28. A forecast for a place with no history

**Why.** Every forecast so far trained on the history of the city it serves. A new site has none. The forecast is what the plan and its promise rest on.

**Decision.** Borrow from cities that publish their rides, and measure the borrowing where it can be measured: hold out each city in turn, treat it as if it had no history, compare with what happened there (E13).

**Data.** New York ride-hail and yellow taxi by area, Chicago ride-hail, San Francisco taxi by area: 15 hourly series, each labeled with a kind of place. Two things did not work. Chicago's service times out on any query by area or before 2025, so Chicago is one whole-city series from 2025. New York's file server blocks a client that reads columns over the network in many small requests; the loader downloads each monthly file whole, counts, deletes it. Washington DC was planned and not loaded. No trip-level data exists for Los Angeles or Phoenix.

**A decision about level.** The plan was to predict how many rides a new place would see from its population and jobs. That's dropped for now. In this twin the level of demand is set by the fleet being planned, from public totals of rides per vehicle. What a place decides is the shape. So the generator takes the level as an input and borrows shape, holiday pattern, response to rain and week-to-week variation from donors of the same kind of place.

**Development, three rounds, on days that were not the test days.**

1. *First version.* Chicago held out: the cross-city model beat a model trained on Chicago itself. New York held out: lost to "same hour last week". Generated demand made every cell slightly worse.
2. *Size.* The model was made blind to size on purpose, so it would transfer. But how far to trust last week's figure depends on size: at 200 rides an hour it's noisy, at 30,000 precise. A model taught by San Francisco distrusted it in New York. The remedy: tell the model the log of last week's level, and train on every large donor again thinned to 300 and 2,000 rides an hour. New York improved. Generated demand then made New York much worse.
3. *Noise that belongs to the donor.* The cause: the generator borrowed a donor's week-to-week variation whole, including the counting noise of a 200-ride-an-hour donor, and replayed it at 20,000. That noise is taken out when a donor is taken apart, and the right amount put back when counts are drawn. A second change: the forecast is last week's figure moved part of the way to the model's, and how far is measured on donor cities the model never saw.

**A change that did nothing.** Weeks of leftover variation borrowed in runs of consecutive weeks, on the theory that a week resembles the one before. Measured, the resemblance is weak in every city (0.02 to 0.10). It made no difference. It stays because it is the more faithful choice.

**Result (E13), 1 of 4 bars.** The cross-city forecast beat "same hour last week" in seven of nine cells and was level with it in New York at six and 24 hours, where the donors transfer so poorly that the forecast is given no trust. It came within 1.25 times an in-city model in five. Bounds were too narrow for San Francisco, where only one donor city had earlier data, and over the top edge for Chicago. The depot reached the same answer on generated demand as on real days: 88.0% against 88.2% at 1,000 vehicles.

**What that means for a new site.**

- A new site should run on last week's curve until it has a few weeks of its own rides. The borrowed forecast has 77% to 93% of last week's error an hour ahead and 88% to 100% at six and 24 hours, across the three held-out cities.
- The guard from E10 is mandatory, because the bounds missed.
- Generated demand is fit for sizing a depot, though it does not improve the forecast: donors alone do as well or better in eight cells of nine.
- What helped most was not the generator: it was telling the model the size of the place and thinning real donor cities to it.

**East Oakland as the first new site.** `depot-twin new-site east_oakland` with a mix of 60% outer and 40% inner districts at 521 rides an hour (500 vehicles at 25 rides a day). It writes three forecasts, their bounds and trust, and three generated fortnights with the forecasts the site would have had at each moment. What the site is told to expect is the held-out cities' figure above.

**What it says about method.** The registration records all three rounds, written before the test days were touched. Three bars were missed and published as misses.

## 29. The power rule on another city's days, and the rule theory names (E14)

**Decision.** Run the three power rules on real Chicago days no depot run had touched: emptiest first; in order; least energy left first, which scheduling theory says is best for average time in the system.

**Result, 4 of 4 bars.** In-order feeding beats emptiest first by 7.3 points with 25 people and 3.4 with 100 (San Francisco: 6.5 and 3.0). Emptiest first again leaves 7.6% of the site's usable power undrawn. Least-left ties with in-order to a tenth of a point.

**What that means.** The finding isn't San Francisco's. The tie is informative: at a site short of energy, rides follow energy delivered, and any rule that feeds at full rate in a fixed order delivers all of it. Theory's best rule and the simplest rule are the same here. The claim is stated that way in the README and the brief.

## 30. How far the capacity figure moves

**Decision.** Move each uncertain input alone, within what public figures allow, and read rides served from 600 to 1,000 vehicles (the sensitivity study in `EVALS.md`).

**Result.** The site's capacity is a number of rides, not of vehicles. On these days, at 25 rides a vehicle a day, 700 vehicles serve every ride and 800 serve 98.7%. At 21.5 rides, 800 serve every ride. At 18, the low end of public figures, 1,000 serve 99.9%. Ten percent on energy per mile moves the limit by about a fleet step. Calling vehicles in earlier costs rides when every visit is cleaned: 1.3 points at 1.9 visits a day, 13 points at 2.4. Doubling the people changes nothing once power is fed in order.

**What changed.** The README states the capacity with its condition. Depot visits per day joined the list of things the model didn't know, until the filings settled it (section 53).

## 31. Reading capacity from generated demand (E15)

**Why.** E13 checked the depot on generated demand in one city. Before a new site's capacity is quoted from generated demand, the reading had to be tested elsewhere, and San Francisco's days were used up. A cautious reading was testable on Chicago and New York at once: quote the worst of ten scenarios.

**Result, 2 of 2 bars.** In both cities the real fortnight landed almost three points above the worst generated scenario. The average scenario was 3.9 points too kind for Chicago and 1.0 for New York, so the agreement E13 found in San Francisco is one city's figure, not a rule.

**A finding on the side.** The same depot and fleet serve 91% of rides on New York's days and 85% on Chicago's, at the same rides per day. How peaked a place's day is matters as much as how busy it is.

**What is still open.** The generator's typical weeks are kinder than real ones. The worst-scenario rule works around that.

## 32. Tidying

- The first-version modules - the stand-in model, the design search, the learned recall policy and its training - moved to `depot_twin/first_version/`, with a note at the top saying what they were built on and that nothing current depends on them.
- The browser simulator gained two tests: that more people narrow the gap between the power rules while in-order feeding is unaffected; and that the slot rule keeps every vehicle accounted for.

## 33. The README and the look of the front end

**README.** It leads with three findings (capacity under the baseline assumptions, the power rule, what prediction and control buy) and holds the rest as supporting evidence: why it was built, how it's put together, the choices in machine learning and statistics, how to use it. Results live in `EVALS.md`.

**Front end.** The look follows the visual style of the service's public site: mint, blue and deep navy; a geometric sans; pill controls; an open white page. The depot floor is a dark stage, a site at night, where mint means energy and nothing else. The charts sit under the stage, and the settings in a rail that stays in view. No logo or wordmark and no asset of theirs is used, and the independence line stays on the page. `PRODUCT.md` records who the page is for. `DESIGN.md` records the system as built.

## 34. Naming every vehicle, and showing the forecast and the grid

Four requests from the owner after seeing the page.

**Speed.** Speed is a dial: 1x = one simulated minute a second, slow enough to watch a vehicle plug in, then 2x, 5x, 20x and 60x.

**Every vehicle identifiable.** Each trace step names every vehicle off the road, with where it is and its charge, in both simulators. On the page a vehicle can be hovered for its name, followed with a click, and read as a visit: called in, given a charger, started charging, finished, cleaned, back on the road. A board lists the vehicles at each station.

**The forecast, scored on screen.** A chart sets the forecast for each coming hour against the rides that came, with the error and how often the upper bound held. Under it, the trained forecast's tested scores, read from the result files by `depot-twin data facts`, never typed in.

**The wider grid.** A real week of California's net demand and carbon intensity (California ISO, week of 15 April 2024, `depot-twin data grid`) runs beside the depot: how strained the grid is now; how much of the depot's energy was drawn in the grid's hardest quarter of hours; the carbon its charging carried against the grid's average.

**What the sample replays.** Three real San Francisco days from 15 April 2024, the same week as the grid data, with the trained forecasts (`depot-twin trace --demand`). The trace carries the forecast for the hour starting an hour ahead, the horizon the test measures.

**The hour under way.** The plan has no model for the hour already under way; it interpolates. A fourth model was trained for that hour, the same way as the others (the first-hour study in `EVALS.md`): error 9.2% against 14.2%, bound holds 96% of the time against 90%. The plan's rides and kept promises didn't change. With prices it bought energy 1.4% cheaper at 500 vehicles. The model is kept as an option, and the registered tests run on the interpolated figure.

## 35. A model workbench

**Why.** The owner asked that a visitor be able to change how the forecast is built and see what that does to the model and to the plan.

**Decision.** A third mode on the page, built on recorded results. `depot_twin/workbench.py` trains a reference forecast and fifteen variants that each change one thing: boosting rounds (10, 50, 200, 3,000 against early stopping); features (lags only, plus calendar, plus weather); training history (1, 3, 6 months against all); the target (ride counts against the ratio to last week); local history (none against this city); no model at all (same hour last week); a pretrained model (Chronos-2); the feed to the plan (intact, broken, broken with the guard). Tree depth and the other settings stay at the reference's. Every variant is scored on the same 60 held-out days, and the depot is run for a fortnight with the plan on each one's forecasts. The browser trains and simulates nothing.

**What it found about the model.**

- Training too long shows as it should: with 3,000 trees training error keeps falling, held-out error rises from 11.4% to 12.3%, and the bound holds 91% of the time where it is sized for 95%.
- One month of history: 14.7% error, no better than "same hour last week". Three months already 10.3%.
- Asking for ride counts: 15.5%, the failure that led to the ratio target.
- The reference isn't the best on the held-out days. Fifty trees (9.8%), six months of history (10.1%) and no weather (10.6%) all beat its 11.4%. The reference's stopping point and settings were chosen on earlier days that include a jump in the level of rides. The page says so, and says why the reference stays: choosing the winner on the test days is how a model comes to fit its test.
- A model that has never seen the city (11.3%) matches one trained on it (11.4%), with a bound that holds a little less often (92.4% against 92.8%).

**What it found about the plan.** Almost nothing moves. Rides served are 100.0% under every variant, including a forecast cut to a third. The plan at this depot is set by energy and by how many vehicles need charging, not by the ride forecast. The guard, when it takes over from a broken feed, costs more: its fallback rule doesn't know the price of energy ($0.192 per kWh against the reference's $0.168).

**So what does a forecast buy?** The page needed a measure that does respond, and an honest one. The plan covers the forecast's upper bound, so the bound has a price: vehicles held on the road that could have been charging, and rides above the bound not provided for. With no model the fleet of 500 holds 62.9 vehicles in reserve; with the reference, 48.5. Both are computed from the forecasts and the rides that came, and shown beside the full model's results with a sentence saying why the second set hardly moves.

**What it says about method.** A workbench built to show that a better model helps showed where it doesn't. It went on the page as found.

## 36. Showing the plan

**Why.** The owner couldn't see the model predictive control in the demo, and asked what it does for people.

**What changed.** The controller writes out its whole day plan each time it redraws it: visits, vehicles on the road, rides and energy for each of the 24 hours. The trace keeps every plan with the hour's quota and promise. In replay, the page shows the plan in force: what it calls in this hour; what it promised; the 24 hours ahead as bars over the ghosts of the plans made before; the vehicles it expects on the road against what the fleet did. Beside it, the same days run with a fixed threshold, on the same depot and power rule: rides served, energy per kWh, energy bought in peak-price hours, unevenness of grid draw.

**What the comparison shows.** The same rides either way, with cheaper energy and less of it bought in the peak under the plan. That's E12's result on the page.

**On the command line.** The "heartbeat" rule is the plan as E12 settled it, told the price of energy.

## 37. Data contracts, and the price of a forecast (E16)

**Steer.** The owner asked for the record to show each turn as a belief, a test and a change of course (`docs/DECISIONS.md`), and for data contracts before any model changed.

**Data contracts first.** The checks in code (`data/contracts.py`), run on every series the models train on, written into `docs/DATA.md`. The split registry (`data/splits.json`) with two windows reserved for confirmation and one accepted overlap recorded with its reason. The rule that rows a generator made can only ever be trained on, enforced where a model is stopped, calibrated or scored. Found and recorded: two six-hour gaps in one New York series; the daylight-saving hours; the dated level shifts.

**Then the question put first.** What is a forecast worth to the plan, and does that depend on what binds? E16 fed the plan perfect foresight, the model, last week's curve and a broken feed, in four regimes. Where energy binds, the four are identical. Where vehicles bind, perfect foresight is worth a sixth of a point and nothing short of it is worth anything: the model, last week's curve and the broken feed land within 0.03 points of each other. The model's money regret against perfect foresight is at most 0.12%. A forecast's value at this depot is the reserve its bound asks of the fleet - 50 to 99 vehicles for the model against 64 to 128 for no model - not rides.

**What changed.** The remaining forecast work is judged on calibration and sharpness, which set that reserve, and on sites with no history. Forecast error is not a goal in itself for this depot.

## 38. The model fixes, confirmed and not (E17)

**Decision.** Build each fix as one change from the reference (`models/lab.py`): the steadier denominator; rolling-origin stopping; bagging; a calibrated quantile bound; the fair form of a count target. The models are trained on every hour of the day. Develop on San Francisco. Confirm once on the two reserved windows.

**Development.** All three real fixes helped on San Francisco, in error and in reserve at the same coverage. The quantile bound did not. It was dropped from the combined arm before the confirmation.

**Confirmation, 0 of 4 bars.** New York gained about a point at every horizon. Chicago lost 0.2 to 1.6 points. New York's spread between draws comes from two storm days in the window and their echo a week later through the ratio target, not from the thinning draw. Coverage fell in both cities under the combined recipe, and ran under 95% in New York for every arm.

**What changed.** The reference stays the default. Bagging is the one fix whose interval excludes zero in both cities, and it is small. The steadier denominator buys a smaller reserve and pays for it in coverage. The bound at depot volume is the open problem: it runs under 95% in New York however the point forecast is built. That, not error, is what the plan pays for (E16).

**What it says about method.** The registered bars asked for both cities. One city passing and one failing is a miss, published as one. Had the test been "either city", it would have passed and said less.

## 39. The reserve, bought cheaply (E18)

**Steer.** The owner said "go" on the question E16 and E17 left: at a required reliability, which forecasting architecture asks the fleet to hold the fewest vehicles?

**Decision.** Separate the point forecast from the bound. Judge each on the reserve–coverage frontier, at matched achieved coverage. Four arms: the reference's bound; a volume-aware bound on the same forecast; Chronos-2 zero-shot with that bound; an ensemble. Exploratory on the two windows E17 had opened, labeled as a second look. Confirmation once on New York yellow taxi, a series no test had scored.

**Result, 2 of 3 bars.** The bound tested was not the answer: the volume-aware bound holds more vehicles than the symmetric one, 52.8 against 40.7. The point forecast was. Chronos-2, used as it comes: 7.7% error on the confirmation series against 9.6% for the model trained here, and 35.7 vehicles in reserve against 40.7. New York data is in the pretrained model's public training corpora, so those figures show that an available component helps, not that it transfers zero-shot. Chicago, whose series postdates the model's training, is the cleaner read and an exploratory one: 6.5% against 8.0%, and 26.3 vehicles against 35.3.

**What changed.** The forecast work stops, as registered. The trained trees stay the controlled reference: locally trained and reproducible from public data. Chronos-2 is the preferred pretrained candidate where its dependency and its provenance are acceptable. The dependency is recorded as an optional group (`pretrained`), the model pinned by commit, the pretraining-overlap caveat written beside every New York figure.

**What it says about method.** E17's finding pointed at the bound. E18 was built to confirm that and found the opposite. A registered test with a wrong premise still earns its keep, if its bars are written so the premise can lose.

## 40. The account, and the sweet spot (E19)

**Steer.** The owner asked for the economics on top: uptime and charging optimization in one financial model; wholesale prices fetched like a public grid map does; the scenario frozen in time; the sweet spot found; done the way an operator would count it.

**Decision.** An account per vehicle-day and per ride (`finance.py`) on a frozen fortnight with every input dated: real rides; the trained forecasts; the tariff; California ISO net demand; emissions; and, new, day-ahead and real-time wholesale prices at the PG&E load point from the system operator's public archive (`data/caiso_prices.py`). The tariff is the base case, because that is what the site pays. Wholesale is a scenario with an assumed delivery charge. Two figures have no public source, a vehicle-year and running a vehicle for a day, and are parameters on the page. A ride is priced the way the service builds its prices (section 44), and a lost ride costs $20 beyond its fare (section 43). A sweep over fleet, feeders, chargers and control (E19). A fourth page mode, "The money", built on the recorded sweep.

**Result, 0 of 4 bars, each miss a finding.** At the required service the best fleet on one feeder is 700 vehicles, and the account pulls one step past it: 800 vehicles earn $8,700 a day more while serving 98.5%, and past 800 it turns hard. The grid saturates before service breaks: at 700 vehicles the feeder is at its limit 98% of the time and service still holds, because batteries carry the day. The plan is ahead of a threshold at 400, 500 and 600 vehicles on one feeder and at every size on two, by its cheaper energy; at 700, where the grid leaves it nothing to move, the threshold earns more. The plan told an hourly price buys 0.7% cheaper than the plan told the tariff, because its price response is the steering around the evening peak, not the price term in its program.

**What changed.** The sweet spot is stated as conditional on required service: 700 vehicles on one feeder under the threshold, $126,200 a day. Among designs serving 99%, the best in the sweep is 1,200 vehicles on two feeders, $219,700 a day, the top of the range swept. The plan's price response is recorded as tariff-shaped, and E20 tests the steering directly.

## 41. The page held to the owner's front-end laws

**Steer.** The owner asked that the front end get a thorough design pass, hold to the owner's front-end rules, and follow the visual style of the service's public site.

**The rules.** Measurable laws asserted by tests and a browser pass: targets of 24 px; contrast against every ground; no overflow; nothing unreachable; no overlapping hit areas; no console errors. Judgment laws raised with the owner. The artifact is the test. Verify on the production build. They live in `web/tests/laws.test.ts` and `npm run measure`.

**What the laws caught.** Teal text at 3.75:1 on white, fine as a marker, not as text. Slider thumbs and the checkbox under 24 px.

**The look.** The page follows the visual style of the service's public site: a light page, one dark stage, mint and blue, a geometric sans (Outfit). It uses no logo or wordmark and no asset of theirs, and the project is independent. `DESIGN.md` records the palette, type scale, radii, spacing and motion as built.

## 42. The plan taught to follow a price (E20)

**Decision.** The plan's steering reads an expensive stretch off whatever price curve it holds: the dearest quarter of the next 24 hours that also sits at least a fifth above the median hour. A quantile alone would sweep up the tariff's off-peak hours, because they tie. The tariff is the special case that must not change.

**Result, 2 of 3.** The tariff path is unchanged to four decimals. The day-ahead arm bought 0.8% cheaper: that fortnight's day-ahead prices, with the assumed delivery charge, were too flat to steer around. Steering by a price the depot does not pay is expensive: billed on the tariff, that arm paid 14% more per kWh. The steering stays in, active when a price curve is given. It will pay where the price has a shape worth paying for.

## 43. The rest of the roadmap, built

**Steer.** The owner asked for the five remaining roadmap items, tested, with the code held to the owner's engineering standard: checks that are cheap, frequent, hard to fake, immediate and non-drifting.

- **A price the plan can follow** (E20, section 42).
- **A cost for a lost ride beyond its fare.** There's a parameter in the account (`finance.Assumptions.lost_ride_cost`, $20) and a third slider on the money page. With it, the sweet spot stops being a bare service floor: a design that drops rides pays for them.
- **The local operator's tool.** `depot-twin app` opens a Streamlit page over `local.run`, a tested function that runs the full model on a design: the Python simulator, the plan told the price of energy, the identified energy figures, and on real days the trained forecasts. The public page runs nothing it cannot show. This runs everything, on the operator's machine.
- **More recorded runs.** Five, listed in `traces/index.json` with a picker in replay mode: the plan and a threshold at 500 and at 1,000 vehicles, and the wrong power rule at 500. The comparison table appears when a run has a partner on the same days.
- **Hosting and release artifacts.** A Pages workflow deploys the built site from `main`. `depot-twin package` gathers the trained models, their bounds, the workbench's scores and the model card (`docs/MODEL_CARD.md`) into one folder, which the release workflow attaches. Nothing in the models comes from the Waymo Open Dataset, and the card says so.

**The front end, held to the owner's laws** (section 41) and measured again after these changes: all five modes, both widths, every target at or above 24 px, no overlaps, no overflow, no console errors.

## 44. What a ride pays

**Steer, twice.** On the money page, the owner saw a flat fare on every ride and asked for a statistical model of what riders pay instead. The first answer fitted a fare line on San Francisco taxi trips and scaled it to the filed trip length and the published average fare. The owner stopped it: a taxi meter is the wrong thing to compare with. The service's own price is what to simulate.

**The price model.** The service publishes how a price is built, not its rates: a minimum, a part for distance, a part for time, an adjustment for demand, quoted before the ride. `fares.py` simulates that structure.

- Rates in the proportions a public price survey reported for the Bay Area service in late 2025 (base $9.52, $1.66 a mile, $0.30 a minute), leveled so that the quiet price of the filed average trip (3.93 miles, 18.4 minutes with a passenger) is the published average fare of $19.69. The scaled rates: $8.70, $1.52 a mile and $0.27 a minute. Labeled a survey's reading, not a rate card.
- Busy pricing read from the twin's own run: each step knows how many vehicles are on the road and how many rides they served, so the share busy is known. Above 80% busy the price rises linearly to a cap of 1.3 at full use, inside the one to three tenths that public descriptions give the service's adjustment. The threshold and the cap are parameters.
- The published average already contains busy pricing. So busy pricing moves the fare between hours and leaves the average over the rides served on the published $19.69. Otherwise a depot that starves its road would be paid more per ride for doing so, with no rider turning away at the higher price.

The taxi records are used for when and where rides happen, never for what they pay. The account reports the mean fare per ride, the mean share busy and the share of steps under busy pricing, so a reader can see which is happening. The E19 record carries the price model's figures under `assumptions.pricing`.

**What the account shows with it (E19).** A ride pays $19.69 on average at every fleet size. The share of steps sold at the busy price runs from 10% at 400 vehicles to 69% at 1,200 on one feeder, and the average fare is the same at both. Scarcity does not pay: a lost ride is only ever a loss, and at $20 beyond its fare it is the figure the service decision turns on. 800 vehicles on one feeder out-earn 700 while serving 98.5%, so the service floor has to be a decision taken against the account, not read off it.

## 45. Names on the floor, tried and taken back

**Steer, twice.** On the page, the owner found the station board under the stage ("Every vehicle through the depot": six lists of names) hard to use beside a floor of dots: the names were in one place, the vehicles in another. The first answer put the names on the floor: every vehicle as a tag with its ID and charge, in the lanes, the queue, the staff area and the bays; the ID written on each charger; a taller stage to make room. The owner looked at it and said no. The floor of dots was better, and the tags had cost it. So the floor went back to the dots exactly as it was. The board stayed, folded: a `details` element the visitor opens when they want the list, drawn only while open.

**Two things kept from the attempt.** The stage "waiting for a person" was the staff's queue - vehicles waiting to be plugged in or unplugged - inside the depot; it reads "Waiting for staff", and in the board "Waiting for staff to plug in", so it can't be read as waiting for riders. The outbound lane was checked: vehicles leave along the bottom lane from the depot to the road, right to left, the arrow at the road end. Laws measured again: all targets at or above 24 px (the chips carry a 24 px minimum), no overlaps, no overflow, both widths.

## 46. The page held to the place

**Steer.** The owner made two points about the page. The twin's physical limits come from its location, and the page should say where that is. And a real site stops where its grid stops. Then, for the other dials, the opposite: let a visitor set 2,000 vehicles or 400 plugs and tell them what the site cannot do, because the page should show site design as well as logistics.

- **The site, named.** A "Site" row in the "What is running" table: the parcel, the feeders, the 95% the load manager draws (section 3), and that the page tells rather than stops, with a pointer to the site notes.
- **The power dial.** Bounded 1 to 5.5 MW, with the two feeder presets: no feeder near the parcel offers more than 4.6 MW, and the two strong ones together 5.5. The gauge reads "of usable".
- **The other dials run free** (chargers to 400), and the side panel carries alerts computed from the design: a fleet the connection cannot sustain, with the power it would need and whether the parcel has it; plugs beyond two per fed one; chargers too few or too many for the fleet's energy; too few people. A second alert reads the running depot: the last day's rides lost and which resource bound them (grid at its limit, vehicles waiting for a plug, waiting for a person, or every vehicle busy). The local tool and the trace recorder hold designs to the plug ceiling.

**The physics behind the page.** Chargers are 93% efficient, applied on the grid side in both simulators; the plan and the account use the same figure. A battery accepts a measured fast-charge curve for one model and a taper for the other, and a charger's kW never exceeds it. The site limit is a hard cap, enforced every step after the control rule has spoken, and every recorded run is checked for a draw over the usable figure. The battery buffer has a 90% round trip applied once and a 10% floor, and charges only from spare grid power. People are one shared pool for plugging in, unplugging and cleaning. Two stated limits: there is no cap on vehicles waiting in the yard, since 14.5 acres hold far more than the queue reaches in any recorded run; and whether both strong feeders would serve one parcel is not verified.

## 47. Three targeted changes to the page

**Steer.** The owner asked for three things: a title that says which depot runs and a subtitle of one or two sentences on what the simulation is; charger power as real charger classes rather than a slider; and, when a vehicle is followed, a drawing of it acting out what is going on instead of a list, for the visitor's pleasure.

- **Title.** "A robotaxi depot in East Oakland, running", and under it: a simulation of one depot on a real parcel, vehicles leave the road to charge and be cleaned and go back out, change the fleet, the grid, the chargers or the rules and watch what backs up.
- **Charger classes.** Level 2 at 19 kW (AC; the vehicle's own charger sets 11 kW, and the browser simulator applies that limit), fast at 60 kW, fast at 150 kW, high power at 350 kW. The 60 kW class is the default because a working robotaxi depot was reported with 38 chargers of about 60 kW on roughly 2.4 MW, which is the shape of this site; the two vehicle models accept at most about 100 and 150 kW, so the 350 kW class is there to show that more charger than battery buys nothing.
- **The followed vehicle, drawn.** An authored SVG robotaxi (no logo) on a piece of the night stage, one scene per place, CSS motion only, still under reduced motion; one caption in the depot's words; the visit log under it (`web/src/views/vehicle.ts`; the scenes are in `DESIGN.md`). The first drawing was flat and the owner said so ("a kid drawing"); the second is shaded with gradients, a glare on the glass, lit rims and a blurred shadow, and the mint fill inside the body went, the battery bar being enough. The alerts lost their coloured left rule at the same time, which the design floor refuses, and gained a short lead instead.

Laws measured again: all targets, both widths.

## 48. Why the model workbench shows the same rides for every model

**Steer.** On the model page the owner could not see a difference between the trained model, no model and the pretrained one, and asked why.

**The forecast is in the loop.** The two fault variants, which break the feed, come out with the bound held in 0% of hours and no reserve, and the guarded one hands over to the simple rule. The energy cost and the share bought at the peak price differ between the real variants: $0.1680 a kWh for the reference, $0.1716 for last week's curve, $0.1682 for the pretrained model; 10.55%, 12.17% and 10.66% at the peak price.

**The arithmetic.** On the fortnight the variants are run on, the busiest hour of the source series held 589 rides. Scaled to the run, which offers about 12,650 rides a day against the series' 7,300, and at 23 minutes a ride, that is about 390 vehicles on the road; the depot's 66 chargers take about 100 vehicles off the road at once; the fleet is 500. So the fleet just covers the busiest hour whatever the forecast says, and rides served do not depend on it. This is E16's finding again, with the arithmetic beside it. What the forecast decides is when the plan charges, which is the energy bill, and how many vehicles its bound holds back, which is the reserve: last week's curve costs about $174 a day more in energy than the trained model and holds 62.9 vehicles against 48.5; the pretrained model holds 46.1.

**The fortnight is not the 60 days.** The headline scores are over 60 held-out days (the trained model 11.4% error at one hour, "same hour last week" 14.9%, the pretrained model 8.4%). The depot is run on one fortnight, 15 to 28 April 2024, and on that fortnight the trained model and last week's curve are nearly indistinguishable, 10.8% and 11.1%; the pretrained model scores 8.1%. A quiet April fortnight flatters the simple rule, and the depot run sees only the fortnight.

**What the page does with it.** The model mode shows the error on the fortnight beside the 60-day score, and says when the two disagree and by how much. Moving a dial while another is off the reference says that the other went back, because each model was built with one change and two cannot be combined. The arithmetic paragraph is computed from the recorded fortnight (`depot` figures in `models.json`, from `workbench.assemble`), with the share of energy bought at the peak price and how often the bound held in the run. The page shows the figures that move beside the one that cannot.

## 49. The model page as six questions

**Steer.** The owner judged the work under the model page stronger than the page made it look. Keep "what the plan did with it" and the arithmetic of why rides do not move; add, compactly, the split, calibration against sharpness, a qualified feature importance, failure slices, the E18 comparison with its honesty line, and a model card; change the chart copy when the 3,000-tree variant is chosen; put the reserve's formula on the page; add nothing for show. The owner's condition: pure clarity, the least text for the message.

**Three cities, read the same way.** The E18 panel shows San Francisco beside New York and Chicago, all at matched achieved coverage, E18's rule. On San Francisco the pretrained model holds 37.0 vehicles against the reference's 52.6. The pretrained forecasts for San Francisco are made in the trust step.

**Built.** `trust.py` fits the reference once and writes `web/public/trust.json`: the four blocks' dates and rows; error by slice on the 60 held-out days (time of day, weekday and weekend, demand quartiles, holidays) for the model and for last week; feature importance by XGBoost gain and by permutation loss on the calibration block; the reference bound's reserve frontier on this city beside E18's frontiers; the model card's facts. The page is six questions in order: what it predicted; is it better (the three-city table, the horizons bars, requested against achieved coverage with the vehicles held at each point); can the score be trusted (the split as a time line, one sentence); where it fails (the slice table); what it uses (gain and permutation side by side, one qualifying sentence); what it buys (the arithmetic, the plan's figures, the money, the reserve formula). The card closes it with three lines on what the model is not. The learning-curve caption changes with the variant chosen. The error-by-hour chart went, the slices carry it.

**What the slices say.** The model is worth most where last week's curve is worst: holidays (13.8% against 52.8%, on the one holiday in the block, 27 May 2024), weekends (10.5% against 18.1%), midday (8.1% against 14.5%). It is barely ahead at the evening peak (13.8% against 14.2%) and behind late at night (16.1% against 15.2%). Permutation puts the minute of the day first (+9.1 points when shuffled) and the mean rate over the last day just behind it, where gain puts the rate now against last week first: lagged features share credit under gain, which is the reason both are shown.

## 50. The forecast page cut to three questions

**Steer.** The evidence was all there and all at the same weight, so a reader met controls, curves, tables and a card before any conclusion. The owner asked for a default page that answers three questions (is the forecast better; can the comparison be trusted; does it change the depot) and put everything else one click deeper; replace prose deltas with figures; one chart of accuracy against reserve with a city chip; move the broken-feed dial out of the model controls; a toast for the one-dial rule; shorter tab names.

**Two choices on the way.** The tabs are Depot, Recorded run, Forecast, Money. The chart of accuracy against reserve reads all three cities at matched achieved coverage.

**Built.** The page opens with the question, four figures (error, vehicles held, bound held, error on the run's fortnight) with deltas against the reference and none when the reference is chosen, and one trust line. The dials, with the feed dial under "Break the forecast". Accuracy against reserve for one city at a time, three dots, one sentence and the corpus caveat where it applies. What it changes at the depot: the arithmetic, four figures, the conclusion, and the rest under "Full depot outcomes". Then folds: "How we know the score is real" (the split, the horizons, the fortnight chart, and under it "Why 725 trees" with the curve and the Poisson reference as a methodology note, and "Requested against achieved coverage"); "Where it fails", whose heading carries the worst slice; "What it learned" with permutation first and gain second; "Model card".

## 51. The story, and a fifth tab

**Steer.** The owner found the forecast page's head crowded (the trust line and the dials' note ran together) and asked for a one-page story beside the money: the problem, the product choices, the ML choices, what went wrong, what changed, what it found, in the shape of a short post with a summary first and a few sentence-case headings.

**Built.** The head got its room: one trust sentence under a rule, the dials under their own heading. `docs/STORY.md` is the story, a summary first and four sections. The site renders it at build time beside the README page (`web/scripts/readme.mjs` renders both and writes a fragment), and a fifth tab, Story, takes it in place; the tab bar wraps at phone width. Laws measured on all five modes at both widths.

## 52. One page, one selected model

**Steer.** Parts of the page described the chosen experiment while others silently stayed on the reference (the slices, the importances and the card were the reference's whatever was selected), and a careful reader would distrust the numbers. The owner asked for one rule: everything describes the selected model, and whatever is the reference says so.

**The full option.** Labelling the reference would have been the cheap way. The full one was taken, because the figures cost ten minutes of CPU.

**Built.** `depot-twin data trust` refits every workbench variant at one hour and records for each its error, its slices, its two importances, its reserve frontier and a card; the fault variants share the reference's forecast and are left out. The page follows the selection throughout: a "Selected" strip under the headline with the error and reserve deltas; both deltas on the headline (against last week and against the reference); the selected model as a fourth dot on the San Francisco chart with its own sentence; "Where this model fails", "What this model learned" (error rise first, five rows, the rest on request) and "This model, on a card" with the reference beside it. The controls are two groups, model experiment and operational failure test. The ride-count variant's note says trees extrapolate poorly beyond the count levels in their training rows.

## 53. What the filings count: footprint, chargers, sessions

**Steer.** The owner asked what known data patterns hold for modelling a new city's dynamics, without a rabbit hole. Three do: the ramp of a new city, a concentration curve across areas, and a "dominant driver or mixed" rule; the bandit, SHAP, uplift and cohort scoring do not, for want of rider-level data. Then: do the study and the plan.

**What the filings turned out to hold.** Waymo's quarterly filings to the CPUC redact trips by tract, charger power and session length. They do not redact the list of census tracts served each month, the number of chargers, or the number of charging sessions, and the Census Bureau publishes every tract's 2020 population and centroid without a key. `data/footprint.py` reads six quarters (2025 Q1 to 2026 Q2): the footprint grew from 1,496 tracts and 5.7 million residents to 1,796 and 7.2 million in 2025 Q3 and then held; trips a resident a month rose from 0.106 to 0.197; chargers from 138 to 324; a vehicle charged once every 9.3 trips at the start and every 7.5 at the end; each charger saw 14 to 21 sessions a day. Charging data covers the whole passenger fleet, pilot and deployment, and the record says so.

**What that said about the twin.** How often a vehicle visits the depot was an unknown. The filings say about three times a day in short sessions, where the twin under long sessions visits 1.3 to 1.5 times for about an hour, and the twin's own sensitivity study finds that 2.5 visits a day cost 13 points of rides. That is the brief's "what would prove this wrong" with a number against it. Two tests were registered before any run: E22, whether the twin can reproduce the real cadence with plausible settings and whether its findings hold under it; E21, what the service area around the parcel asks of the depot and when, from penetration and the census. E22 first, because it could move every capacity figure E21 would size against.

## 54. The real cadence (E22) and the East Bay's demand (E21)

**E22, 4 of 4.** The charge level that calls a vehicle in decides cadence; the drive to the depot hardly matters; cleaning on every visit is what breaks. Called in at 55% and cleaned every fourth visit, with a five-minute leg, the twin makes 3.2 visits a vehicle-day of 8.0 trips each, against the filings' 7.5 to 8.5, and serves 100.0% of rides at 500 vehicles; the same call-in level with a wash on every visit serves 87.7%, because the bays bind. So the depot model has `clean_every`: a vehicle is cleaned on every Nth of its own visits, and inspected on every tenth. At the filings' cadence the power rule matters more (in-order feeding serves 86.1% of rides at 1,000 vehicles against 77.0% for emptiest-first, 9.1 points, where long sessions give 5.9), the plan on 30-minute slots buys energy 6.9% cheaper at level rides, and the one-feeder capacity at the 99% floor reads 600 where long sessions give 700. The 600 is capacity under the threshold rule, which calls vehicles in at 55% whether or not a charger is free; a rule that waits for a free charger might carry more. A capacity figure says which cadence it is for. The page's capacity figures read at the filings' cadence, and the browser simulator's defaults are the chosen setting.

**E21, 1 of 3.** Penetration 0.169 trips a resident a month over the last four quarters, growing 5.2% a month at a constant footprint. The East Bay within 20 km of the parcel (1.08 million residents) produces about 6,000 rides a day today: 241 vehicles, well inside one feeder's 600. At the measured growth the second feeder is needed in 19 months; at half the growth, 36. The density adjustment across donor areas was registered and not built (the New York areas have no population table), and the level stands on penetration alone, which is more likely high than low for a service area sparser than the served footprint. The two misses are the registration's: the ramp is faster than it assumed, and the density fit is owed.

**What changed on the page.** The depot mode gained "Where the rides come from": three service areas around the parcel as chips, each with residents, rides a day at today's penetration, the vehicles that is, the feeders it needs, and the month the second feeder is due at the measured growth and at half of it; a button sizes the fleet to the area. The areas are named for what they hold: 8 km is East Oakland, San Leandro and Alameda; 15 km is Oakland, Emeryville and Hayward; 20 km is Alameda County's East Bay to Union City. The circles are straight-line distance over Alameda County tracts; 83 San Francisco tracts across the bay and 33 in Contra Costa fall inside 20 km (418,000 residents) and are left out, which the page and the record say. The browser simulator cleans every fourth visit and calls vehicles in at 55%, as E22 settled, with the visits a vehicle-day shown beside the floor. Scoreboard: 23 tests, 54 of 95 bars.

## Standing limits

- Energy per mile is estimated, not measured.
- Demand comes from taxis in one city and ride-hail in another; it records trips served.
- The site is real; the depot on it is hypothetical; nothing here says the parcel is available.
- Prices are public figures and stated assumptions; the money figure is the depot's contribution, not the service's profit.
