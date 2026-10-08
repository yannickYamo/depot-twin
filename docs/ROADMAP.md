# Roadmap

**TL;DR: The depot twin is a calibrated simulator of a real autonomous fleet depot on a real parcel, and the modeling chapters are closed. A front end lets you watch the thing run instead of reading about it. The forecast work landed somewhere I didn't expect: at this depot, a forecast's value is the reserve of vehicles its bound asks for, not the rides it predicts.**

If you're cloning the repository and want the turns rather than the narrative, go to [DECISIONS.md](DECISIONS.md). The reasons behind every step are in [BUILD_LOG.md](BUILD_LOG.md). Results are in [SCOREBOARD.md](SCOREBOARD.md). The forecast plan is in [FORECAST_PLAN.md](FORECAST_PLAN.md), and the published work we read first is in [RELATED_WORK.md](RELATED_WORK.md). This post is the map over the top of those.

## What's done

The core is a depot and fleet simulator calibrated to public fleet totals, sitting on a real parcel's published grid headroom. The physics are held to the place rather than to a round number: 95% of a connection usable, charger losses, battery acceptance, and a hard cap each step. Per-vehicle energy use is identified from telemetry, not assumed.

On top of that: ride forecasts at 1, 6 and 24 hours with measured bounds on San Francisco data, with a fourth model for the hour under way kept as an option. Demand replayed from real held-out days in three cities. Four ways of calling vehicles in and four ways of sharing power, compared cell by cell.

The controller is a day-ahead hourly linear program where only the first hour is acted on. It makes an hourly promise and keeps it, carries a guard for when its forecast breaks, and can be steered by the tariff or by an hourly price. Every design carries an account: tariff and wholesale scenarios, vehicles, people, land, lost rides, and rider payment simulated the way the service actually prices.

There's a forecast and generated demand for a site with no ride history, tested by holding cities out (`depot-twin new-site`).

Underneath all of it: twenty-three registered tests, 54 of 95 bars, two growth studies, and studies of session length, staffing, sensitivity and the first hour. Every result file stamped with the code it ran on, with `depot-twin stale` listing any whose code has changed. Pinned regression numbers, invariant tests, a generated scoreboard, CI, a release workflow, and the owner's front-end laws measured in a real browser on every change.

## The chapters, as they closed

**A forecast for a place with no history (E13, 1 of 4; E15, 2 of 2).** Beats last week's curve in seven of nine cells. Bounds come out too narrow with a single donor city. Capacity is read from the worst of ten generated scenarios.

**Stand on what is known (E14, 4 of 4, plus the sensitivity study).** The power rule repeated on Chicago days with its mechanism intact. Least-energy-left-first ties in-order. Capacity stated in rides, with how far each input moves it.

**Phase 0 of the forecast plan.** Data contracts in code, a check of every series, a split registry of windows, generated rows barred from stopping a run, and calibration and scoring ([DATA.md](DATA.md)).

**The forecast chapter (E16 3 of 4, E17 0 of 4, E18 2 of 3).** Closed as registered. Trees stay the default. The honest finding is that model fixes which helped on San Francisco did not carry to both other cities, while a pretrained model (Chronos-2) has 7.7% error against 9.6% for the trees on the confirmation series and holds 35.7 vehicles in reserve against 40.7.

**What binds where, and the money (E19, 0 of 4; E20, 2 of 3).** The sweet spot is a service decision, not an engineering one. Among designs serving 99%, the best in the sweep is 1,200 vehicles on two feeders at $219,700 a day, the top of the range swept; on one feeder it is 700 vehicles under the threshold at $126,200. The grid saturates before service breaks. The plan pays its way below saturation. An hourly price in April was too flat to steer by.

**The filings' cadence and the demand around the parcel (E22, 4 of 4; E21, 1 of 3).** One feeder carries about 600 vehicles at the 99% floor at the visit cadence the filings count, 700 under long sessions. East Bay demand is 241 vehicles today and outgrows one feeder in 19 months at the measured growth, 36 at half of it.

The thing that moved across these chapters is where the uncertainty is priced. It stopped being a forecasting score and became a vehicle reserve.

## What's next

1. A browser test of the page beyond the laws: a visitor's path through the five modes
2. Later: a donor city less dense than the three in hand (Washington DC is public; Los Angeles and Phoenix are not); generated weeks as hard as real ones so the average scenario can be trusted and not only the worst; the level of demand at a new site from population and jobs; a registered test of the pretrained forecast inside the plan

## The front end: what it's for

