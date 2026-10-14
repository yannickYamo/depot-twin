# The Depot Twin

**I built a simulated depot to answer one question: how many vehicles one grid feeder can carry. A depot's grid connection sets how many vehicles it can run, and its software rules decide whether it gets there.**

I'd plan one feeder for 600 vehicles, 15,000 rides a day, put one software rule in first, and meter one vehicle before signing. This is an independent project on public data, not affiliated with or endorsed by Waymo.

## The decision you can't take back

You sign the lease and apply for the grid connection years before any vehicle shows up. Chargers and people arrive in weeks. A feeder takes two to four years, which is my assumption and not a utility quote. So the number you write down today is the number you live with.

As far as I can tell from outside, that number comes out of a spreadsheet today. The spreadsheet gets energy right. It can't see the queue, it can't see the peak, and it can't tell you which software rules get the depot to the number it promised.

## What I built

![How the twin is put together: a site file, the planner, the simulator and the one-page brief, with the forecast and hourly schedule beside it](images/architecture.svg)

A real East Oakland parcel with about 2.75 MW of published headroom on a feeder. Real San Francisco ride days, replayed. A simulator that follows every vehicle, charger, person and cleaning bay through the day. On top of that, a ride forecast, an hourly charging schedule, and a planner that reads any site file.

I wrote 30 tests with pass bars set before each run, not after. 81 of 127 bars passed. The misses are published alongside the passes, because a test you only report when it's green isn't a test.

## What I got wrong first

**I credited my hourly charging schedule for a gain it didn't produce.** It served 4.8 points more rides at 1,000 vehicles, and I believed it. Then I ran every rule for calling vehicles in against every rule for sharing power. The gain belonged to the power rule: feeding vehicles in the order they plugged in instead of emptiest first. A plain threshold with that same power rule serves 88.8% of rides against the schedule's 88.5%.

**I forecast ride counts when I should have forecast a ratio.** The count model missed every bar, 0 of 9, the moment the level of the series shifted. I changed the target to the ratio to the same hour last week, and that passed 5 of 9 bars.

**I gave each vehicle one hour-long charging visit a day.** Public quarterly filings count sessions, and a vehicle charges about every eight trips, roughly three times a day. Every capacity test since runs at that cadence.

**I read capacity off three runs of a single two-week window.** Four windows with ten random draws each showed that the draws barely differ and the windows differ by two points of rides. Forty runs are worth about four.

**I assumed a better forecast would buy me rides.** Where energy binds, perfect foresight and last week's curve serve the same share of rides. A better forecast tightens the safety margin. It doesn't buy a single ride here.

**I believed my hourly charging program decided when the fleet charged, and that the ride forecast was what made it smart.** It writes an hourly quota of vehicles to charge. At 500 vehicles that quota sat at its ceiling in 95.6% of hours, and at 600 it sat there in every hour. At the planned 600, the low-battery floor forces 7.5% of the plan's calls and the fleet rides at 31.6% charge. So the program wasn't choosing much. The clock and the floor were. The test that settles it is a threshold rule that waits for a free charger and knows only the clock. No forecast, no program. At 500 vehicles it pays $0.153 a kWh against the plan's $0.1675, 8.7% less, and serves 99.0% of rides against the plan's all of them. What I keep is this: the plan's worth is the energy price, not the rides. It's the honest baseline any forecast has to beat.

## What the evidence changed

At my energy estimate the feeder carries 675 vehicles, and those vehicles take 99% of its usable power. The answer is therefore only as good as the energy figure. That figure is mine, not an operator's, and whether a vehicle's systems keep running while it's parked isn't public. The exact figures are in [METHOD.md](METHOD.md).

So I moved it. 750 vehicles with 10% less energy. 625 vehicles with 10% more energy. 625 with systems left on while parked. 550 vehicles with both unknowns pulling the wrong way at once.

600 vehicles holds against either unknown alone. That's the plan.

The software lever is larger than I expected and costs nothing. Call a vehicle in only when a charger is free, and the same feeder carries 650 vehicles. A plain battery threshold carries 550 vehicles on the same feeder. No hardware involved.

The first action isn't a model change. It's a meter on one vehicle for a whole day. It settles the 125 vehicles between 550 and 675.

## What I chose not to build

I didn't rebuild the hourly charging schedule into a live controller. At 600 vehicles it serves the same rides as the simple rule. It buys energy 9.8% cheaper than the waiting rule at 600, $391,800 a year, and 19.1% cheaper than a plain threshold at 500, $636,300 a year. Next to the calling rule at $6.6M a year that's small, and at 500 a clock-aware rule buys cheaper still, so that saving belongs to a depot with power to spare.

I didn't forecast profit. Owning and running the vehicles is 54% of fare revenue, and neither figure has a public source. The account ranks depot designs against each other. It isn't a profit forecast and shouldn't be read as one.

I built a demand forecast for a place with no ride history and didn't keep it in the planner. Borrowed from other cities, its bounds didn't hold. Demand at a new site stays an input you supply.

I didn't build a live dispatch controller, user accounts, or scenario storage. A site file is a text file.

## What I'd do with an operator's data

Replace three inputs: the energy a vehicle uses, the visit pattern, and demand. Keep the method and keep the tests, because the tests are what caught each mistake above.

Then run the twin beside one working depot for two weeks before trusting it for another. The simulator hasn't been checked against a real depot. Every capacity range here is four two-week windows of one spring in one city, and I'd rather say that plainly than let a clean number travel further than its evidence.

The twin doesn't decide anything. It puts a simulated day beside the spreadsheet in the argument about a lease.

The full findings are in [BRIEF.md](BRIEF.md), the turn-by-turn log in [DECISIONS.md](DECISIONS.md), and every test in [EVALS.md](../EVALS.md).
