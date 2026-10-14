# Planning your own site

[Back to the README](../README.md)

*How to plan your own site: the site file, what each input moves and when not to trust the answer. For someone with a parcel and a grid figure. The one thing to take: the answer is as good as your energy figure.*


The study in this repository is about one East Oakland parcel. `depot-twin plan` asks the same questions of any site you describe in a file: how many vehicles one grid connection carries, which fleet to plan for when the energy estimate may be wrong, and what each change is worth.

```bash
depot-twin plan sites/east_oakland.toml --out out/plan/east_oakland
```

It writes `plan.json`, with every figure and a summary of each fleet in each window, and `brief.html`, one page for the meeting where the lease is decided. On five cores the East Oakland file takes about an hour for its three cases and four changes, and a file with one case five to twenty minutes. It prints each case and the fleets it's running as it goes. `plan.json` also keeps a hash of the site file and of each demand file, and `depot-twin stale` names a plan in `sites/plans/` whose site file or demand has changed since.

## What it gives for the sites in this repository

| Site file | Arithmetic | Carried | With 10% more energy | With the parked load | Plan |
|---|---|---|---|---|---|
| `sites/east_oakland.toml` | 658 | 675 | 600 | 625 | 600 |

That's the study's answer, reached from the file: one of its runs is the study's own run to the last digit kept, and a test holds the depot it builds to the one the study built. With the plain calling rule no fleet from 575 up is carried (the study, with ten draws on steps of 50, gives 550). With emptiest-first feeding the carried fleet is 575. A quarter more chargers carries 675, and so does a quarter more people and bays: neither adds a vehicle.

The three `sites/shape_*.toml` files give the same depot other demand, with one case each: the study's weeks counted by the hour, and four fortnights of Chicago and of New York ride-hail, one from each season. All three carry 675. The plans are kept in `sites/plans/`.

## What it does

1. **Arithmetic.** One short run on a fleet with power to spare measures what a vehicle takes from the feeder in a day. The connection's daily energy divided by that's where the fleet has to end up.
2. **The search.** Fleets around that figure, two at a time, upward while they are carried and downward when the first isn't, on every demand window in the file with two draws a window, under each way the energy estimate could be wrong: as entered, with more energy on the road (10% unless you say otherwise), and with a parked vehicle's systems left on when you don't know whether they are. Each window is replayed until the fleet settles, on low-battery visits, charge on the road and rides served, and its last week is scored.
3. **The fleet carried and the fleet to plan for.** A fleet is carried when, in every window, nine runs in ten serve the service floor and no more than half its depot visits start on a low battery. A run that's still moving after its last replay decides nothing: its window isn't counted as carried, and the brief warns that the carried fleet may be a step low. The fleet to plan for is the largest that is carried under each case taken alone.
4. **One change at a time.** A quarter more chargers, a quarter more people and bays, the plain calling rule, and emptiest-first feeding, each tried at a few fleets around the carried one. When a fleet met both bars with a run that had not settled, the change says so.

## The site file

A site file is TOML. Only four things are required: a name, the connection's kW, at least one vehicle type and at least one demand window. Everything else has a default, the one the East Oakland study uses. A table or a field the planner doesn't know is an error, with its name, so a typo can't silently plan the wrong site. So is a value outside its usual range, which is nearly always a slip of units: `drive_kwh_per_mile = 30` is refused, with the field, the range and the unit it is in. The ranges are 0.15 to 0.8 kWh a mile, 0 to 6 kW always on, 20 to 250 kWh of battery, 7 to 500 kW of fast-charge acceptance, 50 to 50,000 kW of grid, 3 to 500 kW a charger, 1 to 60 rides a vehicle a day and 5 to 90 minutes a ride. If the value is meant, `--allow-unusual` keeps it and the brief says so. A file that isn't TOML, a missing table or required field, or a value of the wrong kind (`kw = "2750"`) is reported first; every other problem in a file is reported together, before anything runs.

The last column says how far the input moves the answer on the East Oakland parcel, from the tests in [EVALS.md](../EVALS.md). Inputs are ordered by that.

