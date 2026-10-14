# Product brief: a lease-time depot planner

**The decision this serves is made once, years before the vehicles arrive, and the spreadsheet that makes it today can't say what happens when it's wrong.**

## The user

The person at a robotaxi fleet operator who signs a depot lease and applies for its grid connection.

## The decision

How many vehicles this site and its grid connection will carry, and what to do first to carry more.

Chargers and people arrive in weeks. A new feeder takes two to four years - my assumption, not a utility quote. So the lease signature and the connection application are the same decision, and it's taken long before anyone can watch a vehicle plug in.

## Today

As far as I can tell from outside, the number comes from a spreadsheet of energy arithmetic. The spreadsheet gets the energy about right. It can't say which operating rules reach a given fleet, or what's left when the energy estimate is wrong.

## What this does

A site file goes in: grid connection, vehicles and their energy use, depot, rules, the weeks of ride demand to replay, and the share of rides that must be served. A one-page brief for the lease meeting comes out - the fleet to plan for, the fleet carried if the estimates are right, what binds past it, what each change is worth in vehicles, and which inputs are measured and which assumed.

```
depot-twin plan sites/east_oakland.toml
```

On the East Oakland parcel: plan 600 vehicles, 15,000 rides a day. 675 carried if the energy estimate is right. The planner tests each uncertainty on its own. The study ran both together, 10% more energy on the road and systems left on while parked, and that carries 550. The plan is read at an assumed mix of 60% I-PACE and 40% Ojai; an all-I-PACE fleet with 10% more energy carries 575.

The file is checked before anything runs. A value outside its usual range (a slip of units), an unknown field, a demand file with a gap - each is refused before anything runs, with the field or the line named.

## Who else could use it

- **Real estate:** sign for this fleet at this site, or not.
- **Energy and utilities:** apply for a second feeder now or later.
- **Depot operations:** which two rules go into the dispatch and charging software first. Call a vehicle in only when a charger is free for it; feed vehicles in the order they plugged in. They cost no hardware.
- **Finance:** when the capital for chargers and the connection is committed.

## How I would know it works

The measure that matters is the gap between the fleet planned at signing and the fleet the site carries in its first year of operation. I can't measure that yet.

What I can measure today: a plan for a site takes about an hour on a laptop. Every figure in the brief comes from a simulated run that can be run again. 35 registered tests with pass bars fixed before each run; 96 of 145 bars passed; misses published.

## What a real deployment would need

This study stops at public data, and the simulator hasn't been checked against a real depot. With an operator, these are the steps, in order.

1. Meter one vehicle through a whole day, on the road and parked. 125 vehicles of the answer - the span from 550 to 675 - rest on that one measurement.
2. Run the twin beside one working depot for two weeks and compare three things: the queue for a charger, the energy drawn from the feeder, and depot visits a vehicle a day.
3. Plan a second site from its file and compare with what that site carries.

With an operator's own data, three inputs get replaced: the energy a vehicle uses, the visit pattern, and demand. The method and the test discipline stay.

## Roadmap

- **Now:** lease planning. One connection at one site, from a file.
- **Next:** an operations twin, fed by a depot's own telemetry, once the simulator has been checked against a real depot.
- **Later:** a set of sites ranked by how long each grid connection takes.
- **A separate study:** on-site solar and storage for a depot capped at one feeder, and what its flexibility is worth to the grid. Energy is what binds at this depot.

## Not building

- **A profit forecast.** The account ranks depot designs. Owning and running the vehicles is 54% of fare revenue at 600 vehicles, and neither figure has a public source.
- **A live dispatch controller.** Tested: at the planned fleet an hourly plan serves the same rides as a simple rule and buys energy 9.8% cheaper. Its program sits at its ceiling in most hours, and at 500 vehicles a rule that knows only the clock buys cheaper still, at 99.0% of rides.
- **A demand forecast for a place with no ride history, inside the planner.** Built and tested: a forecast borrowed from other cities is behind one trained on the place's own rides in every case, and its bounds don't carry across cities. Demand at a new site stays an input.
- **Scenario storage or accounts.** A site file is a text file, and version control already keeps, compares and shares text files.

## Risks

- The energy figure is my estimate. The fleet moves one for one with it. Meter it.
- Rides a vehicle a day: the plan holds up to 27.5. At 30 the vehicles run short at the busiest hours before the feeder does.
- Demand in a new area is a scenario, not a measurement.
- Grid headroom is a reading of the utility's public map, not a connection offer.
- Every capacity range is four fortnights of one spring in one city.

The planner doesn't make the call. It moves the argument from an arithmetic sheet to a set of inputs someone can name, measure, and be answerable for.
