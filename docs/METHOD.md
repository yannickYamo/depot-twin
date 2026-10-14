# Method: what is simulated, with which inputs, and how far to trust it

[Back to the README](../README.md)

*What is simulated, every input and how far to trust it, with a glossary at the end. For a reader checking the model. The one thing to take: the feeder's daily energy is what binds, and the energy figure is my estimate.*


**One feeder at this site is planned for 15,000 rides a day, which is 600 vehicles at 25 rides each. At the energy use estimated it carries 675 vehicles, and serves 700 with the feeder at its limit. 600 is the fleet still carried in every fortnight replayed if the vehicles use 10% more energy on the road, or if their systems stay on while parked in the depot; with both, the fleet is 550. Those figures rest on a published grid limit, four spring fortnights of demand measured in another city, and a set of assumptions listed in section 5. The money figures rest mostly on two guesses, and section 5 marks them.**

Every input below carries one of three labels. *Measured* means computed in this project from public records. *Published* means a figure a publisher states. *Assumed* means a value chosen here with no public source behind it. The project is independent and isn't affiliated with Waymo or PG&E. Their public filings, tariff and capacity map are used as data sources.

## 1. The site

The grid connection is the one thing at this site that can't be bought in the short run, so it sets the ceiling. Chargers, bays and people are scaled with the fleet.

| Quantity | Value | Source | Class |
|---|---|---|---|
| Parcel | 7825 San Leandro Street, Oakland | `data/derived/site.json` | A choice; nothing here says the parcel is available |
| Feeder headroom | EDES 1101: 2,751 to 2,759 kW. OAKLAND J 1110: 2,744 to 2,756 kW. Both 12 kV | PG&E Integration Capacity Analysis map, line sections within 150 m, read 2026-10-04 | Published |
| Site limit | 2,750 kW on one feeder, 5,500 kW on two | Scenario files; the sweep's two feeder options | Published figure, rounded; a second service on the same parcel is assumed |
| Most the site draws | 95% of the limit: 2,612 kW on one feeder | `DepotConfig.usable_share` | Assumed |
| Power reaching vehicles | 93% of the draw: about 2,430 kW, or 40 chargers at full rate | `charger_efficiency` in the scenario files | Assumed |
| Chargers | 60 kW DC; 66 for 500 vehicles, 132 for 1,000 | Scenario files; other sizes take one charger per 720 kWh a day at 95 kWh a vehicle-day | Assumed |
| Cleaning bays and people | 12 of each for 500 vehicles, 25 for 1,000; one of each per 40 vehicles at other sizes | Scenario files, `growth.scaled_v2` | Assumed |
| Handling times | 2 minutes to plug in, 2 to unplug, 8 to clean, 20 to inspect | Scenario files | Assumed |

Two other feeders pass within 150 m with less headroom (912 to 2,334 kW and 1,158 kW) and aren't used. The map is a snapshot. A connection application could return a different figure.

## 2. How a day is simulated

Rides are lost in two ways: no vehicle is free when a rider asks, or vehicles are off the road for longer than they need to be. The simulator counts both.

1. **Demand.** The registered runs replay real five-minute counts of San Francisco taxi rides from four fortnights of 2024 (starting 18 March, 15 April, 29 April and 13 May), scaled on the scored week so the fleet is offered exactly 25 rides a vehicle a day in every fortnight. Every run starts its vehicles at the same spread of charge, so each fortnight is replayed and the last week of the last pass is scored: two passes, then four, then eight, until the scored week reads the same as that week a pass earlier (within two points of low-battery arrivals and half a point of charge on the road). The record keeps the passes each run took. The page draws rides from the hourly shape of an average San Francisco week instead.
2. **Riders.** A ride takes 23 minutes of a vehicle, pickup included. A rider with no free vehicle waits up to ten minutes and is then lost. Rides served = served / (served + lost).
3. **Driving.** Each vehicle uses energy by the mile and for its always-on load, whether or not it carries anyone. Vehicles differ from their type by a standard deviation of 8%.
4. **Calling in.** Every five minutes a calling rule picks vehicles to send to the depot. The drive in and the drive out each take the leg time and its energy.
5. **Charger.** A vehicle queues for a free charger, a person plugs it in, it charges, and a person unplugs it. The charger is free only after the unplugging.
6. **Bay.** A vehicle is cleaned on every Nth of its own visits and inspected on every tenth. Both need a bay and a person. Other visits skip the bay.
7. **Power.** A power rule shares what the site can deliver among plugged-in vehicles. The simulator then caps every grant at what the battery accepts, what the charger delivers and what the site has left, so no rule can exceed the limit.
8. **Time step.** Rides and calls move in five-minute steps. Power is integrated in one-minute steps, because every charging vehicle shares one connection. The same scenario and seed give the same result.

