# The Depot Twin

**I built a simulated depot to answer one question: how many vehicles one grid feeder can carry. A depot's grid connection sets how many vehicles it can run, and its software rules decide whether it gets there.**

I'd plan one feeder for 600 vehicles, 15,000 rides a day, put one software rule in first, and meter one vehicle before signing. This is an independent project on public data, not affiliated with or endorsed by Waymo.

## The decision you can't take back

You sign the lease and apply for the grid connection years before any vehicle shows up. Chargers and people arrive in weeks. A feeder takes two to four years, which is my assumption and not a utility quote. So the number you write down today is the number you live with.

As far as I can tell from outside, that number comes out of a spreadsheet today. The spreadsheet gets energy right. It can't see the queue, it can't see the peak, and it can't tell you which software rules get the depot to the number it promised.

## What I built

![How the twin is put together: a site file, the planner, the simulator and the one-page brief, with the forecast and hourly schedule beside it](images/architecture.svg)

A real East Oakland parcel with about 2.75 MW of published headroom on a feeder. Real San Francisco ride days, replayed. A simulator that follows every vehicle, charger, person and cleaning bay through the day. On top of that, a ride forecast, an hourly charging schedule, and a planner that reads any site file.

I wrote 35 tests with pass bars set before each run, not after. 96 of 145 bars passed. The misses are published alongside the passes, because a test you only report when it's green isn't a test.

## What I got wrong first

**I credited my hourly charging schedule for a gain it didn't produce.** It served 4.8 points more rides at 1,000 vehicles, and I believed it. Then I ran every rule for calling vehicles in against every rule for sharing power. The gain belonged to the power rule: feeding vehicles in the order they plugged in instead of emptiest first. A plain threshold with that same power rule serves 88.8% of rides against the schedule's 88.5%.

**I forecast ride counts when I should have forecast a ratio.** The count model missed every bar, 0 of 9, the moment the level of the series shifted. I changed the target to the ratio to the same hour last week, and that passed 5 of 9 bars.

**I gave each vehicle one hour-long charging visit a day.** Public quarterly filings count sessions, and a vehicle charges about every eight trips, roughly three times a day. Every capacity test since runs at that cadence.

**I read capacity off three runs of a single two-week window.** Four windows with ten random draws each showed that the draws barely differ and the windows differ by two points of rides. Forty runs are worth about four.

**I assumed a better forecast would buy me rides.** Where energy binds, perfect foresight and last week's curve serve the same share of rides. A better forecast tightens the safety margin. It doesn't buy a single ride here.

**I believed my hourly charging program decided when the fleet charged, and that the ride forecast was what made it smart.** It writes an hourly quota of vehicles to charge. At 500 vehicles that quota sat at its ceiling in 95.6% of hours, and at 600 it sat there in every hour. At the planned 600, the low-battery floor forces 7.5% of the plan's calls and the fleet rides at 31.6% charge. So the program wasn't choosing much. The clock and the floor were. The test that settles it is a threshold rule that waits for a free charger and knows only the clock. No forecast, no program. At 500 vehicles it pays $0.153 a kWh against the plan's $0.1675, 8.7% less, and serves 99.0% of rides against the plan's all of them. What I keep is this: the plan's worth is the energy price, not the rides. It's the honest baseline any forecast has to beat.

**I believed the 600-vehicle plan didn't depend on which vehicles ran.**

Every capacity test before then ran one fleet mix I'd assumed without checking: 60% Jaguar I-PACE, 40% Ojai. A new test swept the Ojai share from none to all - 0%, 40%, 70%, 100% - at my energy estimate and again with 10% more, forty runs a fleet. At the estimate, carried in all four two-week windows, the spread looked harmless: 650 all I-PACE, 675 at 40% and 70%, 700 all Ojai. With 10% more energy it stopped being harmless. 575 all I-PACE, 600 at 40% Ojai, 625 at 70%, 650 all Ojai. So the plan holds under that margin at 40% Ojai and above, and not with none; shares in between weren't run. I'd set a bar before the run - 600 holds at every mix - and it missed. The Ojai is the leaner vehicle on paper, 0.27 kWh a mile and 1.8 kW always on against 0.30 and 2.0, and neither of those numbers has a public source. A second test says the always-on load is the one that matters: at 1.5 to 2.5 kW, an all-Ojai fleet carries 775 down to 600. Battery size and charging curve move it by at most 25. So the plan now gets stated with its mix, and the always-on load is the first thing I meter.

