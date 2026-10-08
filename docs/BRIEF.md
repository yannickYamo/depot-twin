# Product brief: the depot twin

**A robotaxi earns only while it's on the road, and the depot decides how much of the day that is. We built a twin of a real East Oakland parcel to answer "how many vehicles will this site carry" before the lease is signed instead of finding out in production. The first answer costs nothing: change how the site shares power, and one feeder carries 9 more points of rides at 1,000 vehicles.**

This is an independent project built on public data. It isn't affiliated with or endorsed by Waymo.

## The problem

Every vehicle comes back to a depot to charge and be cleaned, and the depot's capacity to turn vehicles around sets the ceiling on the service.

Chargers, people and cleaning bays get added in weeks, and a grid connection takes years. So the parcel and its feeder are the lease-time decision, and they're the one you can't walk back.

Today that decision is made with hand arithmetic and then settled in production. Arithmetic gives you the energy limit. It misses everything on the way there: queues at the chargers, the evening when half the fleet comes back empty at once, people busy elsewhere, power shared badly.

## Who it's for

**Depot planning.** Chooses and sizes sites. Needs to know what a parcel's grid connection is worth in vehicles before signing.

**Fleet operations.** Runs the site day to day. Needs rules for calling vehicles in and sharing power that protect the peak.

**Market expansion.** Sets the fleet ramp for a city. Needs the date the current sites run out.

## What success looks like

One number at the top: **rides served as a share of rides offered.** The cost of a depot that can't keep up is a ride nobody serves.

Underneath it, the things that move it:

- vehicles on the road in the busiest hours: what the depot gives back when it matters
- time in the depot per visit: queue, charge, clean
- energy delivered per visit: a visit that delivers little is overhead
- energy delivered per day against what the site can deliver: the hard ceiling
- vehicles stranded: must be zero

Beside it, once service holds: price paid per kWh, whether the depot's hourly promise of vehicles on the road is kept, contribution per vehicle-day.

## The site

A real parcel in East Oakland, 14.5 acres. PG&E publishes grid headroom of about 2.75 MW on each of two feeders. The site's load manager draws 95% of a connection, because code treats charging as a continuous load and a load manager keeps a margin. Demand is replayed from real San Francisco days.

Every figure below comes from a test with its bars fixed before the run. The record is EVALS.md, indexed in docs/SCOREBOARD.md. 23 tests, 54 of 95 bars passed, and the misses are in the record.

## What the twin showed, in order of what to do first

### 1. Change how power is shared before buying anything

When the site is short of power, feed plugged-in vehicles in the order they plugged in, at full rate.

Against the obvious rule (emptiest first) at 1,000 vehicles on one feeder: 77.0% of rides served becomes 86.1% at the filings' visit cadence, and 82.9% becomes 88.8% with long visits. The gain is 3 to 6.5 points depending on staffing. It repeats on real Chicago days, 85.3% against 78.0%. "Least energy left first" ties with in-order.

Emptiest-first fails because it evens out the charge of everything plugged in. Vehicles then finish together and stand on chargers waiting to be unplugged, 32 at a time against 3, and 7.5% of the site's usable power goes unused. Fed in order, they finish one after another.

### 2. What the site carries

| Fleet | One feeder (2.75 MW) | Two feeders (5.5 MW) |
|---|---|---|
| 600 | 100.0% | 100.0% |
| 700 | 99.9% | 100.0% |
| 800 | 98.0% | 100.0% |
| 1,000 | 87.6% | 100.0% |
| 1,200 | 75.8% | 100.0% |
| 1,500 | 62.1% | 99.2% |
| 2,000 | 46.8% | 87.6% |

The table is share of offered rides served over a week, on the plan with in-order feeding and long charging visits, one a day.

One feeder carries about 600 vehicles at 25 rides a day against a 99% floor at the filings' cadence of three short visits a day, and about 700 with long visits. At 18 rides a day, 1,000 vehicles serve 99.9% with long visits. Hand arithmetic on energy says about the same; the twin adds what happens on the way there.

Energy per mile moves the ceiling about one fleet step, 100 vehicles, per 10%.