## 3. The rules compared

The calling rule decides capacity and the power rule decides how much is lost once power is short. They are compared separately.

**Calling rules**
- **Plain threshold.** Every vehicle on the road at or below a set charge level is called in, whether or not a charger is free. Vehicles leave at 85%.
- **Threshold that waits for a free charger.** The same level, but only as many vehicles are called as chargers are free and unspoken for, emptiest first.
- **Hourly plan.** Each hour a linear program plans the next 24 hours against the forecast's upper bound, and only its first hour is carried out. Vehicles are called for an energy slot (30 minutes at full rate, about 26 kWh, in the capacity runs), a few every five minutes, never more than the site can feed at full rate. Told the tariff, it charges ahead of the 4 pm to 9 pm peak.
- **Low-battery floor.** Under every rule, a vehicle at or below 8% charge is sent in. The plan also brings in any vehicle at or below 12%. A vehicle arriving at or below 12% is counted as arriving at the low-battery level.

**Power rules**
- **In order of arrival.** Vehicles are fed at full rate in the order they plugged in. The rest wait their turn.
- **Emptiest first.** The vehicle with the least charge is fed at full rate first.

Capacity is counted only when the calling rule, not the floor, is bringing vehicles in. A fleet is carried when at least nine runs in ten serve 99% of rides, no more than half its depot visits start at the low-battery level (the share is counted over visits, not over vehicles, and the level is 12% charge or under after the drive in; the floor that forces a vehicle in is 8%), and every smaller fleet is carried too. The exact condition is in E23's registration in [EVALS.md](../EVALS.md).

Across four fortnights and ten seeds on one feeder (`data/derived/e23_capacity.json`), on steps of a hundred vehicles: the plain threshold carries 500 vehicles, the threshold that waits carries 600, and the plan carries 500. The fleets between the steps were run on the same fortnights and seeds (`e25_between.json`, `e26_margin.json`). Under the waiting rule 650 and 675 vehicles are carried too: 675 serve at least 99.95% of rides in every one of the forty runs with no low-battery arrivals in the median run, drawing 99% of the feeder's usable power. 700 vehicles still serve every ride at the median, with the feeder at its limit in every step and 61% of visits starting at the low-battery level: served, not carried. On the same steps of 50 vehicles the plain threshold carries 550 where the waiting rule carries 650.

**The feeder's energy is what binds.** With the vehicles' driving energy and always-on load both 10% lower, the feeder carries 750 vehicles; as estimated, 675; 10% higher, 625 (E26, forty runs a fleet). The carried fleet multiplied by its energy level is 675, 675 and 688: the feeder gives 62.7 MWh a day and the fleet is that divided by what a vehicle takes. The steps are 25 to 50 vehicles. At 10% less, 750 is the largest fleet carried and 775 was not run; at the estimate 700 is the largest that still serves 99%, and the fleets between 700 and 800 were not run.

**A parked vehicle draws nothing in this model.** The always-on load is drained on the road and on the drive to and from the depot, and not while a vehicle waits, charges or is cleaned. Whether a robotaxi powers down in a depot isn't public. E27 counts the load for every minute inside, charged to the battery as the vehicle leaves, through one method replaced in the test's own processes: the simulator's code and every other record are unchanged. That counts the load as energy, not as power drawn through the charger while the vehicle is plugged in: the extra time lands on the next charge and not on this one. It costs the feeder about 5 kWh a vehicle a day. The carried fleet is then 625 at the estimate and 575 with 10% more on the road as well.

