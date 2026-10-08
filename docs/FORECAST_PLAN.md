# Where the project stands, and the plan for the forecast

**Three parts: what is built, where it stands, and the plan for the ride forecast with how it came out.** Figures come from the result files in `data/derived/`; registrations and results live in `EVALS.md`; decisions are in `docs/BUILD_LOG.md`. If you're cloning the repository to follow along, read those three alongside this.

## 1. What is built

**The twin.** It's a simulation of one depot and the driverless fleet that works out of it: rides served on the road, vehicles called in, a queue for chargers, charging under a site power limit with each battery's own charge curve, people who plug in and clean, cleaning bays, the drive in and out. The site is a real 14.5-acre parcel in East Oakland, with the 2.75 MW of headroom PG&E publishes for each of two feeders. The depot on it is hypothetical. Demand is replayed from real San Francisco taxi days, scaled to the fleet. Each vehicle's energy use is estimated from its own telemetry during the run, not taken from its type.

**The controller.** Model predictive control. Every hour a linear program plans the next 24 hours against the forecast's upper bound - how many vehicles to call in each hour, what to keep on the road - acts on the first hour, then plans again an hour later. It commits each hour to a number of vehicles on the road, and that promise is checked. Told the price of energy, it moves charging out of the 4 pm to 9 pm peak. A guard hands control to a simple threshold rule if the forecast's bound keeps breaking.

**The forecasts.** Gradient-boosted trees (XGBoost), one model each for 1, 6 and 24 hours ahead, predicting the ratio of a coming hour's rides to the same hour last week, with an upper bound measured on days held back from training. A fourth model for the hour under way exists as an option. A cross-city version, trained on New York, Chicago and San Francisco without a city identifier and told the size of the place, serves a site with no history.

**Demand for a place with no history.** A generator that borrows the weekly shape, holiday pattern, rain response and week-to-week variation of donor cities of the same kind of place, at a level the planner sets. `depot-twin new-site` builds the forecast and the demand files for a new site in one command.

**The front end.** A static page with five modes. Play is a simulator in the browser with the fleet, grid power, chargers, charger power, people, both power rules and the calling rule on sliders; every vehicle is named and can be followed through its visit. Replay is a run recorded from the full Python model on real days, with the trained forecast, the plan hour by hour over the plans before it, a comparison with a fixed threshold on the same days, and a real week of California grid data beside the depot's draw. Forecast is the forecast built fourteen ways, one change at a time, each scored on held-out days and each handed to the plan. Money is the account for a recorded design. Story is one page on the problem, the choices and what it found.

**The evidence.** Twenty-three registered tests, each written down with pass bars before it was run; 54 of 95 bars passed; misses published. Six studies without bars. Every result file stamped with the code it ran on. Pinned regression numbers, invariant tests, a generated scoreboard, CI with a web job. Documents: README, brief, build log, training notes, related work, site notes, product and design records.

## 2. What it found

| Finding | Figure | Where |
|---|---|---|
| Feeding the emptiest vehicle first is the wrong rule when power is short | 77.0% of rides served against 86.1% for in-order feeding at 1,000 vehicles on one feeder (82.9% against 88.8% under long sessions); the gain is 3 to 6.5 points depending on staffing; repeated on Chicago days | E22, E11, staffing study, E14 |
| Why: finished vehicles wait on chargers for a person, and site power goes unused | 7.5% of site power unused with 25 people | Staffing study |
| Any fixed order at full rate does as well; the textbook rule ties in-order feeding | 85.4% against 85.3% | E14 |
| The site's capacity is a number of rides | One feeder carries about 600 vehicles at 25 rides each at the filings' cadence, 700 under long sessions; at 18 rides each, 800 serve every ride | E22, sensitivity study |
| The day-ahead plan buys no rides, and cheaper energy | 12.2% cheaper per kWh at 500 vehicles under long sessions, 6.9% at the filings' cadence, no loss of rides; 12.3% of energy bought in the peak against 23.9% | E12, E22 |
| The plan's results do not depend on the forecast at this depot | Identical rides served at 700 and 1,000 vehicles with perfect foresight, the model, last week's curve or the forecast cut to a third | E16 |
| A forecast can be built for a site with no history | Beats "same hour last week" in seven of nine held-out cells and passes 1 of 4 bars; bounds too narrow with one donor city | E13 |
| Generated demand is kinder than real days | Average scenario 1.0 to 3.9 points too kind; the worst of ten is a safe reading | E15 |

## 3. Where it stands

