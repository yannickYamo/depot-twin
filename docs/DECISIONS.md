# Decisions: what we thought, what we found, what changed

The build log has every step in order. This file has the turns: each time a belief met an experiment and the roadmap moved.

Every entry has the same shape, because the work was run that way. A belief stated first, a test with its bars fixed before its run, the result published whether it passed or missed, and the decision that followed. "We" is the team: the owner set the direction and called each turn, and the building and testing followed. The **Steer.** line is what the owner decided at that point.

---

## 1. The depot is the limit on a fleet, not the vehicles

**We thought** a robotaxi fleet in a city is capped by how many vehicles one depot can turn around. Chargers and people get added in weeks. A grid connection takes years. Most plans take that number from a spreadsheet, which is right about energy and wrong about the day.

**We built** a discrete-event twin of one depot on a real parcel, with the grid headroom its utility publishes. Inside the model: the fleet's rides, the queues, charging under the site limit, people, cleaning.

**What the experiments showed.** The hand calculation and the twin agree on energy. They disagree on the day. The twin sees the queue at the evening peak, and the hour when half the fleet comes back empty together. The first growth study shows where each resource saturates as the fleet grows from 200 to 2,000.

**Steer.** The owner chose the Bay Area site, the 200 to 2,000 range, and the rule that everything is rebuilt from public data.

---

## 2. Demand forecasting should be gradient-boosted trees, trained properly

**We thought** the demand forecast needed a model you can inspect, train quickly, and hold to a baseline. The first risk we named was over-fitting.

**Steer.** The owner asked for XGBoost in place of the first choice, gave a hyperparameter table as a starting point to challenge, and set the rule: every model gets a proper split and a withheld block that tuning never sees.

**We built** forecasts at 1, 6 and 24 hours. A small search over tree depth and child weight. Early stopping on a separate block. Bounds measured on a third.

**Experiment A (E7)**: missed every bar. The level of rides rose by about 60% between the training days and the test days, and a tree model extrapolates poorly beyond the levels it has seen.

**Experiment B (E7b)**: target changed to the ratio to the same hour last week. Passed 5 of 9.

**The binding thing**: the target's definition, not the model's settings.

**What changed:** every forecast since predicts a ratio. The pooled cross-city model later built on the same idea.

---

## 3. Charging should be orchestrated as a heartbeat, not a surge

**We thought** a depot that fills every free charger works in surges. A steady pulse of short sessions, paced to the chargers, would serve more rides and draw smoother power.

**Steer.** The owner brought the idea of orchestrated, dynamic charging, as in a published charging-network design, and asked for a controller built around it. The architecture is one from home energy management: forecasts, an identified twin, model predictive control.

**We built** the heartbeat controller. Energy slots. A cap on plugged-in vehicles at what the site can feed. In-order feeding. An hourly linear program over the next 24 hours against the forecast's upper bound. A ledger of hourly promises, and a guard.

**Experiment A (E8)**: the controller beat the fill-every-charger rule by 5.2 points at 1,000 vehicles.

**Experiment B (E9)**: repeated on fresh days, 4.3 points. Promise kept in 96% to 98% of hours.

**What was binding, found later (E11):** not the plan. See entry 5.

---

## 4. Short charging sessions would be the heartbeat's advantage

**We thought** 30-minute sessions would keep more vehicles on the road.

**We built** them.

**Experiment A**: lost ten points of rides at the first depot.

**Experiment B (the session-length study)**: varied slot length, drive time and charger power. Distance barely mattered. Charger power did. At 150 kW a 20-minute slot serves as many rides as an hour at 60 kW.

**The binding thing**: energy per visit, not minutes.

**What changed:** the slot is measured in energy, and the finding is stated as a rule about chargers rather than a rule about sessions.

---

## 5. The controller's gain belonged to the plan

**We thought** the day-ahead plan and its forecasts were what served the extra rides.

**Steer.** The owner asked for a full gap analysis instead of more features, and every claim got taken apart.

**Experiment A (E10)**: fed the plan a broken forecast. It barely moved.