**The fleet to plan for is 600.** It's carried in each of the four fortnights with 10% more energy on the road (feeder at 98% of usable power), and in each with the parked load counted (94%). With both, 600 isn't carried and 550 is. E26's registered rule, the largest fleet carried at the estimate and with 10% more over all forty runs, gives 625. At 625 with 10% more the feeder is at its limit in every step of the median run and one fortnight of four isn't carried, at 52% of visits starting low against a line at 50%, so I plan on 600.

**Forty runs are four fortnights.** The ten draws of a fortnight change which vehicle is which and how work falls between them, and they move rides served by about a tenth of a point where the fortnights move it by two. Between 98% and 99.9% of the spread is between fortnights, so forty runs are worth about four independent ones (`data/derived/capacity_spread.json`). "Nine runs in ten" therefore usually means every fortnight serves 99%, and a 10th percentile is the weakest fortnight. The low-battery half of the rule is read on the median of the forty and can pass with one fortnight over the line, which is why the planned fleet asks for every fortnight. All four fortnights are from March to May 2024, and each is scaled to the same rides a vehicle a day.

The plan's worth is the energy bill: 6.7% cheaper at 500 vehicles at the median, with no ride lost. At 1,000 vehicles under the plain threshold, feeding in order serves 85.0% of rides against 76.4% for emptiest first; at 500 and 600 the two power rules serve the same rides.

## 4. The cadence setting

How often a vehicle visits the depot changes what one feeder carries, so the setting is taken from public counts and not chosen freely. Waymo's quarterly filings to the California Public Utilities Commission leave two counts in the open: charging sessions and chargers. The two figures the twin had to match, each within 15%:

- **7.5 to 8.5 trips a charging session** (the filings give 8.41, 7.84 and 7.45 for the last three quarters);
- **19 to 21 sessions a charger a day** (19.3, 21.0 and 19.2).

E22 swept the leg (5, 8 and 15 minutes), cleaning every first, second or fourth visit, a call-below level of 20%, 40% or 55%, and two charger counts, at 500 vehicles. The setting it chose (`chosen` in `data/derived/e22_cadence.json`): **a 5-minute leg of 1.2 miles, cleaning every fourth visit, called in at 55% charge**, released at 85%, 66 chargers. It gives 8.0 trips a visit and 23.9 visits a charger a day, with 3.2 visits a vehicle a day and every ride served. The second figure sits above the published band and inside the 15% allowance. The filings' charging counts cover pilot and deployment fleets together, while trips are the deployment's alone.

## 5. The assumptions

Read this table before any result. The physical inputs move the fleet one feeder carries by one or two hundred vehicles. Two money inputs with no public source, **what a vehicle costs a year and what running it costs a day**, each move the daily account by more than the whole of the depot's own costs.

Swings in the last column are the change in daily contribution for 600 vehicles on one feeder, under the rule that waits for a free charger, when that input alone moves across its range (`tornado` in `data/derived/account_study.json`). The contribution at the base values is $102,469 a day.