**I believed a calling rule that knew the vehicle type would carry more.**

A third test called the vehicle with the least range left first. It carries 675 - the same as the rule that simply waits for a free charger. That bar missed too. Under the rule that waits, both types sit about 40 minutes a visit and arrive at the same charge; the Ojai comes in 2.7 times a day, the I-PACE 3.0. The rule that waits stays.

**I believed faster chargers would carry more vehicles, and that half as many of them would carry as much for less.**

Every capacity test before this ran 60 kW chargers, so neither type charged at its own top rate - up to 100 kW for the I-PACE, 150 kW for the Ojai, which is my assumption with no public figure behind it. So I ran six charger designs on one feeder and on two, at the assumed 60/40 mix and my energy estimate, three runs per two-week window across four windows. At the sizing rule's count, every design carried the same: 675 vehicles on one feeder, 1,350 on two. 150 kW cut the Ojai's median visit from 81 to 67 minutes, while the I-PACE's grew from 81.5 to 87, and carried no more vehicles, for about $405,000 a year more on one feeder. Half the count at 150 kW carried 625 and 1,250; my bar missed. Half at 60 kW carried none of the fleets run. Keeping the fast chargers for the Ojai carried no more than letting the first vehicle called take one. I keep the sizing rule's count at 60 kW, and I state the plan by feeder: 600 on one, 1,200 on two.

## What the evidence changed

At my energy estimate the feeder carries 675 vehicles, and those vehicles take 99% of its usable power. The answer is therefore only as good as the energy figure. That figure is mine, not an operator's, and whether a vehicle's systems keep running while it's parked isn't public. The exact figures are in [METHOD.md](METHOD.md).

So I moved it. 750 vehicles with 10% less energy. 625 vehicles with 10% more energy. 625 with systems left on while parked. 550 vehicles with both unknowns pulling the wrong way at once.

600 vehicles holds against either unknown alone, at the mix I assumed. That's the plan for one feeder; two carry 1,200.

The software lever is larger than I expected and costs nothing. Call a vehicle in only when a charger is free, and the same feeder carries 650 vehicles. A plain battery threshold carries 550 vehicles on the same feeder. No hardware involved.

The first action isn't a model change. It's a meter on one vehicle for a whole day. It settles the 125 vehicles between 550 and 675.

## What I chose not to build

I didn't rebuild the hourly charging schedule into a live controller. At 600 vehicles it serves the same rides as the simple rule. It buys energy 9.8% cheaper than the waiting rule at 600, $391,800 a year, and 19.1% cheaper than a plain threshold at 500, $636,300 a year. Next to the calling rule at $6.6M a year that's small, and at 500 a clock-aware rule buys cheaper still, so that saving belongs to a depot with power to spare.

I didn't forecast profit. Owning and running the vehicles is 54% of fare revenue, and neither figure has a public source. The account ranks depot designs against each other. It isn't a profit forecast and shouldn't be read as one.

I built a demand forecast for a place with no ride history and didn't keep it in the planner. Borrowed from other cities, its bounds didn't hold. Demand at a new site stays an input you supply.

I didn't build a live dispatch controller, user accounts, or scenario storage. A site file is a text file.

## What comes next

The next study is a separate project: on-site solar, a stationary battery, and paid grid events, where the utility pays the depot to shed load in certain hours. It asks how many vehicles and how many dollars a year solar and storage add to a depot capped at one feeder while it waits, and what that flexibility is worth when every kWh shed is rides not served.

A forecast should have a real job there. Each hour becomes a choice to store, draw or shed, and a wrong guess about rides, sunshine or price costs money or rides. A clock can't see a cloudy afternoon or a grid event.

Nothing in it is built or run yet. The requirements are written, and the bars get approved before any run. It will be tested against the same clock-aware rule that beat the forecast here.

## What I'd do with an operator's data

Replace three inputs: the energy a vehicle uses, the visit pattern, and demand. Keep the method and keep the tests, because the tests are what caught each mistake above.

Then run the twin beside one working depot for two weeks before trusting it for another. The simulator hasn't been checked against a real depot. Every capacity range here is four two-week windows of one spring in one city, and I'd rather say that plainly than let a clean number travel further than its evidence.

The twin doesn't decide anything. It puts a simulated day beside the spreadsheet in the argument about a lease.

The full findings are in [BRIEF.md](BRIEF.md), the turn-by-turn log in [DECISIONS.md](DECISIONS.md), and every test in [EVALS.md](../EVALS.md).
