# Scoreboard

Generated from the result files by `depot-twin scoreboard`. Do not edit by hand. Each test's bars
were fixed before its run; the registrations, results and what each one means are in
[EVALS.md](../EVALS.md), and each test below links to its section there.

**35 tests run. 96 of 145 bars passed.**
A missed bar is a result, not an omission.

All 35 records were made by the code in this tree: each carries a stamp of it, and `depot-twin stale` checks.

| Test | Question | Bars passed | Record | Note |
|---|---|---|---|---|
| [E1](../EVALS.md#e1-week-ahead-demand-forecast) | Does a week-ahead demand forecast beat "same hour last week"? | 0 of 1 | current |  |
| [E2](../EVALS.md#e2-recall-rules-on-a-power-constrained-depot) | Do smarter recall rules serve more rides on a power-constrained depot? | 3 of 5 | current | read with E11: these rules ran with power to the emptiest vehicle first |
| [E3](../EVALS.md#e3-a-fast-stand-in-for-the-simulator) | Can gradient-boosted trees stand in for the simulator? | 4 of 6 | current | read with E4: these runs measure two weekdays, E4 a full week |
| [E4](../EVALS.md#e4-a-planner-that-can-be-trusted-with-the-search) | Can the stand-in be trusted with a search over depot designs? | 5 of 7 | current |  |
| [E5](../EVALS.md#e5-teaching-the-planner-where-it-searches) | Does retraining on what the search picks let the search choose? | 1 of 3 | current |  |
| [E6](../EVALS.md#e6-identifying-the-twin-from-telemetry) | Can each vehicle's energy use be recovered from its telemetry? | 3 of 4 | current |  |
| [E7](../EVALS.md#e7-ride-forecasts-for-the-controller) | Can rides be forecast 1, 6 and 24 hours ahead, with honest bounds? | 0 of 9 | current |  |
| [E7b](../EVALS.md#e7b-the-same-forecasts-on-a-scale-free-target) | Does forecasting the ratio to last week pass E7's bars? | 5 of 9 | current |  |
| [E8](../EVALS.md#e8-the-heartbeat-controller) | Does the heartbeat controller beat filling every free charger? | 4 of 5 | current | read with E11: the gain came from the power rule, not the plan |
| [E9](../EVALS.md#e9-a-ledger-that-keeps-its-word-and-e8-again-on-fresh-days) | Can the depot keep an hourly promise, and does E8 repeat on fresh days? | 4 of 4 | current |  |
| [E10](../EVALS.md#e10-a-guard-for-when-the-forecast-breaks) | Does a guard catch a broken forecast and limit the damage? | 2 of 3 | current |  |
| [E11](../EVALS.md#e11-taking-the-controller-apart) | Which part of the controller delivers the gain? | no bars (attribution) | current |  |
| [E12](../EVALS.md#e12-does-a-plan-that-knows-the-price-of-energy-earn-its-place) | Does a plan that knows the price of energy cut its cost at equal service? | 4 of 6 | current |  |
| [E13](../EVALS.md#e13-can-a-forecast-be-built-for-a-place-with-no-ride-history) | Can a forecast be built for a place with no ride history? | 1 of 4 | current |  |
| [E14](../EVALS.md#e14-do-the-power-rule-findings-hold-on-fresh-days-from-another-city-and-does-the-textbook-rule-beat-in-order-feeding) | Do the power-rule findings hold on another city's days? | 4 of 4 | current |  |
| [E15](../EVALS.md#e15-is-the-worst-generated-scenario-a-safe-reading-of-a-constrained-depot) | Is the worst generated scenario a safe reading of a constrained depot? | 2 of 2 | current |  |
| [E16](../EVALS.md#e16-what-is-a-forecast-worth-to-the-plan-and-does-that-depend-on-what-binds) | What is a forecast worth to the plan, and does that depend on what binds? | 3 of 4 | current |  |
| [E17](../EVALS.md#e17-do-the-changes-to-the-model-improve-the-forecasts-bound-and-does-that-hold-on-days-held-back-for-it) | Do the model changes tighten the bound and cut error on days held back for it? | 0 of 4 | current |  |
| [E18](../EVALS.md#e18-how-cheaply-can-the-fleet-buy-a-required-level-of-demand-certainty) | At a required reliability, which forecast asks the fleet to hold the fewest vehicles? | 2 of 3 | current |  |
| [E19](../EVALS.md#e19-where-is-the-sweet-spot-and-what-binds-on-either-side-of-it) | Where is the sweet spot, and what binds on either side of it? | 0 of 4 | current |  |
| [E20](../EVALS.md#e20-can-the-plan-follow-an-hourly-price) | Can the plan follow an hourly price? | 2 of 3 | current |  |
| [E22](../EVALS.md#e22-does-the-twin-survive-the-real-visit-cadence) | Does the twin survive the real visit cadence? | 4 of 4 | current |  |
| [E23](../EVALS.md#e23-what-does-one-feeder-carry-with-what-spread-and-under-which-calling-rule) | What does one feeder carry, over many weeks and seeds, under three calling rules? | 4 of 4 | current |  |
| [E25](../EVALS.md#e25-is-the-fleet-halfway-between-the-one-carried-and-the-one-only-served-carried-too) | Is the fleet halfway between the one carried and the one only served carried too? | 4 of 4 | current |  |
| [E26](../EVALS.md#e26-what-does-one-feeder-carry-if-the-vehicles-use-more-energy-than-estimated) | What does one feeder carry if the vehicles use more energy than estimated? | 5 of 5 | current |  |
| [E27](../EVALS.md#e27-what-does-one-feeder-carry-if-a-parked-vehicles-systems-stay-on) | What does one feeder carry if a parked vehicle's systems stay on? | 3 of 3 | current |  |
| [E28](../EVALS.md#e28-how-far-does-the-plan-of-600-hold) | How far does the plan of 600 hold? | 3 of 5 | current |  |
| [E29](../EVALS.md#e29-what-does-the-plans-cheaper-energy-cost-in-margin) | What does the plan's cheaper energy cost in margin? | 4 of 5 | current |  |
| [E30](../EVALS.md#e30-does-the-plan-of-600-depend-on-the-fleets-mix-of-vehicles) | Does the plan of 600 depend on the fleet's mix of vehicles? | 4 of 5 | current |  |
| [E31](../EVALS.md#e31-how-much-does-the-plan-rest-on-the-ojais-unknown-figures) | How much does the plan rest on the Ojai's unknown figures? | 4 of 4 | current |  |
| [E32](../EVALS.md#e32-does-a-calling-rule-that-knows-the-vehicle-type-carry-more) | Does a calling rule that knows the vehicle type carry more? | 2 of 3 | current |  |
| [E33](../EVALS.md#e33-what-do-the-chargers-do-for-two-vehicle-types-on-one-feeder-and-on-two) | What do the chargers do for two vehicle types, on one feeder and on two? | 4 of 5 | current |  |
| [E34](../EVALS.md#e34-how-many-vehicles-do-two-feeders-carry-with-the-planning-margin) | How many vehicles do two feeders carry with the planning margin? | 1 of 1 | current |  |
| [E21](../EVALS.md#e21-what-does-east-oakland-ask-of-a-depot-and-when) | What does East Oakland ask of a depot, and when? | 1 of 3 | current |  |
| [E24](../EVALS.md#e24-over-26-weeks-in-three-series-which-forecast-is-better-and-which-bound-holds) | Over 26 weeks in three series, which forecast is better and which bound holds? | 4 of 4 | current |  |

## Bars missed

- **E1**: bar
- **E2**: 1 headroom beats threshold by 2pt at 1000
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
- **E7b**: 1h 3 not low by more than 3pct at peak
- **E7b**: 6h 2 upper bound holds 93 to 97pct
- **E7b**: 6h 3 not low by more than 3pct at peak
- **E7b**: 24h 3 not low by more than 3pct at peak
- **E8**: 2 ledger kept 95pct of hours
- **E10**: 3 guarded serves at least as many under the fault
- **E12**: 5 at least 1pct cheaper than the clock aware threshold that waits at 500 at equal rides
- **E12**: 6 program quota below its ceiling in a quarter of hours at 500
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
- **E28**: 3 with the peak hours 20pct busier 600 are carried in every fortnight
- **E28**: 4 with the peak hours 20pct busier the carried fleet is within one step of the control
- **E29**: 5 as tested at 600 the fleet rides at half a charge or more
- **E30**: 5 600 is carried in every fortnight at every share and both energies
- **E32**: 1 the rule that knows the type carries at least 700 in every fortnight
- **E33**: 3 half as many 150 kw chargers carry within one step of the full count at 60 kw for less
- **E21**: 1 density fit loo within 35pct on six of nine with positive elasticity
- **E21**: 3 second feeder between 24 and 120 months out