| Input | Value | Moved over | Class | What it moves |
|---|---|---|---|---|
| Rides offered a vehicle a day | 25 | 18, 21.5, 27.5 and 30 | Assumed | The fleet count more than the rides. At 21.5 and at 18 the feeder carries 700. At 27.5 it carries 650, and at 30 no fleet from 525 to 600 is carried: vehicles run short at the busiest hours with the feeder at 84% to 94% of its power (`e28_further.json`). Served at its limit while holding the 99% floor it takes 800 vehicles at 21.5 and 1,000 at 18, every vehicle arriving at the low-battery level, and rides a day stay near 17,200 to 18,000 |
| Shape of demand through the week | San Francisco taxi rides, December 2022 to May 2024 | Four fortnights | Measured, in another city | When the peaks fall. On hundred-vehicle steps the carried fleet was 600 in two fortnights and 700 in two; 650 and 675 are carried in all four |
| Ride time, pickup included | 23 minutes | 18 and 28 | Assumed | Which resource binds. At 18 minutes 600 are carried. At 28 no fleet from 500 to 900 is carried, and vehicles bind before the grid |
| A rider's wait | 10 minutes | 5 and 15 | Assumed | Whether the vehicles bind. At 15 minutes 600 are carried. At 5 no fleet from 500 to 900 holds 99% in nine runs in ten, with power to spare |
| Miles a ride | 0.99 to the pickup, 3.93 with a passenger | Not moved | Published (filings, April to June 2026) | Energy a ride, and the fare |
| Speed with no ride assigned | 2.4 mph, parked time included | Not moved | Assumed, set by calibration | Energy used while idle |
| Energy on the road | 0.30 and 0.27 kWh a mile by vehicle type, plus 2.0 and 1.8 kW always on | 10% each way | Assumed | The carried fleet moves one for one with it: 750, 675 and 625 vehicles at 10% less, the estimate and 10% more (`e26_margin.json`). All in it is about 0.53 kWh a mile, nearly half of it the always-on load. A parked vehicle is assumed to draw nothing; counted, the carried fleet is 625 (`e27_parked.json`). Further out the fleet keeps following the fleet carried at the estimate, scaled by energy: 575 at 20% more (a registered bar) and 525 at 30% more (run, with no bar) (`e28_further.json`). For scale, the EPA rates the stock 2020 Jaguar I-PACE at 44.3 kWh per 100 miles combined and 42.2 in the city, measured at the wall (fueleconomy.gov); 0.53 at the battery is 0.57 at the wall with the 7% charger loss, about 30% above the combined rating |
| Battery and charging | 90 and 93 kWh; up to 104 and 150 kW, tapering with charge; fleet mix 60/40 | Not moved | Assumed | Time on the charger at high charge |
| Site limit | 2,750 kW a feeder | One or two feeders | Published | Everything |
| Usable share of the limit | 95% | Not moved | Assumed | Energy a day the site can deliver |
| Charger losses | 7% | Not moved | Assumed | The same |
| Charger count | 66 at 500 vehicles | 1.5 times as many; one per five vehicles | Assumed | Queueing. Little once power is the limit |
| People and bays | One of each per 40 vehicles | Not moved in the capacity runs | Assumed | Time to plug, unplug and clean |
| Leg between riders and depot | 5 minutes, 1.2 miles | 5, 8 and 15 minutes | Assumed, chosen to match the filings | Time off the road a visit |
| Call-below and release levels | 55% and 85% | 20%, 40%, 55%; then 45% to 65% in steps of 5 | Assumed, chosen to match the filings | Visits a day. A call-in level of 50% or 55% matches the filed counts; under each, 675 is carried (`e28_further.json`) |
| Cleaning | Every fourth visit, 8 minutes | Every visit, second, fourth; then third to sixth | Assumed, chosen to match the filings | Time off the road a visit. Every third to every sixth visit carries the same fleet (`e28_further.json`) |
| Inspection | Every tenth visit, 20 minutes | Not moved | Assumed | The same |
| Low-battery floor | 8% (12% under the plan) | Not moved | Assumed | When the rule stops being in charge |
| Service floor | 99% of rides served | Not moved | A choice | Which designs count |
| Fare a ride | $19.69 | $17.72 to $21.66 | Published price survey, late 2025 (Obi, in [DATA.md](DATA.md)) | $59,090 a day |
| Busy pricing | Starts at 80% of on-road vehicles busy, up to 1.3 times | Not moved | Assumed | The fare between hours. The average stays on $19.69 |
| Energy price | $0.360 peak, $0.151 off-peak, $0.128 midday, a kWh; $85.98 a month per 50 kW | 20% each way | Published (PG&E BEV-2, effective March 2026) | $4,341 a day |
| **A vehicle** | **$60,000 a year** | **$30,000 to $100,000** | **Assumed, no public source** | **$115,068 a day** |
| **Running a vehicle** | **$100 a day** | **$50 to $250** | **Assumed, no public source** | **$120,000 a day** |
| A lost ride, beyond its fare | $20 | $0 to $60 | Assumed, no public source | $114 a day at 600 vehicles, where under two rides a day are lost; decides whether 800 beats 700 |
| A person on site | $40 an hour, around the clock | $30 to $55 | Assumed | $9,000 a day |
| Land | $217,500 a month for 14.5 acres | $150,000 to $300,000 | Assumed | $4,932 a day |
| Grid connection | $200 a kW over 20 years | $100 to $400 | Assumed | $113 a day |
| A fast charger, installed | $40,000 plus $500 a kW, over 10 years | Not moved | Assumed | $1,534 a day at 600 vehicles |
| Wholesale delivery charge | $0.08 a kWh | Not moved | Assumed | The two wholesale scenarios only |