**Experiment B (E11)**: every calling rule crossed with every power rule. The whole gain at 1,000 vehicles belonged to the power rule. A plain threshold with in-order feeding serves 88.8%, level with the full controller's 88.6%, against 82.9% with emptiest-first.

**The binding thing**: how power is shared when it's short.

**What changed:** the headline of the project moved from the controller to the power rule. E8 and E9 stand as numbers, and their explanation is the power rule. The plan was tested on the thing it can actually move, the price of energy (E12: 12.2% cheaper per kWh, no loss of rides, all of it from steering by the tariff clock).

---

## 6. We explained the power rule without measuring it

**We thought** emptiest-first loses because each arrival takes power from a vehicle that was nearly done.

**Experiment A**: the browser simulator, a second implementation built for the front end, disagreed with the first in exactly one cell. The difference was that it had no staff.

**Experiment B (the staffing study)**: varied the people on the floor. Emptiest-first leaves 7.5% of the site's power unused while finished vehicles wait on chargers to be unplugged. The gain shrinks from 6.5 points to 3 as people are added.

**Experiment C (E14)**: repeated on another city's days, and added the textbook rule, least energy left first, which ties.

**The binding thing**: unused power, through people.

**What changed:** the explanation is the measured one. The claim narrowed to "3 to 6.5 points depending on staffing". The rule was restated as "any fixed order at full rate".

---

## 7. The literature should have come first

**Steer.** The owner asked that what had been published on fleet charging be read before anything more was built. The owner's words: "we are not reinventing the wheel here".

**What it found.** The power-rule result is a theorem from 1968 about shortest-remaining-work scheduling. The staffing interaction isn't in the literature. The model's inputs sit inside public figures. No open tool models one depot's grid limit, queue, cleaning and staff together. No published method validates a forecast for a city with no data.

**What changed:** the roadmap was reordered to put the new-site forecast first, and the related-work document became part of the record.

---

## 8. A forecast for a place with no history

**We thought** a new site could borrow other cities' rhythms, and demand generated from them would be the training data.

**Steer.** The owner made the forecast the priority and set the standard: dummy data for a new location, set up properly, trained properly, its error stated even though it can't be validated there.

**We built** a donor panel from three cities, a generator, a cross-city model, and a leave-one-city-out test.

**Experiment A (E13)**: 1 of 4 bars. The borrowed forecast beat last week's curve in seven of nine cells and came within 1.25 times an in-city model in five. The bounds missed. The depot reached the same answer on generated demand as on San Francisco's real days.

**Experiment B (E15)**: in two more cities the average generated scenario is kinder than the real days, and the worst of ten is a safe reading.

**The binding things**: telling the model the size of the place, and training on real donors thinned to that size. The generator itself added little.

**What changed:** the model is told its size. A new site runs on last week's curve until it has a few weeks of its own rides, with the guard on. The site's capacity is quoted from the worst scenario. The generator was demoted from training data to scenario source.

---

## 9. How far the figures move

**We thought** the site's capacity could be quoted as a number of vehicles.

**Experiment (the sensitivity study)**: moved each uncertain input within public figures. At 25 rides a vehicle a day with long visits, 700 vehicles serve every ride on one feeder and 800 sit just under the 99% floor (98.7%); at 21.5 rides 800 clear it; at 18, 1,000 vehicles serve 99.9%.

**What changed:** capacity is stated with its condition attached: the rides a vehicle serves a day.

---

## 10. The plan should be seen, and judged by what it decides

**Steer.** The owner looked at the demo and asked three things: slow it down to a dial, show the ML's performance and some grid data beside it with a public grid-intensity map as the reference, and name every vehicle so an asset can be followed through the chain. Then: show the plan itself, test whether a stronger first-hour forecast helps it, and build a mode where a visitor changes how the model is trained and sees what that does to planning.

**We built** all of it on recorded results. Nothing trained in the browser.

**Experiment A (the first-hour study)**: cutting the first hour's forecast error by a third changed nothing in the plan's rides or promises.

**Experiment B (the model workbench, a reference and fifteen variants)**: rides served were 100.0% whatever forecast the plan was fed, including one cut to a third. The reference model isn't the best of its variants on held-out days. The page says so and doesn't act on it.