- The forecast work is closed as registered: E16 3 of 4 bars, E17 0 of 4, E18 2 of 3.
- The trained trees stay the default. Chronos-2 is the preferred pretrained candidate where its dependency and its provenance are acceptable.
- The first-version code is kept in `depot_twin/first_version/`.

## 4. The forecast: what the error is, and what it is not

**The figures.** On 60 San Francisco days never used in training, the one-hour forecast is off by 11.4% of rides; "same hour last week" by 14.9%. At six and 24 hours ahead: 11.9% and 12.3%. The upper bound, sized to hold 95% of the time, holds 92.8%.

**A reference point, not a floor.** Under a Poisson counting model, sampling variation alone sets an error that falls as volume rises. Real demand is more variable than Poisson: correlated arrivals, events, level shifts, censoring by supply. So the irreducible error is at least that and probably more. How much of the 11.4% is reducible, I don't know. Counting noise says only that it cannot be all of it.

**What the workbench showed.** The reference is not the best of its own variants on the held-out days: 50 trees scores 9.8%, six months of history 10.1%, no weather 10.6%. The reference's stopping point was chosen on earlier days that contain a jump in the level of rides, and it stopped too late. These variants were scored after the reference was set, so adopting one of them on this evidence would be tuning on the test set. They do say what to change.

**Where it would show.** At this depot the plan's rides served, promises kept and energy cost hardly move with the forecast. A better forecast shows up as a narrower bound and fewer vehicles held in reserve on the road: 50 with the model against 64 without, for a fleet of 500 (E16). It matters more at a site short of vehicles than at one short of energy.

## 5. What was explored for the plan

**Public data on Hugging Face.** Searches for taxi, ride-hail, mobility demand, EV charging and fleet data found mostly unrelated or unvetted uploads. Three sources are usable.

| Source | What | Licence | Use |
|---|---|---|---|
| Traffic-Demand-Bench (tjtrans) | Hourly taxi and bike pickups by zone: New York (taxi from 2014), Chicago, the Bay Area, Boston, Toronto; a benchmark with published results | MIT | More donor zones; a benchmark to stand on |
| Porto taxi (kraina) | A year of trips from 442 taxis, 2013 to 2014 | CC BY 4.0 | A fourth, less dense donor city |
| Uber/Lyft Boston demand (mozgor19) | Trip-level, no licence stated | None | Not usable |

**The benchmark's result.** On Traffic-Demand-Bench, across all seven systems and three horizons, the best forecaster is a pretrained time-series foundation model used with no training on the city: Chronos-2 (Amazon, Apache 2.0), at 0.61 to 0.72 of the weekly-average rule's error, ahead of every model trained on the city. Our "same hour last week" rule is close to that weekly-average rule and scores 14.9%, which suggests 9 to 10% is reachable on our series from this model alone. TimesFM (Google) and Moirai (Salesforce) are the other candidates. The small Chronos sizes run on a CPU.

**Synthetic data, honestly.** It adds no information that isn't already in the donors, and our own tests say so: E13 found generated demand raised the forecast's error in seven of nine cells beside donors alone; E15 found generated weeks kinder than real ones. Where it earns its place is a site with no history, rare regimes (level shifts, holidays, outages), and stress scenarios for the twin. It must be set up so it can never enter a validation or test set.

## 6. The plan

### Phase 0: data setup (1 day)

This comes before any model changes, because a bad set here corrupts everything after it.

A data card per source: period, granularity, licence, known issues. Some are known already: San Francisco had up to 15% exact duplicate records, removed by exact match; Chicago rounds to 15 minutes; and every taxi and ride-hail record is trips served, not trips wanted, so demand is censored wherever supply was short.

Checks that run in CI: no feature reaches past the forecast time; every series on a regular index with gaps marked, never filled; local time with daylight saving handled; one holiday calendar; level shifts detected and flagged with their dates.

A split registry: which days and which cities are development, validation and test, written once, read by every experiment. Provenance on every row - real or synthetic, source, generator version. Synthetic rows may only enter training.

### Phase 1: the model fixes (1 day)

In order of expected gain, each one change.

1. A steadier denominator: the ratio to the mean of the same hour over the last four weeks, not to one noisy hour last week.
2. Rolling-origin validation over several blocks to decide when to stop adding trees, instead of one block that contains a level shift.
3. Bagging: several models on different seeds and row samples, averaged.
4. Quantile models for the bounds (pinball loss), sized per hour of day, instead of one symmetric margin.
5. A few more features: the same hour two and three weeks back, a seven-day same-hour median, the day before and after a holiday.
6. Pool the cities with the size feature.

On San Francisco's development days the three fixes kept each lowered the error (E17).