## 6. The account

The depot's own costs are small beside the fleet's. Energy is 3.7% of revenue at 600 vehicles. Vehicles and running them are 54%. A ranking of depot designs is therefore firmer than any statement of profit.

The account reads a finished run and changes nothing in it. It's taken on the capacity test's own runs: the filed cadence, the rule that waits for a free charger, four fortnights by ten seeds. Lines for 600 vehicles on one feeder, a day, as the mean of the forty runs:

- **Revenue $295,300.** Each served ride at the price of its step.
- **Depot costs $34,163.** Energy on the tariff $10,853, staff $14,400, land $7,151, chargers $1,534, capacity subscription $150, grid connection $75.
- **Fleet costs $158,630.** Vehicles $98,630, running them $60,000.
- **Lost rides $38.** Each lost ride charged at $20 beyond its fare.

The split by fleet size (`split` in `data/derived/account_study.json`), dollars a day as the mean of the forty runs, with the contribution's 10th to 90th percentile:

| Fleet | Depot's contribution before the fleet's cost | Fleet's cost | Lost-ride charge | Contribution | Range across runs |
|---|---|---|---|---|---|
| 500 | 216,831 | 132,192 | 29 | 84,611 | 84,340 to 84,776 |
| 600 | 261,137 | 158,630 | 38 | 102,469 | 102,303 to 102,579 |
| 650 | 283,968 | 171,849 | 35 | 112,084 | 111,814 to 112,225 |
| 700 | 306,963 | 185,068 | 216 | 121,679 | 120,383 to 122,158 |
| 800 | 345,991 | 211,507 | 7,399 | 127,084 | 109,309 to 138,466 |
| 900 | 372,299 | 237,945 | 28,468 | 105,886 | 70,537 to 131,791 |

The first column is the part the twin models. The second is two assumed figures multiplied by the fleet. Contribution rises with the fleet up to 800 because every added vehicle is assumed to find its 25 rides; the account doesn't say the rides are there. An 800-vehicle fleet out-earns 700 only while a lost ride costs less than $51 beyond its fare at the median run, and between $6 and $219 across the forty runs, so the choice between them isn't settled by this account.

**When to apply for the second feeder** (`feeder_timing` in the same file). This is a table of scenarios, and it has no bars. A vehicle the first feeder can't carry earns nothing. What it would earn on a second feeder is what that feeder adds for it: fares less energy, chargers, staff, the vehicle, running it and the charge for lost rides. The parcel's land and the first connection are paid either way and are left out, so the figure is $183 a vehicle a day at the base costs, against $171 for the site's average; $315 with both unsourced vehicle costs at the cheap end of their ranges. At the dear end it's a loss of $77 a day, and a vehicle that loses money isn't put on the road, so its absence is valued at nothing. The second connection, $550,000, is paid when it goes into service. The table crosses two readings of today's level (241 and 280 vehicles, centred on January and May 2026), three of growth, lead times of two, three and four years, discount rates of 8% and 10%, and those three levels of vehicle cost: 108 scenarios for an application made a year after signing, each against one made at signing, with the loss capped at one feeder's worth of vehicles.

The reading of growth to plan on is the slowest of the three. The other two span the quarter in which the served footprint was enlarged, from 1,496 tracts to 1,796, when trips a day rose 56%; a line through the nine months since gives 2.0% a month (`growth_since_the_footprint_settled`), the same as the slowest reading. On it the area fills the planned fleet in 39 to 47 months from the first half of 2026. A year's delay then saves $35,000 to $41,000 at a two-year lead, the feeder being paid for a year later, and costs up to $2 million at three years and $4 to $10 million at four. On the two faster readings, 16 to 20 months, it costs $19 to $31 million, and the top of that range is the cap in present value: 600 vehicles' added contribution for twelve months, $40 million before discounting. Sixteen of the thirty-six base-cost scenarios are at their cap, every faster-reading one with a lead of three or four years. Across the vehicle costs the range is from that small saving to $53 million. Applying a year early costs $30,000 to $41,000 in capital paid sooner, and the whole $550,000 if the second feeder is never needed. Lead times and discount rates are assumed.