A second feeder doubles the site: up to 1,500 vehicles at 99% with long visits. 2,000 vehicles don't fit on this parcel's grid at all, and that needs a third source, a substation project, or a second site.

Worth noticing: the grid saturates before service breaks. At 700 the feeder is at its limit nearly all the time and 99.9% of rides are still served, because the fleet's batteries carry the day. Service breaks a step up.

### 3. What a day-ahead plan is for, and what it isn't

A controller that plans the next 24 hours every hour from ride forecasts (a linear program, first hour acted on, redrawn hourly) serves no more rides than a fixed threshold with in-order feeding. Handed forecasts wrong by a factor of three, it serves the same rides. For rides, it isn't needed.

What it buys is cheaper energy, safely. Steering charging out of the 4 pm to 9 pm peak pays 12.2% less per kWh with no loss of rides at 500 vehicles with long visits, and 6.9% less at the filings' cadence. The steering is by the tariff's clock: the plan with its hourly optimizer blind to prices pays the same. A plain threshold that knows the clock buys nearly as cheap, 10% less, and loses 5 points of rides doing it. The plan's part is keeping the rides. The saving only exists where the site has headroom. Told an hourly wholesale price instead, it buys 0.8% cheaper: April's day-ahead prices were too flat to steer by.

It also makes a promise. Each hour it states how many vehicles it will have on the road. It promises 94% to 97% of what it delivers, and keeps the promise in 96% to 98% of hours.

Past about 700 vehicles on one feeder the plan isn't really deciding anything. At 1,000, 98% of its calls are the low-battery floor.

The forecast's value here isn't rides. It's the reserve of vehicles the plan holds for the forecast's upper bound, 50 vehicles with the trained model, 64 with last week's curve. A better bound is worth vehicles, not rides.

### 4. Size a visit by energy, not minutes

A visit costs road time whatever it delivers: drive in and out, plugging, cleaning. So size it by what it delivers.

A visit of about 40 kWh serves all or nearly all rides. 26 kWh loses 12 to 17 points when every visit is cleaned. With 60 kW chargers, 40 kWh is about 45 minutes, and a 20-minute session serves 57% to 63% of rides. With 150 kW chargers, 20 minutes is enough. Short sessions are a fast-charger design, or a design that keeps the wash off most visits.

### 5. The real visit cadence, from the filings

The quarterly filings count chargers and charging sessions. A vehicle charges every 7.5 to 9 trips, about three times a day, and each charger sees 14 to 21 sessions a day across 2025 Q1 to 2026 Q2, about 20 in the last three quarters.

The twin's long-visit setting goes to the depot 1.3 times a day for an hour. It reproduces the real cadence when vehicles are called in at 55% and cleaned every fourth visit: 3.2 visits a day of 8 trips. Every second visit is nearly as good, 99.7% of rides. With a wash on every visit the same cadence serves 88%. The cleaning bay is the cost of a visit, not the drive.

At the filings' cadence: in-order feeding beats emptiest-first by 9 points at 1,000 vehicles, steering by the clock buys 6.9% cheaper energy, and one feeder's capacity at the 99% floor reads 600 against 700 with long visits.

### 6. The demand around the parcel

The filings' served tracts over census populations give 0.17 trips a resident a month, growing 5.2% a month at a constant footprint. That's a scale-up rate, and we show half of it beside it.

The East Bay within 20 km of the parcel has 1.08 million residents, about 6,000 rides a day today, 241 vehicles. That sits inside one feeder's 600. As a scenario rather than a forecast: if the measured scale-up growth continued, a second feeder would be needed in about 19 months, and at half that rate, about 36.

Today the parcel is demand-bound, not grid-bound. The question is when the room runs out. There's no density adjustment yet, and a sparser area than the served footprint likely makes less.

### 7. The money, and the service floor

There's an account on every design: fares, energy by tariff or wholesale pass-through scenarios, subscription, chargers, storage, connection, land, people, vehicles at $60,000 a vehicle-year, running them at $100 a vehicle-day, and a lost ride beyond its fare at $20. The last three are parameters.

A ride pays the published average fare, $19.69. Busy pricing (flat to 80% of the fleet busy, up to 1.3 times at full use) moves the price between hours and leaves the average there. Scarcity doesn't pay, so a lost ride is only ever a loss.