### Phase 2: foundation models as a second forecaster (1 day)

Run Chronos-2 and TimesFM zero-shot under our own protocol on our own held-out blocks, with weather as a covariate where the model takes one. Then as an ensemble member with the trees. Pin the model files as a dependency and record their versions. On the confirmation series Chronos-2 has 7.7% error against 9.6% for the trees (E18).

### Phase 3: one model for all sites (1.5 days)

Add Traffic-Demand-Bench's zone series and Porto to the donor panel; label each series by kind of place and size; train one pooled model with the size feature already in `models/transfer.py`. A site becomes a set of covariates instead of a separate model. Tested by holding cities out, as E13 does. It pays most at a new site.

### Phase 4: synthetic demand from a fitted statistical model (1.5 days)

Replace the current generator with a model fitted per donor zone: negative-binomial counts, weekly and yearly seasonality, weather and holiday effects, an autoregressive remainder. The fitted parameters form a library, and a new site draws from it. Validation: train on synthetic and test on real; the E15 worst-scenario test on the depot; distribution checks of shape, spread and persistence. It isn't expected to lower in-city error, and the plan doesn't promise that.

### Phase 5: registered tests (within the phases above)

San Francisco's days are all used, so confirmation runs on New York and Chicago thinned to a depot's volume, on windows that end before E13's test days. Three tests, bars written before any run:

- E16: decision regret, the plan with perfect foresight, the model, last week's curve and a broken feed
- E17: the model fixes against the reference
- E18: Chronos-2 and the ensemble against the trees, on the reserve the bound asks for

### What the plan is measured on

**The primary measure is decision quality, not forecast error.** Every forecast gets scored twice: a forecast scoreboard (error by horizon, at the peak, under-forecasting, bound coverage and width) and an operations scoreboard (rides served, energy cost, vehicles held in reserve, promises missed, guard take-overs, peak grid draw). The headline test becomes decision regret: the plan run with perfect foresight, with the model, with last week's curve and with a broken feed, across regimes where energy binds and where vehicles bind. The hypothesis, from the workbench, is that the value of forecast accuracy depends on which constraint binds.

**The bound is defined twice.** Commitment coverage is the chance the next hour's rides stay under the bound, which is what the promise needs. Planning-horizon exceedance is the chance that some hour in the next 24 breaks it; reported but not targeted, because the plan is redrawn every hour and only its first hour acts.

**Quantile models get a calibration layer** on the calibration block, with sharpness - bound width over forecast - reported beside coverage.

**A direct-count model with trailing-level normalization is the comparator** to the ratio target, not raw counts, which lost twice already (E7, the workbench).

**Comparisons use paired days with block-bootstrap intervals**, not pooled hourly errors treated as independent.

**San Francisco results are development evidence.** Only New York and Chicago, on windows not yet looked at, confirm anything.

**Weather is labelled by what is known at forecast time.** The calendar and tariff are known; temperature and rain are the forecasts issued at the time, from Open-Meteo's archive of past forecasts, as now. Observed future weather is never used.

**Chronos-2 is a benchmark, not proof of transfer.** New York taxi series are in public pretraining corpora. Dataset, code and model versions pinned by commit.

**Phase 4 is deferred.** Synthetic demand isn't the bottleneck, and when it's rebuilt it gets a shared city-wide factor so surges stay synchronised across zones.

**Not in this plan: a surrogate-optimum verification loop.** The first version has one (E4, E5); its surrogate was too uncertain near the service level to choose. Building it for the current simulator is a separate day's work.

The order: Phase 0; decision regret (E16); the forecast fixes with the count comparator, rolling-origin stopping and calibrated quantile bounds (E17); Chronos-2 and the ensemble (E18); then a checkpoint that asks four questions. Did error improve, did calibration improve, did the reserve improve, did the depot's results improve. If the first three improve and the fourth does not, the forecast work stops there, and that is the finding.

### Order, and what to decide

| Phase | Days |
|---|---|
| 0: data setup | 1 |
| 1: model fixes | 1 |
| 2: foundation models | 1 |
| 3: one model for all sites | 1.5 |
| 4: synthetic, fitted | 1.5 |

How it came out: Phases 0 to 2 ran, and the forecast work stopped at the checkpoint, as registered in E18. Phases 3 and 4 did not run. Still open:

1. Whether to take a dependency on a pretrained model (Chronos-2, Apache 2.0) or stay with trees only.
2. Whether Phase 4 is worth its day and a half, given that its value is at new sites and in stress scenarios, not in the San Francisco figure.

What matters in this plan isn't the model. It's what counts as a win.