**The binding thing** at this depot is energy and the number of vehicles that need charging. The forecast's value shows in the reserve it asks of the fleet - 48.5 vehicles with the model, 62.9 without - and in the bound, not in rides.

**What changed:** the measure of a forecast became what it asks of the fleet. The plan for improving the forecast was rewritten around decision quality before it was started.

---

## 11. The forecast's error, and whether to chase it

**Steer.** The owner judged 11 to 15% error too high and asked for ideas, then for an exploration of synthetic data and public data at scale.

**What the exploration found.** A Poisson counting reference is about 4.6 points of error at 300 rides an hour (the mean absolute deviation of a Poisson count over its mean, the square root of 2/(π × 300)). A pretrained time-series model leads a public benchmark on city demand, zero-shot. Synthetic data isn't the bottleneck, by our own tests.

**What the plan settled:** decision regret is the primary measure, the bound is defined twice, results on San Francisco count as development only, direct counts return as a comparator in a fair form, and comparisons use paired days.

**The plan:** data contracts first, then the regret test, then the model fixes, then the pretrained model, then a checkpoint with four questions. If the forecast improves and the depot doesn't, the forecast work stops, and that's the finding.

## 12. What a forecast is worth, measured

**We thought** a forecast's value depends on which constraint binds, and that where vehicles bind it would be large.

**Steer.** The owner asked for data contracts before any model changed.

**We built** the contracts, the registry and the provenance rule, then ran the plan on perfect foresight, the model, last week's curve and a broken feed across four regimes (E16).

**Experiment A**: the forecast is worth nothing where energy binds.

**Experiment B**: where vehicles bind, perfect foresight is worth a sixth of a point, and nothing short of it is worth anything.

**The binding thing** is the plan's own margin and slot design, which keep vehicles on the road at the peak whatever the forecast says. What the forecast decides is the reserve: 50 to 99 vehicles with a model against 64 to 128 without.

**What changed:** forecast error stopped being a goal for this depot. The forecast is judged on its bound and on new sites.

## 13. Better on the days we had looked at, not on the days we had not

**We thought** three fixes to how the forecast is built, each answering something a test had found, would cut error and tighten the bound everywhere.

**Steer.** The owner said "go" on the plan: San Francisco for development only, confirmation once on reserved windows in two other cities, bars written first.

**Experiment A (development)**: all three fixes helped on San Francisco.

**Experiment B (confirmation, E17)**: 0 of 4 bars. New York gained about a point. Chicago lost a little. Coverage slipped in both.

**The binding thing** isn't settled. New York's spread between draws comes from two storm days in its window and their echo a week later through the ratio target, not from the thinning draw.

**What changed:** the reference stays, and the bound's coverage at depot volume moves to the front of the forecast work, because E16 showed it's what the plan actually pays for.

## 14. This bound was not the answer; a better point forecast was

**We thought**, after E17, that the uncertainty estimate rather than the point forecast was where the fleet's reserve could be won.

**Steer.** The owner said "go" on a test built to separate the two and judge them on the reserve at matched reliability, with a pretrained model as one arm.

**Experiment A**: the volume-aware bound held more vehicles than the reference's, not fewer.

**Experiment B**: a pretrained model (Chronos-2), used as it comes, had 7.7% error against 9.6% for the model trained here and held 35.7 vehicles in reserve against 40.7, on a series no test had scored. That city's data is in the pretrained model's public training corpora, so the result shows an available component helps, not that it transfers unseen.

**The binding thing**, on the evidence, is the point forecast. A better conditional mean leaves smaller residuals, and a 95% envelope around smaller residuals is narrower. One bound formulation lost; that doesn't prove no bound could win. The ceiling we had assumed for the point forecast was our own models'.

**What changed:** the forecast work stops as registered. The trees trained here stay the controlled reference, and the pretrained model is the preferred candidate where its dependency and provenance are acceptable.

## 15. The sweet spot is a service decision

**We thought** a financial account over the whole design space would show a profit-maximizing fleet size inside the range, with the feeder binding on one side of it.

**Steer.** The owner asked for the financial twin, frozen in time with real prices, counted the way an operator counts.