Reading that in-order feeding serves several points more rides is one thing. Watching the same depot on the same day back up under one rule and flow under the other is another.

A visitor watches the depot run, then changes the site, the fleet or the rules to see what breaks first. The page says plainly what the site cannot do.

### What a visitor does

1. Watch: the depot floor, every charger with its vehicle and charge filling, the queue, the staff area, the cleaning bays, the count on the road; above it the heartbeat: arrivals every five minutes as a pulse beside the grid draw against the usable limit
2. Read the day: rides offered against served with the forecast's band; vehicles on the road against the hour's promise; grid draw with the expensive hours shaded; the real California grid week under it
3. Compare: the same depot run alongside under the other power rule, on the same demand; in replay, the plan against a threshold on the same days
4. Change it: fleet, grid connection, chargers and their power, people, the recall rule, the power rule, rides per vehicle. scrub the week or let it play at 1x to 60x
5. Follow one vehicle from the road through the depot and back; open the list by station when wanted
6. Test the forecast model on seven dials and see what each change does to error, bound coverage, reserve, and the plan
7. Read the money for a recorded design, with the three unsourced figures on sliders

Dials run free. Alerts say what the site cannot do and what the running depot is losing.

### How it's built

| Mode | What runs | Where | Use |
|---|---|---|---|
| Play | A small simulator in the browser: the depot's core rules, inspections and the rider's wait, rewritten in TypeScript | The static site | Changing the design and the rules, with no server |
| Replay | Nothing. The page plays traces recorded from the Python model | The static site | The runs behind the published results, exactly as tested |
| Model workbench | Nothing. Recorded scores and runs of sixteen variants: fourteen forecasts, one of them pretrained, and two broken feeds | The static site | What model quality does to planning and to money |
| The money | Nothing. The account of every E19 design, redone in the browser as sliders move | The static site | Where the sweet spot is and what moves it |
| Story | Nothing. One page rendered from `docs/STORY.md` at build time | The static site | The problem, the choices and what it found |
| Local tool | The Python model, behind a few widgets | `depot-twin app`, on your machine | The full model on a design of your own |

**The browser simulator is a second implementation, and two models drift.** So it's held to the first by a parity test on matched definitions (`web/tests/sim.test.ts`, with figures from `web/scripts/reference.py`): within half a point of rides at 500 vehicles and a point and a half at 1,000, and the same ordering of the power rules. If the ordering flips, the test fails and the page doesn't ship.

The trace is one file per run, versioned, with every five-minute step recording vehicles by place and each one named with its charge; each charger's vehicle, charge and power; grid draw, usable limit, battery; rides offered, served, lost; the forecast and its bound; the hour's promise and what was delivered; and the plan as redrawn each hour. `depot-twin trace` writes a trace from any run and refuses one that breaks the contract, with a checker on both sides for columns, lengths, vehicles conserved every step, and nothing over what the site has.

TypeScript, no framework, Vite, canvas. One axis per chart, labeled directly. The look follows the visual style of the service's public site, with no logo, wordmark or asset of theirs. The owner's laws - 24 px targets, 4.5:1 contrast, no overflow - asserted in tests and measured in a browser. CI runs the type-check, the contract and parity tests, the laws, and the build.

### Stages

| Stage | Delivers | State |
|---|---|---|
| F1 | Trace format, recorder, contract checks, `depot-twin trace` | Done |
| F2 | Viewer: depot floor, heartbeat strip and timeline, replaying recorded runs | Done |
| F3 | Compare: the other power rule run alongside | Done |
| F4 | Play mode: the browser simulator and its controls, held to the Python simulator by test | Done |
| F5 | The full model on a design of your own | Done as a local tool (`depot-twin app`) |
| F6 | Hosting and releases | Done: a Pages workflow and release artifacts |
| F7 | Every number on screen links to the test it comes from | Not built |

### What it won't do

It won't pretend to be a live operations tool; it shows a simulation. It won't show individual riders or routes, because the road is modeled in aggregate. And it won't run the long evaluations in the browser - those stay in the test suite, where they can be registered and reproduced.

## Open questions, kept open

Three things stay unresolved, and I'd rather name them than quietly resolve them in a default.

Whether a second service connection to one parcel is what the map implies, or whether that's a second parcel. What a lost ride is worth beyond its fare, since the account's answer to the plan's worth turns entirely on that number. And whether the service would let itself be priced the way the account assumes once the site is saturated.

Those three sit under the money chapter, which means E19's conclusions are only as firm as the assumptions above them. The simulator doesn't settle them. Somebody on the fleet operations side does.