On one feeder, the best fleet at the 99% floor is 700 vehicles with long visits, $126,200 a day. But 800 vehicles earn $8,700 a day more while serving 98.5%: 295 lost rides a day cost less at $20 each than a hundred more vehicles earn. Past 800 the account turns hard, and 1,200 lose money. The floor has to be a decision taken against the account, not read off it.

On two feeders, contribution rises through 1,200 vehicles at $219,700 a day, and the best size lies beyond the range we swept.

One and a half times the chargers buys nothing.

Under a wholesale pass-through, energy would cost about $0.10 a kWh against $0.16 to $0.20 under the tariff. That's a scenario for an operator with such a contract, not what this site pays.

## The decision this supports, for a site like this one

1. Share power in order of plugging in. First, free, and worth more than anything you can buy quickly.
2. Open on one feeder, and apply for the second the day the lease is signed. At the measured growth the East Bay needs it in under two years. One feeder is good for about 600 vehicles at a 99% floor, two for up to 1,500.
3. Keep the wash off the charging path: clean every fourth visit, and let vehicles top up often.
4. Plan the second site before the fleet passes 1,500.
5. Steer charging around the evening peak once there's headroom to use, and run the day-ahead plan for the hourly promise. Don't expect rides from either.
6. Set the service floor as policy, then size to it. The account alone will pull you one step past it.
7. If sessions are meant to be short, buy chargers to match.

## Trade-offs taken

**Aggregate service, detailed depot.** Rides on the road are modeled in bulk; the depot is modeled vehicle by vehicle, minute by minute. The question is the depot.

**Demand from taxis.** There's no public hourly ride-hail data for the East Bay, and robotaxi trip times are redacted in the filings. We use San Francisco taxi trips, scaled, and shape from other cities for a new site.

**Energy per mile estimated.** No public measurement exists for these vehicles. The ceiling moves in proportion.

**Simple rules first.** Each more elaborate rule had to beat a simpler one in a test registered in advance. Several didn't.

## What this version leaves out

- the capacity charge on the month's highest draw: only the price per kWh by time of day is in the plan
- more than one depot, and which depot a vehicle returns to
- charger and vehicle failures
- parking: there's no cap on vehicles waiting in the yard, since 14.5 acres hold far more than any recorded queue
- whether both strong feeders would actually serve one parcel. It's on the map, not verified

## The first version, kept

A search over depot designs (chargers, power, battery size) was built on the first version of the twin, before in-order feeding, per-vehicle energy and replayed demand. A fast stand-in for the simulator ranks designs, and the search then picks the designs the stand-in likes best, which are exactly the ones it's most wrong about. We keep it as the record of the first version. A stand-in shortlists; the simulator decides.

## How the figures are held

Every result file carries a stamp of the code that produced it. Change the model and the result is marked stale until it's run again.

The depot is implemented twice, in Python and in the browser. Each is held to its own invariants, then to the other within half a point of rides at 500 vehicles and a point and a half at 1,000.

The depot tests from the controller on record the cadence each run actually ran at, and whether its rule or the low-battery floor was calling vehicles in.

## What would prove this wrong

- measured energy per mile far from the estimates. The whole ceiling scales with it
- a real depot where vehicles aren't held to a full session by plugging and cleaning overhead
- a demand peak in the East Bay much sharper than San Francisco's
- utility headroom that isn't what the map says once an application is filed
- a fleet management system that already shares power in order. Then the largest gain here is one the operator already has
- a service that doesn't price by demand. Then the account's pull toward saturation is weaker than shown

## Rollout

1. **Shadow.** Run the twin beside one live depot for a month. Compare predicted and actual queue, grid draw, vehicles on the road, and fix what's off.
2. **The power rule.** Trial in-order feeding on part of one depot's chargers, with the current rule as control. Cheapest to test, most valuable if it holds.
3. **Planning tool.** Size the next site before the lease.
4. **The plan.** Shadow first: ask it every tick what it would do, never act on it. Then let it steer charging around the price peak, behind the guard that hands control back to the simple rule if its forecasts break.