## 7. The page

The page is for watching and for changing a design. The registered results come from the Python simulator.

- **A second simulator.** `web/src/sim.ts` models the same core in the browser: rides through the week, batteries on the road, the leg, the charger queue, people, cleaning and inspection, the rider's wait, both power rules, and three calling rules (threshold, threshold that waits, energy slots).
- **Held to the first by test.** `web/tests/sim.test.ts` runs 500 and 1,000 vehicles on one feeder under both power rules in four settings, three seeds each over seven days with the first left out. Rides served must agree with Python within half a point where Python serves at least 99.9% and within a point and a half elsewhere. Visits a vehicle a day must agree within 0.05 and grid energy a vehicle a day within 2%. The gain from feeding in order at 1,000 vehicles must agree within two points.
- **Recorded traces.** Runs that need the plan are played from traces recorded from Python (`web/public/traces/`): the plan and the threshold at 500 and 1,000 vehicles and the threshold with emptiest-first feeding at 500, three days each, recorded from the replay curves kept in the repository and stamped with the code that ran them.
- **The short version and three tabs.** The page opens on a short version: the decision, the answer, why, one rule, what I got wrong and what to do first. The full twin has three tabs: Depot, Decisions, and Under the hood (Forecasts, The account, A recorded run).
- **The Decisions tab.** Four choices, each as one pair, with the decision taken and not taken, read from the capacity runs and the account study into `web/public/outcome.json`. The power rule and the plan are the same fleet run both ways on the same forty fortnight-and-draw pairs; the calling rule compares the largest fleet each rule carried on the same steps of 50 vehicles; the feeder is the scenario table above. Above the cards the view states the planned fleet and what the feeder carries at each level of energy use. The pairs aren't added together, because they were measured at different fleets, and the dollar figures assume every vehicle finds its rides. Three of them can be watched: the page puts every setting of the browser's depot back to its start, sets that case and runs the same depot the other way beside it, with the difference in rides and fares. The pair for the power rule is an overloaded depot on purpose, 1,000 vehicles on one feeder, because that is the only place the rule matters.
- **Not simulated in the browser.** The hourly plan, the ride forecasts, a stationary battery, and replayed real days. The account, under the hood, redoes the account of recorded designs as sliders move; it starts no new simulation.

## 7b. The site planner

`depot-twin plan` (`src/depot_twin/siteplan.py`, described for a user in [SITES.md](SITES.md)) runs the capacity method on a site read from a file. It is a layer over the simulator and changes nothing in it. It differs from the registered tests in four ways, three for speed and one for caution: a window whose run hasn't settled, on low-battery visits and on rides served, isn't counted as carried; two draws a window in place of ten, since the draws of a window are near copies; a search outward from the arithmetic, two fleets at a time, in place of a fixed grid; and a run far past the edge is not replayed until it settles. Its verdict is the planned-fleet rule: carried in every window. On the East Oakland file it gives 675 carried, 600 with 10% more energy, 625 with the parked load and a plan of 600, the figures of E26 and E27.

**Other demand.** The same depot was planned on the study's four fortnights counted by the hour, and on four fortnights each of Chicago and New York ride-hail, one from each season between July 2025 and April 2026 (`sites/shape_*.toml`, plans in `sites/plans/`). Each carries 675, with the feeder at 99% of its usable power, and 700 fails in one or two windows of the four in each. This is a check with no bars. It says the shape of the week does not set what the feeder carries once the level is fixed; it does not say the level is right, and the vehicles' energy use is the same in every season.

## 8. Results are tied to their code

- **Stamps.** Every result file under `data/derived/` carries hashes of the simulator code and scenario files, the forecasting code, the module that ran the test, and any record it was computed from. Comments and docstrings are left out of the hash.
- **`depot-twin stale`** lists every result, page file, figure folder and the claim ledger (`docs/FACTS.json`) whose stamp differs from the current tree. A record is stamped when it is written, so a run is only as good as the tree staying still while it runs; E27, E28 and E29 check that their stamp is the same at the end as at the start and refuses to write otherwise. The test suite fails while a stale file is not named with its reason.
- **`depot-twin reproduce`** runs six published runs from replay curves committed under `data/reproduce/` (the fortnight from 15 April 2024, seed 2301): both power rules at 1,000 vehicles, the waiting rule at 600, 650 and 700 vehicles, and 600 vehicles with 10% more energy use. Each must match its record (`e23_capacity.json`, `e25_between.json`, `e26_margin.json`) to the fifth decimal of rides served and of low-battery arrivals, and a run with no counterpart in the records fails the check.
- **The manifest.** `data/manifest.json` lists the 222 downloaded source files with size, SHA-256 and retrieval date. The PG&E map is queried live and is not in it.