**Experiment (E19)**: 0 of 4 bars. Contribution rises one step past the point where service breaks: 800 vehicles on one feeder earn more than 700 while serving 98.5%, and it falls steeply after. The grid is at its limit 98% of the time at 700, where service still holds. The plan is ahead of a threshold at 400 to 600 vehicles and behind at 700. The plan told an hourly price buys 0.7% cheaper.

**The binding thing** is the service requirement. Without it the account pulls past the floor. With it, the sweet spot is 700 vehicles on one feeder under the threshold, $126,200 a day; among designs serving 99%, the best in the sweep is 1,200 vehicles on two feeders, $219,700 a day, the top of the range swept.

**What changed:** capacity and the sweet spot are stated with their service condition, and the plan's price steering is recorded as tariff-shaped, with an hourly version on the roadmap, not built.

## 16. A price response that is real and conditional

**We thought** the plan, taught to read an hourly price, would buy noticeably cheaper under day-ahead prices.

**Steer.** The owner asked for the roadmap's remaining items, built and tested.

**Experiment (E20)**: the steering reads the dearest quarter of the day that also sits a fifth above the median hour, because a quantile alone sweeps up tied hours. It matched the tariff path to four decimals and gained 0.8% under that fortnight's day-ahead prices.

**The binding thing** is the price curve itself. With the assumed delivery charge added, that fortnight's day-ahead prices at this load point were too flat to steer around.

**What changed:** the steering stays in, stated as conditional on the price's shape, with the delivery assumption named as what flattens it.

## 17. A ride pays what the service charges, not what a meter says

**We thought** a flat published average fare was enough for the account, since the fleet's rides were the thing being counted.

**Steer, twice.** The owner read the money page and refused the flat fare: what riders pay should be modeled, not assumed. The first model was a fare line fitted on San Francisco taxi trips, scaled to the published figures. The owner refused that too: the comparison is wrong, and the service's own price is what to simulate.

**Experiment (E19)**: each ride priced the way the service builds its prices - base, distance, time, busy pricing - with the demand adjustment read from the twin's own run. Busy pricing moves the fare between hours and leaves the average on the published $19.69.

**The binding thing** is the lost ride, not the fare. The share of steps sold at the busy price runs from 10% at 400 vehicles to 69% at 1,200 on one feeder, and the average fare is the same at both. Scarcity doesn't pay, so a ride the depot can't serve is only ever a loss.

**Roadmap change:** the account's revenue line became part of the simulation rather than an input to it. The taxi records are used for when and where rides happen, never for what they pay. The price of a lost ride moved from a footnote to the figure the service decision turns on.

## 18. The visits were the twin's, not the service's

**We thought** how often a vehicle visits the depot was unknowable from public data, and that the twin's long, infrequent visits were as good a guess as any; the sensitivity study had even said more visits cost rides.

**Steer.** The owner asked what known data patterns hold for a new city's dynamics, then for a full study and a plan, then for the build.

**Experiment A (the filings)** found that the quarterly filings count chargers and charging sessions: a vehicle charges every 7.5 to 9.4 trips, about three times a day. **Experiment B (E22)** found the twin reaches that cadence when vehicles are called in at 55% and cleaned every fourth visit, and that with a wash on every visit the same call-in level loses twelve points of rides. **The binding thing** was the cleaning bay, not the drive or the charger: the cost of a visit the twin had charged to the trip was the wash. **Roadmap change:** `clean_every` in the depot model; the browser simulator's defaults set to the real cadence; the capacity figure stated at 600 for the 99% floor on one feeder at that cadence, 700 under long sessions (the 600 is capacity under the threshold rule, which calls vehicles in at 55% whether or not a charger is free; a rule that waits for a free charger might carry more); E21 sized against that; and the page's depot mode starts from the service area's residents and the filings' penetration, the direction a site team thinks in.

## What the pattern says

Eighteen turns, and in most of them the thing we believed mattered didn't, or mattered somewhere else than we thought. Each test's bars were fixed before its run, so the misses sit in the record beside the passes: 54 of 95 bars. The product moved each time the evidence did, never the other way round.