| Table and field | Meaning | Default | How far it moves the fleet carried |
|---|---|---|---|
| `[grid] kw` | Power one service can deliver at the parcel | required | In proportion |
| `[grid] services` | How many such services | 1 | In proportion |
| `[grid] usable_share` | The share of that the site's load manager lets the chargers draw | 0.95 | In proportion |
| `[vehicles.<name>] drive_kwh_per_mile`, `always_on_kw` | Energy to drive a mile, and the load of computers, sensors and climate control | required | One for one with the total: 750, 675 and 625 vehicles at 10% less, the estimate and 10% more (E26) |
| `[fleet] parked_load` | Whether that always-on load keeps running in the depot: `"off"`, `"on"` or `"unknown"` | `"unknown"` | 675 to 625 (E27). With `"unknown"` the plan must hold both ways |
| `[rules] calling` | `"threshold_waits"` calls a vehicle in only when a charger is free; `"threshold"` calls it at a set charge | `"threshold_waits"` | 650 against 550 on equal steps (E26) |
| `[fleet] ride_minutes` | A ride, pickup leg included | 23 | At 28 no fleet from 500 to 900 was carried: vehicles run short before the grid does (E23) |
| `[fleet] max_wait_minutes` | How long a rider waits before giving up | 10 | At 5 no fleet from 500 to 900 was carried (E23) |
| `[fleet] rides_per_vehicle_day` | Rides offered, a vehicle in the fleet | 25 | 700 at 18 or 21.5 against 600 at 25, on steps of a hundred (E23). 650 at 27.5, and no fleet from 525 to 600 at 30, where vehicles run short before the feeder does (E28) |
| `[demand] windows` | Fourteen-day windows of ride counts | required | See "Demand" below |
| `[rules] power` | `"slot_power"` feeds in order of plugging in; `"need_first"` feeds the emptiest first | `"slot_power"` | Nothing with power to spare; 8.8 points of rides at a fleet far past the feeder (E23) |
| `[rules] call_below`, `charge_to` | The charge a vehicle is called in at, and charged to | 0.55, 0.85 | Sets the visit pattern; 0.55 matches three visits a day in the public filings (E22). 0.50 matches too and carries the same fleet (E28) |
| `[depot] chargers_per_vehicle`, `charger_kw` | Chargers for each vehicle in the fleet, and their power | 0.132, 60 | Little, once the feeder is what binds |
| `[depot] people_per_vehicle` | People, and cleaning bays, for each vehicle | 0.025 | Little under the filed visit pattern |
| `[depot] clean_every`, `clean_minutes`, `plug_minutes`, `inspect_every`, `inspect_minutes`, `charger_efficiency` | Depot operations | 4, 8, 2, 10, 20, 0.93 | Not moved one at a time; `charger_efficiency` in proportion |
| `[fleet] depot_leg_minutes`, `depot_leg_miles` | The drive between the riders and the depot, each way | 8, 2.0 | Little at 500 vehicles with power to spare (E22); not moved at the edge |
| `[vehicles.<name>] capacity_kwh`, `max_dc_kw`, `max_ac_kw`, `dc_curve`, `share` | Battery, charge acceptance, and the type's share of the fleet | required | Not moved |
| `[policy] service_floor` | The share of rides that must be served | 0.99 | A policy, not a finding |
| `[policy] low_battery_visits_at_most` | The most depot visits that may start at 12% charge or under | 0.5 | Decides the edge fleets: move it and see whether the answer moves |
| `[policy] energy_margin` | How much more energy on the road the plan must survive | 1.1 | The plan falls about 4% for every 5%; 575 at 20% more and 525 at 30% more on the East Oakland parcel (E28) |
| `[sweep] step`, `draws`, `start`, `changes` | Fleet step, draws a window, where the search starts as a share of the arithmetic, and whether to try the changes | 25, 2, 0.9, true | Resolution and run time only |
| `[sources]` | For each of `grid`, `energy`, `parked_load`, `rides`, `ride`, `demand`, `policy`: where the figure comes from | `"assumed"` | Printed in the brief; an assumed energy figure puts a warning on it |

## Demand

A demand window is fourteen days of ride counts. Only its shape is used: the level is `rides_per_vehicle_day` times the fleet, so every window offers the same rides a day. Give a window as:

- **A file of counts**, a CSV with `time` and `rides` columns, at five minutes or at one hour, fourteen days long, starting on a Monday at 00:00. An hour's rides are spread evenly over its twelve steps. The times must run evenly through the fortnight: a gap, a repeated row, rows out of order or a clock change is refused when the site file is read, with the line it is on, and so is a file that can't be read as a CSV, because counts are replayed by position and everything after the fault would land at the wrong hour. Write times in standard time or UTC, so that no hour is missing or doubled. This is the one to use: your own trips, from the place and the season you are planning for.
- **A start date** among the four San Francisco fortnights committed with the study (`2024-03-18`, `2024-04-15`, `2024-04-29`, `2024-05-13`). Any other date, or a file that isn't there, is refused when the site file is read.

The windows are the sample. Two draws of one window differ by a tenth of a point of rides served, and two windows by two points, so four windows are four data points however many draws you run. Use at least four, from different seasons, and include the busiest fortnight you have.

## Reading the answer

- **Arithmetic against carried.** When the carried fleet is 95% or more of the arithmetic, the feeder's energy is what binds and the answer is as good as your energy figure. When it's well below, something else binds first, and the brief says what: chargers, or vehicles at the peak.
- **Carried against planned.** Carried is what the site does if your figures are right. Planned is what survives one of them being wrong. Sign for the planned fleet.
- **"Or more" on a change** means the largest fleet tried with that change, two steps past the carried one, was still carried. Write the change into a site file of its own to find its edge.
- **A warning that the carried fleet is at the edge of the fleets run** means the search ran out of room before a fleet failed. Raise `start` and plan again.

## When not to trust it

- The simulator hasn't been checked against a real depot. Run it beside one before relying on it for another.
- Energy use is nearly always assumed. The fleet moves one for one with it, so meter one vehicle's whole day, on the road and parked.
- Demand from another city is a shape, not your demand. A city with a sharper evening peak carries fewer vehicles than the same energy would suggest.
- Every window is scaled to the same level. A week busier than `rides_per_vehicle_day` isn't in the sample unless you raise it.
- No battery aging, no vehicle downtime, no winter heating or summer cooling load beyond what your energy figures include.

## What it does not do

It plans one connection at one site. It doesn't rank sites, price the plan, date a second connection or keep your scenarios: a site file is a text file, and the place to keep, compare and share text files is the version control you already have. The account and the timing of a second feeder are in the East Oakland study ([METHOD.md](METHOD.md), section 6), on that parcel's costs and that area's growth.