## 9. What is left out

- **One site.** One parcel, one or two feeders. No network of depots and no vehicles moving between them.
- **No traffic or repositioning.** The road is modelled in aggregate: a ride is a set number of minutes and miles, and the leg to the depot is one figure.
- **A plan that doesn't solve isn't counted.** If the hourly program finds no solution, it plans no call-ins for that hour and the run doesn't record it. The low-battery floor still brings vehicles in.
- **No battery aging.** Capacity and charge acceptance stay as set for the whole run.
- **No weather or events in the simulated day.** Demand is what the replayed days held: four fortnights between 18 March and 26 May 2024, each scaled to the same level. No winter heating or summer cooling load, and no week busier than the level assumed.
- **A vehicle is always available.** No maintenance downtime, and a parked vehicle draws nothing unless a test says otherwise (E27).
- **The depot is five minutes from its riders.** The leg is 1.2 miles each way while demand is drawn from a 20 km circle. E22 found the leg moved little at 500 vehicles with power to spare; it was not moved at the edge.
- **East Oakland demand is not observed.** The shape is San Francisco taxi rides and the level is set at 25 rides a vehicle. The area estimate (about 6,000 rides a day within 20 km) is the filings' statewide trips a resident applied to census population.
- **Costs are assumptions.** Section 5 lists them. The account ranks designs; it does not state a profit.
- **Ride records count rides served, not rides wanted.** Where cabs were short, real demand was higher.
- **Riders are scored when served or given up on.** A ride offered before the scored week and settled inside it counts in the week, and a rider still waiting at the end of a run would count nowhere. The scored week opens and closes at midnight on a Monday; in 24 runs measured for it, at 650 and at 800 vehicles, no rider was waiting at either edge (E26). A test scored across a busy hour should count by the hour a ride was offered.
- **No connection offer.** The headroom is a map reading, and whether two services can reach one parcel is not settled here.

## Glossary

- **Feeder.** A 12 kV distribution line. Each of the two used here has about 2.75 MW of published headroom.
- **Draw.** The power the site takes from the grid, in kW. Never above 95% of the site limit.
- **Calling rule.** Decides which vehicles leave the road for the depot, and how full they go back out.
- **Power rule.** Decides which plugged-in vehicles are fed when the site cannot feed all of them.
- **Low-battery floor.** The charge level at which a vehicle is sent in whatever the calling rule says.
- **Leg.** The drive between the riders and the depot, each way.
- **Cadence.** How often a vehicle visits the depot: trips a visit, and visits a charger a day.
- **Rides served.** Served / (served + lost), over the scored week.
- **Carried.** A fleet the feeder serves at 99% in nine runs in ten with the calling rule in charge: no more than half its depot visits start at 12% charge or under.
- **Planned fleet.** The largest fleet carried at the estimated energy use and, in each fortnight, with 10% more on the road: the fleet a lease is sized for. It also holds with the parked load counted, and not with both.
- **Served at the limit.** The largest fleet that still serves 99% of rides in nine runs in ten, whatever brings its vehicles in.
- **Plan.** The calling rule that solves an hourly program over the next day and acts on its first hour.
- **Bound.** The forecast's upper level, which rides should stay under 95% of the time. The plan is drawn against it.
- **Contribution.** Revenue less the lines of the account, a day. Not the service's profit.
- **Bar.** A pass condition written in EVALS.md before the run it judges.
- **Energy estimate.** What one vehicle uses in a day, on the road and parked. Mine, with no public source.
- **Service floor.** 99% of rides served. A policy choice, not a finding.
- **Registered test.** A question whose pass bars were fixed before it was run.
- **Fortnight.** A 14-day replay window, replayed until the fleet settles; its last seven days are scored.
