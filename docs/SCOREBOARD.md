# Scoreboard

Generated from the result files by `depot-twin scoreboard`. Do not edit by hand. Each test was
written down before it was run; the registrations, results and what each one means are in
[EVALS.md](../EVALS.md).

**23 tests run. 54 of 95 bars passed.**
A missed bar is a result, not an omission.

All 23 records were made by the code in this tree: each carries a stamp of it, and `depot-twin stale` checks.

| Test | Question | Bars passed | Record | Note |
|---|---|---|---|---|
| E1 | Does a week-ahead demand forecast beat "same hour last week"? | 0 of 1 | current |  |
| E2 | Do smarter recall rules serve more rides on a power-constrained depot? | 3 of 5 | current | every rule ran with a power rule E11 showed to be the wrong one |
| E3 | Can gradient-boosted trees stand in for the simulator? | 4 of 6 | current | runs measured two quiet weekdays; rebuilt as E4 |
| E4 | Can the stand-in be trusted with a search over depot designs? | 5 of 7 | current |  |
| E5 | Does retraining on what the search picks fix the search? | 1 of 3 | current |  |
| E6 | Can each vehicle's energy use be recovered from its telemetry? | 3 of 4 | current |  |
| E7 | Can rides be forecast 1, 6 and 24 hours ahead, with honest bounds? | 0 of 9 | current |  |
| E7b | Does forecasting the ratio to last week fix E7? | 5 of 9 | current |  |
| E8 | Does the heartbeat controller beat filling every free charger? | 4 of 5 | current | read with E11: the gain came from the power rule, not the plan |
| E9 | Can the depot keep an hourly promise, and does E8 repeat on fresh days? | 4 of 4 | current |  |
| E10 | Does a guard catch a broken forecast and limit the damage? | 2 of 3 | current |  |
| E11 | Which part of the controller delivers the gain? | no bars (attribution) | current |  |
| E12 | Does a plan that knows the price of energy cut its cost at equal service? | 4 of 4 | current |  |
| E13 | Can a forecast be built for a place with no ride history? | 1 of 4 | current |  |
| E14 | Do the power-rule findings hold on another city's days? | 4 of 4 | current |  |
| E15 | Is the worst generated scenario a safe reading of a constrained depot? | 2 of 2 | current |  |
| E16 | What is a forecast worth to the plan, and does that depend on what binds? | 3 of 4 | current |  |
| E17 | Do the model fixes tighten the bound and cut error on days held back for it? | 0 of 4 | current |  |
| E18 | At a required reliability, which forecast asks the fleet to hold the fewest vehicles? | 2 of 3 | current |  |
| E19 | Where is the sweet spot, and what binds on either side of it? | 0 of 4 | current |  |
| E20 | Can the plan follow an hourly price? | 2 of 3 | current |  |
| E22 | Does the twin survive the real visit cadence? | 4 of 4 | current |  |
| E21 | What does East Oakland ask of a depot, and when? | 1 of 3 | current |  |

## Bars missed

- **E1**: bar
- **E2**: 2a plan no worse than headroom at 500
- **E2**: 2b plan within half pt of headroom at 1000
- **E3**: 4 test at most 1.3x validation
- **E3**: 6 picked designs hold up in simulation
- **E4**: 4 regret and top50 hold in every case
- **E4**: 6 robust design holds in 18 of 20
- **E5**: 1 regret and top50 hold in every case
- **E5**: 2 first pick truly serves 99pct
- **E6**: 2 always on median error at most 5pct and half the nominal
- **E7**: 1h 1 removes 15pct of best baseline error
- **E7**: 1h 2 upper bound holds 93 to 97pct
- **E7**: 1h 3 not low by more than 3pct at peak
- **E7**: 6h 1 removes 15pct of best baseline error
- **E7**: 6h 2 upper bound holds 93 to 97pct
- **E7**: 6h 3 not low by more than 3pct at peak
- **E7**: 24h 1 removes 15pct of best baseline error
- **E7**: 24h 2 upper bound holds 93 to 97pct
- **E7**: 24h 3 not low by more than 3pct at peak
- **E7b**: 1h 2 upper bound holds 93 to 97pct
- **E7b**: 1h 3 not low by more than 3pct at peak
- **E7b**: 6h 3 not low by more than 3pct at peak
- **E7b**: 24h 3 not low by more than 3pct at peak
- **E8**: 2 ledger kept 95pct of hours
- **E10**: 3 guarded serves at least as many under the fault
- **E13**: beats best naive in all 9
- **E13**: within 1.25x in city in 7 of 9
- **E13**: upper bound holds 90 to 99 in all 9
- **E16**: 2 vehicles bound foresight worth 1 point and model recovers half
- **E17**: 1 all fixes lower error 1h both cities interval excludes zero
- **E17**: 2 all fixes coverage 93 to 97 both cities
- **E17**: 3 all fixes fewer reserve vehicles at no lower coverage both cities
- **E17**: 4 all fixes lower error at 6h and 24h both cities
- **E18**: 1 B holds fewer vehicles than A at 95 achieved
- **E19**: 1 sweet spot inside the range on one feeder
- **E19**: 2 plan beats threshold wherever both meet service
- **E19**: 3 grid binds where service breaks on one feeder
- **E19**: 4 plan on day ahead prices buys 10pct cheaper under that scenario at 500
- **E20**: 1 day ahead steering buys 10pct cheaper under day ahead prices rides within 0.2
- **E21**: 1 density fit loo within 35pct on six of nine with positive elasticity
- **E21**: 3 second feeder between 24 and 120 months out
