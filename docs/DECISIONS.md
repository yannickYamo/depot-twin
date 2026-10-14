# Decisions: what I believed, what the test showed, what changed

[Back to the README](../README.md)

*The log of the project: what I believed at each turn, what the test showed, what I got wrong and what I changed. For a reader who wants to see how the work moved. The one thing to take: every correction came from a test or a public record.*


Eighteen turns. Most have the same shape because the work was run that way: a belief stated first, a test whose bars were fixed before its run, the result published whether it passed or missed, and the decision that followed. Where a turn rests on a study with no bars, it says so. The **Steer** line is the call I made at that point, where one changed the direction. Every figure is in [EVALS.md](../EVALS.md) under the test named, and the order of all thirty tests with the reason for each is in [its first section](../EVALS.md#the-path-through-the-tests); the account study's are in [METHOD.md](METHOD.md), section 6.

| # | I believed | The test showed | What changed |
|---|---|---|---|
| 1 | A spreadsheet can size a depot | It is right about energy and blind to the day | A simulated day on a real parcel |
| 2 | Forecast ride counts | A count model can't follow a change of level | Forecast the ratio to last week |
| 3 | The plan serves the extra rides | The power rule does | The power rule became the headline |
| 4 | Emptiest first loses by taking power from vehicles nearly done | It loses because power goes unused | The claim narrowed to a range, with its mechanism |
| 5 | Short sessions keep vehicles on the road | Energy a visit matters, not minutes | Slots are sized in energy |
| 6 | Visit frequency is unknowable | The filings count it | The twin runs at the filed cadence |
| 7 | Capacity is one number | It is two: what a feeder carries with margin and what it serves at its limit | Capacity is quoted with its rule, its margin and its spread, and the step between the two was run |
| 8 | A better forecast buys rides | It buys a tighter bound and no rides | The forecast is judged on its bound |
| 9 | One held-out window is evidence | It gives the order and not the size | A 26-week backtest on three series in two cities |
| 10 | The model I trained is the ceiling | A pretrained model is ahead | Mine stays the reference, not the candidate |
| 11 | A new site can borrow other cities' rhythms | Not well enough to beat last week | A new site starts on last week's curve |
| 12 | The plan pays for itself by reading prices | The clock does the work, and a threshold can read it | The saving is quoted with its range, as a clock |
| 13 | The account finds a best fleet size | The service floor finds it; the account pulls past | The lost ride is named as the deciding guess |
| 14 | The account is about the depot | It is mostly two guesses about the vehicle | The depot's own contribution is shown apart |
| 15 | A result stays true | It is true of the code that ran | Every record carries a stamp of its code |
| 16 | The shape of the week decides what a feeder carries | Twelve fortnights in three cities carry the same fleet | The method ships as a planner that reads a site file |
| 17 | The plan of 600 is settled | It holds to 10% more energy, 27.5 rides a vehicle a day and a peak 10% busier | The plan states its limits |
| 18 | A better plan would close the gap to the rule | The plan carries 600 on a third of a charge and buys 9.8% cheaper; a peak level of 25% lifts its charge | The rule that waits runs the planned fleet |

## What I got wrong, and what I did about it

Eight things I believed or built that didn't survive a test, and what I did about each.

1. **I credited the plan for a gain that belonged to something else.** I compared the hourly plan, which shipped with its own power rule, against simpler rules running a different one, and credited the plan with 4.8 points more rides at 1,000 vehicles, and 4.2 on fresh days (E8 and E9). Then a deliberately broken forecast barely dented the plan (E10), and a forecast that doesn't matter can't be the source of the gain. I crossed every calling rule with every power rule (E11), and the gain turned out to be the power rule's. The headline changed.

2. **I forecast the wrong quantity.** I forecast ride counts and got 0 of 9 bars (E7). A reporting change lifted recorded rides by about 45% just before the held-out days, and trees can't predict outside the range they've seen. I switched to forecasting the ratio to the same hour last week (E7b): 5 of 9 bars.

3. **I let a surrogate make decisions.** A search picked depot designs off a fast model of the simulator (E3). The designs it picked were predicted to earn 11.2% to 14.6% more than they actually did in simulation. Now the simulator stays in the loop for every decision and the model only shortlists.

4. **I gave each vehicle one long charging visit a day.** The public quarterly filings count sessions, and they come out at about three visits a vehicle a day. Every capacity test since runs at the filed cadence (E22).

5. **I quoted a capacity off three seeds on one fortnight.** Draws of one fortnight differ by a tenth of a point of rides, and fortnights differ by two points. I moved to four fortnights by ten draws, and gave "carried" an actual definition (E23).

6. **I chased forecast error as the goal.** Error sat at 11% to 12%, and my first attempts at cutting it moved no rides (the first-hour study). So I asked what a perfect forecast is worth (E16): nothing where energy binds. Three model changes that had helped in San Francisco then helped in New York and not in Chicago (E17, 0 of 4 bars). I now judge forecasts on the margin the bound asks for, over 26 weeks in three series (E24).

7. **I wrote a pass bar on a guess about the grid.** My bar expected the grid at its limit under a fifth of the time at the largest fleet that still met service (E19). That fleet was 700, at its limit 98% of the time, and the grid was already at its limit 63% of the time at 600. The account kept rising past the last fleet meeting the service floor. The service floor is a policy, not an output of the money. The account ranks designs; it doesn't pick the fleet.

8. **I was planning on a fleet my own estimate was holding up.** At 650, the fleet the capacity tests had carried (E25), the feeder was giving 97% of its usable power, and what fills it is a number I estimated. I moved the estimate 10% each way and left the parked load on (E26, E27). The feeder carries 675 at my estimate, and the plan became 600.

Every one of these was caught by a test or a public record, not by argument. That's why the bars are written before the runs and the misses stay published.

---

## 1. A spreadsheet can size a depot

**Belief.** The fleet in a city is capped by what one depot can turn around. Chargers and people arrive in weeks and a grid connection in years, so the number of vehicles a site carries is decided at the lease, usually from an energy total.

**Steer.** I chose a real Bay Area parcel, the 200 to 2,000 vehicle range, and the rule that everything is rebuilt from public data.

**Experiment.** A hand calculation against a simulated day (E2, the growth studies). They agree on energy and disagree on the day: the queue at the evening peak, and the hour half the fleet returns empty together.

**Changed.** The product is a simulated day, held to the hand calculation where the two should agree.

## 2. Forecast ride counts

**Steer.** I chose gradient-boosted trees, on a chronological split with a block that tuning never sees.

**Experiment.** E7 forecast counts and missed every bar: a reporting change in February 2024 raised recorded rides by about 45% just before the held-out days, and a tree model doesn't extrapolate past the levels it was trained on. E7b changed one thing, the target, to the ratio to the same hour last week, and passed 5 of 9.

**Changed.** The target's definition was the binding thing, not the model's settings. Every forecast since predicts a ratio.

## 3. The plan serves the extra rides

**Belief.** A controller that plans the next 24 hours against the forecast would serve more rides than a rule that fills every free charger. E8 and E9 agreed: 4.8 and 4.2 points more at 1,000 vehicles.

**Steer.** I decided to attribute each gain to its part before adding features.

**Experiment.** E10 fed the plan a broken forecast and it barely moved. E11 crossed every calling rule with every power rule: with power fed in order of arrival, a plain threshold serves 88.8% and the full controller 88.5%. At that fleet size the low-battery floor, not the plan, was making every call.

**Changed.** I made the power rule the headline, since it costs nothing: no new hardware, a setting in the charging software. Over forty runs at the filed cadence it's worth 8.8 points of rides at 1,000 vehicles under a plain threshold (8.2 to 9.4; E23), and nothing at 500 and 600, where the feeder has power to spare. It's insurance for the day a fleet outgrows its feeder.

## 4. Why emptiest first loses

**Belief.** Feeding the emptiest vehicle first loses because each arrival takes power from a vehicle that was nearly done.

**Experiment.** The staffing study measured the cause under long charging visits: emptiest first evens out every plugged-in vehicle, they finish together, and 7.5% of the site's power goes unused while they wait to be unplugged. The gap closes from 6.5 points to 2.9 as people are added and no further, the same to a tenth of a point in each of ten runs. E14 repeated it on another city's days and added the textbook rule, least energy remaining first, which ties with in-order feeding.

**Steer.** I read the published work before building more, so as not to reinvent the wheel. Scheduling theory already names the rule that finishes jobs one after another; what the twin adds is the interaction with the people who unplug.

**Changed.** The explanation is the measured one, and the rule is stated more broadly: feed at full rate in any order that finishes vehicles one after another.

## 5. Short sessions

**Belief.** Thirty-minute sessions would keep more vehicles on the road.

**Experiment.** The session-length study varied slot length, drive time and charger power. Under one long visit a day, a visit that delivers 26 kWh loses 14 to 18 points of rides. Distance barely mattered, and a 20-minute slot at 150 kW serves as many rides as an hour at 60 kW.

**Changed.** A slot is sized in energy, about 40 kWh a visit under the long visits this was measured on, and the finding is stated as a rule about chargers. At the visit pattern of the filings, which came later, the plan runs slots of about 26 kWh.

## 6. How often a vehicle visits

**Belief.** Visit frequency could not be known from public data, and the twin's one long visit a day was as good a guess as any.

**Steer.** I asked which known patterns hold for a new city, and went to the filings for the answer before planning anything.

**Experiment.** The quarterly filings count chargers and charging sessions: a vehicle charges every 7.5 to 9.4 trips, about three times a day. E22 found the setting that reproduces it, and found that the cost of a visit is the wash, not the drive: with cleaning on every visit, 2.3 visits a day cost 13.6 points of rides at 700 vehicles (the sensitivity study); with a wash every fourth visit, three visits a day cost none at 500.

**Changed.** The twin and the page run at the filed cadence, and cleaning frequency is an input.

## 7. Capacity is one number

**Belief.** One feeder carries a number of vehicles, and three seeds on one fortnight are enough to read it.

**Experiment.** E23 ran four fortnights by ten draws, at five fleet sizes, under three calling rules, each fortnight replayed until the fleet had settled. A plain threshold, which calls a vehicle in whether or not a charger is free, carries 500. The same threshold waiting for a free charger carries 600: every run serves 99% of rides, no vehicle arrives at the low-battery floor, and the feeder runs at 90% of its usable power. At 700 the depot still serves every ride in the median run, but the feeder is at its limit in every step and 68% of depot visits start at the floor. The floor is running the depot and the rule under test isn't, so 700 is served and not counted as carried. One of the four fortnights carries it and three don't. Moving the rides a vehicle serves moves the count of vehicles more than the rides: at its limit, still holding the 99% floor, the feeder serves 17,200 to 18,000 rides a day whether the fleet is 700 at 25 rides a vehicle, 800 at 21.5 or 1,000 at 18.

That left the answer between two steps, and the verdict on 700 resting on a line I had drawn by judgement: no more than half of depot visits starting at the low-battery floor. So E25 ran the fleet halfway, on the same forty fortnight-and-draw pairs, and asked whether its verdict moved with the line. 650 vehicles serve at least 99.9% of rides in every one of the forty runs, none arrives at the floor, and the feeder runs at 97% of its usable power. Its verdict is the same with the line at a quarter, a half or three quarters; the verdict on 700 isn't.

At 650 the feeder was giving 97% of its usable power, and the one figure that fills it, the energy a vehicle uses on the road, is an estimate. E26 moved it 10% each way, in steps of 25 and 50 vehicles on the same forty pairs, and put the plain rule on the same steps as the waiting rule. The feeder carries 750 vehicles with 10% less energy use, 675 as estimated and 625 with 10% more: the carried fleet times its energy level is 675, 675 and 688, so the feeder's energy is what binds, once the rules are right and short of the two inputs, ride length and rider patience, that run the vehicles short first. On the same steps of 50 the waiting rule carries 650 and the plain rule 550. 5 of 5 bars. The registered rule for the fleet to plan on, the largest carried at both levels of energy use, gives 625. At 625 with 10% more energy the feeder is at its limit in every step of the median run and one fortnight of four isn't carried, so I plan on 600, which is carried in every fortnight at both levels. That fortnight fails at 58% of visits starting low against a line at 50%, so the verdict on 625 turns on the line.

E27 then counted the one load the model assumes away: a parked vehicle's always-on load, which the model switches off at the depot gate. Counted, the feeder carries 625 at the estimate, and 550 with 10% more on the road as well, in every fortnight. 600 holds against either unknown alone. 3 of 3 bars. I also split the spread of the forty runs: the ten draws of a fortnight are near copies, so the forty are worth about four.

**Changed.** Six things. Capacity is quoted as three figures with the rule and the spread beside them: 600 vehicles and 15,000 rides a day to plan for, 675 carried at the estimated energy use, 700 served at the limit. The plan is the fleet that survives either unknown about a vehicle's energy, with 550 named as the fleet that survives both, and metering a real vehicle's whole day became the first step of the rollout. Ranges are described as what they are, the spread across four fortnights. A fleet is counted only where the rule being tested is the one in charge. Every capacity figure is a median over forty runs with its range. And where a verdict turns on a line drawn by judgment, the line is moved before the figure is quoted.

## 8. A better forecast buys rides

**Steer.** I judged an error of 11% to 12% too high and set out to cut it, then wrote the test that would say whether cutting it was worth anything.

**Experiment.** E16 ran the plan on perfect foresight, the model, last week's curve and a feed cut to a third, in four regimes. Where energy binds the forecast is worth nothing. Where vehicles bind it is worth nothing either: perfect foresight serves 99.20% of rides and last week's curve 99.22%. What the forecast does decide is the reserve the plan keeps on the road: 50 to 100 vehicles with the model's bound, 64 to 127 with last week's.

**Changed.** Forecast error stopped being a goal for this depot. The forecast is judged on its bound and on sites with no history.

## 9. One held-out window is evidence

**Belief.** A model scored once on 60 held-out days has been tested.

**Experiment.** E17 took three modeling recipes that all helped on the development city to reserved windows in two others: 0 of 4 bars. E24 then forecast each of 26 weeks, on three series in two cities, from the days before it, and read the error week by week. The single windows had the order right and the size wrong: one window put the pretrained model 2.7 points ahead on New York taxis, and 26 weeks put it 1.3 ahead.

**Changed.** The rolling backtest is the comparison the documents quote. A bound that adapts hour by hour holds its 95% in all three series where a fixed one drifts, at a stated cost in width. It's a choice for steadier weekly coverage, not a sharper bound.

## 10. The model I trained is the ceiling

**Belief.** After E17, that the uncertainty estimate and not the point forecast was where the reserve could be won, and that tuned trees were near what the data holds.

**Experiment.** E18 separated the two. A volume-aware bound held more vehicles, not fewer. A pretrained model used as it comes held 5.8 fewer at the same reliability. Over 26 weeks (E24) it's ahead on all three series by 0.45 to 1.33 points one hour ahead, and in Chicago, the series least likely to be in its training data, by 0.45 points with a range clear of zero.

**Changed.** The trees trained here stay as the controlled reference: local, reproducible from public data. The pretrained model is the candidate where its dependency is acceptable. The ceiling I had assumed was my own models'.

## 11. A site with no history

**Steer.** I made this the priority and set the standard: generated data for a new location, set up and trained properly, with its error stated even though it can't be validated there.

**Experiment.** E13 trained across three cities and held each out: 1 of 4 bars. The borrowed forecast beats last week's curve in eight of nine cells and is behind a model trained on the place's own rides in all nine; its bounds do not carry across cities. E15 found the average generated scenario kinder than real days and the worst of ten a safe reading.

**Changed.** A new site runs on last week's curve, with the guard on, until it has a few weeks of its own rides. Its capacity is quoted from the worst of ten generated scenarios, with the spread beside it.

## 12. The plan pays for itself by reading prices

**Belief.** A plan that knows the price of each hour would buy energy noticeably cheaper.

**Experiment.** E12: told the tariff, the plan pays 14% less a kWh than a threshold under long visits, and a plan whose optimizer cannot see prices pays the same. The whole saving is steering by the clock around the evening peak. A threshold that waits for a free charger and follows the same clock pays less still at 500 vehicles, $0.153 a kWh against the plan's $0.1675, serving 99.0% of rides to the plan's 100%, and the plan's hourly program sits at its ceiling in 95.6% of hours. 4 of 6 bars. E20 gave it an hourly price and that fortnight's curve was too flat to follow: 0.2%. At the filed cadence over forty runs (E23) the saving is 19.1% (17.7% to 20.0%) with rides level.

**Changed.** The saving is quoted at the filed cadence with its range, and described as what it is: a clock, which a threshold can read as well. Energy is under 4% of fares, so this is worth having and is not what makes a depot work.

## 13. The account finds the best fleet size

**Steer.** I wanted a financial account counted the way an operator counts, and chose the service's own price structure for the fare over a flat average or a taxi meter.

**Experiment.** E19, 0 of 4 bars. Contribution rises one step past the last fleet that meets the service floor: 800 vehicles earn more than 700 while serving 98.5%. Busy pricing moves the fare between hours and leaves the average at the published $19.69, so scarcity does not pay.

**Changed.** The sweet spot is stated as a service decision. On the capacity test's forty runs, 800 vehicles earn more than 700 only while a lost ride is valued under $37 beyond its fare at the median, and anywhere from $4 to $159 across the runs. That value is a guess, so it is shown as the figure the decision turns on.

## 14. The account is about the depot

**Belief.** A ranking of designs by contribution a day says something about the depot.

**Experiment.** The account study moved each input alone across a stated range. Owning and running the vehicles is 54% of fare revenue at 600 vehicles, and both figures are assumptions with no public source; each swings the result by more than every depot input together. Energy is 3.7% of revenue.

**Changed.** The depot's contribution before the fleet's cost is shown apart, every input is labeled measured, published or assumed, and the ranking is presented as conditional on two guesses.

## 15. A result stays true

**Belief.** A result file written last week describes the code today.

**Reasoning.** A simulator keeps changing while its results are being read. The same test run on a later tree gives another number, and a bare result file cannot say which tree it belongs to.

**Changed.** Every record carries a hash of the code that produced it, and of the records it was built from. `depot-twin stale` names any record the tree has moved away from; the figures the documents quote are read from the records and tested against them (`docs/FACTS.json`); and `depot-twin reproduce` runs six of the headline runs again on a fresh clone, from inputs kept in the repository.

## 16. The shape of the week decides what a feeder carries

**Belief.** A capacity figure measured on San Francisco's spring weeks belongs to those weeks, and another city or season would move it.

**Experiment.** I wrote the capacity method as a planner that reads a site from a file, and gave the same depot other demand: its own weeks counted by the hour, and four fortnights each of Chicago and New York ride-hail, one from each season. Twelve fortnights, three cities, and the feeder carries 675 vehicles in every one. Past it, 700 fails in one to three windows of four each time.

**Changed.** The method ships as `depot-twin plan` with a site file, an input reference and a one-page brief, and the East Oakland study is its first case. What limits a feeder at a fixed level of rides is energy, so the two inputs a planner has to get right are that level and what a vehicle takes in a day. The shape can be borrowed.

## 17. The plan of 600 is settled

**Belief.** The capacity answer holds 10% either side of the energy estimate, at 25 rides a vehicle and at one cadence setting. Four further inputs could each move it, and the call-in level and the cleaning interval are fitted to one pair of filed counts, so I moved them before calling 600 settled.

**Experiment.** E28 moved four things one at a time: energy to 20% and 30% more, rides a vehicle to 27.5 and 30, the busiest fifth of hours 10% and 20% busier, and every call-in level and cleaning interval that matches the filings. The fleet follows the fleet carried at the estimate, scaled by energy, as far as 30% more: 575 at 20% (a registered bar) and 525 at 30% (run, with no bar). All eight matching cadence settings carry 675. A peak 10% busier leaves 675 carried. With the peak 20% busier, 600 misses 99% in the fortnight of 18 March, its lowest run at 98.98% of rides, while 650 and 675 hold in every run; a fleet counts as carried only when every smaller one is, so none does. At 30 rides a vehicle no fleet from 525 to 600 is carried, with the feeder at 84% to 95% of its power. 3 of 5 bars.

**Changed.** The plan states its limits: up to 10% more energy than estimated, up to 27.5 rides a vehicle a day, and the busiest hours up to 10% busier. Past that level of rides the thing a site runs out of is vehicle time at the peak, not grid. The cadence setting does not decide the answer.

## 18. A better plan would close the gap to the rule

**Belief.** The plan's fleet rides at about a third of a charge where the rule that waits keeps two thirds, so the plan needs fixing: a setting, a longer view, or a larger reserve.

**Experiment.** The record already showed the plan serving 100.0% of rides at 600 in the median run and carrying them, with 19% of its visits starting on a low battery. E29 moved its peak call-in level, its reserve and the length of its view. As tested, at 600 the floor forces 7.5% of the plan's calls and the fleet rides at 32% of a charge, short of the half I asked for. At a peak level of 25% no visit starts low at 600, the charge rises to 40%, and the saving at 500 is kept: 19.1% against 19.2%. A 12-hour or a 36-hour view moves nothing. At 600 the plan buys energy 9.8% cheaper than the rule that waits. 4 of 5 bars.

**Changed.** I did not rebuild the plan. At the planned fleet the rule that waits stays the controller to run: the plan carries 600 and buys cheaper energy, but on a third of a charge. The plan belongs with its peak level at 25%. A plan that saw the spread of charge across vehicles is the next thing to build, and the test says what it could and could not win: margin, not energy cost.

---

## Decisions outside the tests

Not every decision came out of a test. These are choices about the tool itself, each with what it costs.

- **Strict site files.** The planner refuses a site file with an unknown table or field, a value of the wrong kind or outside its usual range, or a demand file with a gap, a repeat or a clock change, before anything runs. It costs a flag, `--allow-unusual`, for the rare value that is meant. I took it because a typo or a slip of units would otherwise plan the wrong site without saying so.
- **Unsettled runs don't count.** In the planner a window whose run is still moving after its last replay isn't counted as carried, and the brief says the carried fleet may be a step low. That is stricter than the registered tests, which report unsettled runs and count them. A run counts as settled when its low-battery visits, its rides served and the charge its fleet rides at have all stopped moving between replays. I took it because the planner runs two draws a window, and one unsettled run can decide a fleet.
- **Plans are held to their inputs.** Every plan keeps a hash of its site file and of each demand file it names, and `depot-twin stale` names a committed plan whose inputs have changed. It costs a rerun of about an hour when a site file is touched. It stops a plan outliving the file it was made from.
- **The parked load is counted as energy (E27).** A parked vehicle's always-on load is taken from its battery when it leaves the depot, not drawn through the charger while it's plugged in. The day's energy is right and the minute it is drawn is late by a visit, so 625 reads as an energy sensitivity and not an electrical model. I took it because it left the simulator's code and every other record unchanged.
- **Weather for the target hour comes from a stitched archive.** The archive joins the first hours of successive forecasts, so at 24 hours ahead it is a little better than a real forecast would have been. Without weather the error moved by under a point at every horizon, so it stays in as registered, and the limit is stated where the features are evaluated.
- **The pretrained model's revision is recorded, not pinned.** The hub commit of the model's files and the package version are in the E18 and E24 records. A later run takes whatever the hub then serves, so its commit has to be checked against the record before figures are compared.
- **The page leads with a short version.** One screen that reads in about 90 seconds, with one control, sits in front of the full twin, and the twin has three tabs: Depot, Decisions, and Under the hood. It costs a click to reach the simulator. I took it because a first reader needs the decision and the answer before the machinery.
- **The front door states less.** The README and the story are held to two findings, the planned fleet and the calling rule. The findings document is held to every finding with its range. The second feeder and the power rule moved off the front door, and the test that checks the documents against the records enforces the split.
- **No hosted app, no accounts, no saved scenarios.** The planner is a command that reads a text file and writes one page. Version control already keeps, compares and shares text. A local tool for trying settings exists (`depot-twin app`) and stays local.
- **The page runs its own simulator.** The browser simulator is a second implementation, held to the Python one by a parity test. It costs two simulators to keep in step. I took it so that anyone can change a design and watch it without a server.

## What the pattern says

In most of these turns the thing I believed mattered did not, or mattered somewhere else. The bars were fixed before each run, so the misses sit in the record beside the passes: 81 of 127 bars. The product moved each time the evidence did.

## How this was built

I picked the question, the site, the test design, the pass bars, and what to cut. Every decision in this log is mine.

I used an AI coding assistant, Claude Code, throughout: writing code, running the experiments, drafting the documents, and reviewing them. I checked results against the records, rejected or redirected work that didn't hold up, and reran tests whenever the code under them changed.

The safeguards don't depend on who typed the code. Bars are fixed before each run, not after I've seen the numbers. Every result is stamped with the code that produced it. Every figure in these documents is checked back against its result file.

The judgment calls stayed with me.
