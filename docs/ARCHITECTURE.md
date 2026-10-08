# Architecture

**This page is how the system is put together. Why it came to be this way, and what was tried and dropped, lives in [BUILD_LOG.md](BUILD_LOG.md). How each model was trained lives in [TRAINING.md](TRAINING.md).**

## What the system must answer

1. How many vehicles does this site return to service per hour, and how many are available at the demand peak?
2. Which resource runs out first as the fleet grows: grid power, chargers, cleaning bays, stalls or people?
3. Which control rule gets the most vehicles back on time under the same constraints?
4. Given a new site's power and space, how large a fleet can it serve?

Every module exists to answer one of those four. Anything that doesn't is out of scope.

## The module map

The simulator:

| Module | Responsibility |
|---|---|
| `resources.py` | The nouns: vehicle models with their energy use and charge curves, chargers, battery, depot, visits, scenario files |
| `sizing.py` | The planner's arithmetic, as pure functions. The reference the simulator is checked against. |
| `grid.py` | The site power limit and the battery. Power-sharing primitives. |
| `sim.py` | The depot: discrete events for arrivals, staff and bays; fixed steps for power. Enforces every physical limit. |
| `fleet.py` | The driverless fleet: demand, each vehicle's energy use on the road, the trips to and from the depot |
| `replay.py` | Demand replayed from real days, with the forecasts that were available at each moment |
| `data/contracts.py`, `data/registry.py` | What a series must satisfy, the series check, where its rows came from; the split registry |
| `data/donors.py`, `data/nyc.py` | Hourly rides from every city that publishes them, labelled by kind of place |
| `synth.py` | Demand generated for a place with no history, from pieces of donor series |
| `local.py`, `app.py` | The local operator's tool: a tested run of the full model, and the Streamlit page over it |
| `finance.py` | The account: a finished run as money, per site-day and per vehicle-day, under the tariff and two wholesale scenarios |
| `trust.py` | The figures behind the model page's trust views: the split, failure slices, two importances, the reserve frontier, the model card, written to `web/public/trust.json` |
| `data/footprint.py` | What the filings leave in the open: served tracts, chargers, sessions, with census populations; penetration and cadence by quarter |
| `cadence.py` | E22, the twin against the real visit cadence; E21, what the service area asks of the depot and when |
| `fares.py` | What a ride pays: the service's price structure (base, distance, time, busy pricing) levelled on the published average, with busy pricing read from the run |
| `data/caiso.py`, `data/caiso_prices.py` | California grid net demand and emissions; day-ahead and real-time prices at the PG&E load point |
| `models/reserve.py` | The reserve–coverage frontier, two ways of sizing a bound, and Chronos-2 as a point forecast (E18) |
| `models/lab.py` | The forecast built with one fix at a time, scored the same way, with paired-day intervals (E17) |
| `models/transfer.py` | The forecast trained across cities, with trust and bounds measured on cities it never saw |
| `workbench.py` | The forecast built fourteen ways, each scored and each handed to the plan, for the front end's model mode |
| `newsite.py` | Holding a city out to test all of the above, and building a real new site |

Rules, in two layers that can be mixed:

| Module | Responsibility |
|---|---|
| `control.py` | How power is shared among plugged-in vehicles: emptiest first, in order of plugging in, or least energy left first |
| `dispatch.py` | Which vehicles are called in: fixed threshold, clock-aware threshold, fill every charger, hourly plan |
| `heartbeat.py` | The day-ahead controller: energy slots, phased arrivals, an hourly plan against the forecast's upper bound, a ledger, a price-aware mode |
| `ledger.py` | The hourly promise of vehicles on the road, its margin and its record, apart from the controller that opens and closes hours |
| `steering.py` | Which hours are expensive, on a tariff or on a price curve |
| `interfaces.py` | The Protocols the fleet and the controller ask of what is plugged into them: demand source, telemetry sink, observer, energy estimate, prices |
| `guard.py` | Watches the forecast bound the controller relies on; falls back to a simple rule when it breaks; runs a new rule in shadow |

What the rules are fed:

| Module | Responsibility |
|---|---|
| `data/` | One loader per public source, each split into a network half and a pure parsing half |
| `features.py` | The one feature builder used for both training and control |
| `models/short_horizon.py` | Ride forecasts at 1, 6 and 24 hours, with calibrated bounds |
| `twin.py` | Each vehicle's energy use and each type's charge curve, identified from telemetry |
| `economics.py` | What a day earns and costs: fares, energy by tariff period, capacity, chargers, battery, staff, land |

Keeping it honest:

| Module | Responsibility |
|---|---|
| `evals/` | Executes the tests registered in `EVALS.md`, in five modules by subject (`common`, `foundations`, `control`, `forecast`, `money`); the package is the registry |
| `facts.py` | The figures the public documents quote, read from the result files; writes `docs/FACTS.json` and lists what each document must say |
| `provenance.py` | Stamps every result file with the code it ran on; `depot-twin stale` lists any whose code has changed |
| `scoreboard.py` | Generates the index of tests from the result files |
| `growth.py` | The fleet-size studies |
| `report.py` | The one-page HTML report |
| `cli.py` | The command line |

The first version is kept so earlier results can be rebuilt, and is not used by anything current:

| Module | What it was for |
|---|---|
| `models/demand.py` | The week-ahead forecast on another city's data (E1) |
| `first_version/policy.py`, `env.py`, `train.py` | A recall policy trained by reinforcement learning (E2). It tied a simple rule and is superseded by the controller. |
| `first_version/surrogate.py`, `planner.py` | A fast model of the simulator and a search over depot designs (E3 to E5), trained on the first-version simulator |
| `scenarios/*.toml` outside `v2/` | Scenarios with one energy figure for every vehicle |

## Design decisions

**Discrete events for things, fixed steps for power.** Arrivals, people and bays are events. Power is integrated in one-minute steps, because every charging vehicle draws on the same grid connection and the same buffer, so no vehicle's finish time can be computed in isolation. The cost is that finish times are accurate to two steps. The sizing test states that tolerance out loud.

**The control rule cannot break physics.** A rule proposes; the simulator clamps every grant to what the battery accepts, what the charger delivers and what the site has left. A learned or faulty rule can be bad, never impossible. It's what makes it safe to compare a trained policy with hand-written rules on equal terms.

**One interface for every rule.** First-come-first-served, need-first, the optimizer, the learned policy: all of them implement `queue_order`, `bank_order` and `allocate`. A comparison between them changes one argument.

**Hand arithmetic is the first test.** Before the simulator is trusted on cases nobody can check by hand, it has to reproduce the cases someone can: one wave, one charger each, a known power limit.

**Two levels of control, two interfaces.** Inside the depot, a policy orders the queue and splits the power. Above it, a recall rule decides which vehicles come in and how full they leave. The second level is where rides are won or lost, so that's where the optimizer and the learned policy compete.

**The learned policy sees ratios, never counts.** Share of the fleet on the road, share of chargers in use, demand over capacity. A policy trained on 250 vehicles can then run on 1,000, and a registered test checks whether it holds up.

**Tests are registered before they are run.** `EVALS.md` fixes the data, the split, the metric and the bar first. A miss stays on the page, with what it means.

**The surrogate shortlists; the simulator decides.** The surrogate is accurate on average and not near the service level, the edge that matters (E3 to E5). Nothing it proposes is believed until the simulator has run it.

**Prices are not model inputs.** The surrogate predicts physical outcomes; money is computed from them. A price can change without retraining anything.

**Compare one thing at a time.** A controller can beat a simpler rule on rides (E8) with the whole gain coming from the way of sharing power it ships with (E11). Every comparison crosses the parts, and every baseline is the simplest rule that could plausibly do the same job.

**A plan is asked what it is for.** The day-ahead plan doesn't buy rides. It buys cheaper energy without losing rides, and an hourly promise that's kept. It stays in the system for those two things, behind a guard.

**Scenarios are data.** A depot, its fleet and its control rule live in a TOML file. Changing a site is an edit, not a code change, and every run is reproducible from a file and a seed.

**Assumptions are labelled where they live.** A number from a public source carries the source. An assumed number says so in the scenario file, right next to the number.

## The invariants the tests enforce

- The grid draw never exceeds the usable share of the connection (95% of the published figure, 2,612 kW of 2,750 on one feeder; `DepotConfig.usable_share`).
- No vehicle is charged past its target, or faster than its battery or charger allows.
- Energy delivered equals energy needed, for every vehicle that finishes.
- A depot that cannot finish still returns a result.
- The same scenario and seed give the same result.

## The front end

`web/` is a static site: TypeScript, canvas, no framework, built with Vite. Who it's for is in `PRODUCT.md`; its visual system is in `DESIGN.md`.

| File | What it holds |
|---|---|
| `src/trace.ts` | The trace format and its checker, mirroring `src/depot_twin/trace.py` |
| `src/sim.ts` | The depot and fleet simulator for the browser: both power rules, a threshold and energy slots, staff, inspections, the rider's wait |
| `src/views/floor.ts` | The depot floor in plan view, every vehicle a named mark |
| `src/views/board.ts` | The vehicles at each station, and one vehicle's visit told step by step |
| `src/views/money.ts` | The money mode: the account for a chosen design, redone as the three unsourced figures move |
| `src/views/workbench.ts` | The model mode: seven dials, the model's charts, what the plan did |
| `src/grid.ts` | A real week of California grid net demand and carbon intensity |
| `src/views/charts.ts` | The heartbeat strip and the hourly charts |
| `src/main.ts` | The page: its five modes, controls, the clock, play and replay, and the alerts that say what a design cannot do and what the running depot is losing |
| `scripts/readme.mjs` | Renders the README and `docs/STORY.md` as pages beside the site at build time, and the story as the fragment the Story tab takes |
| `scripts/measure.mjs`, `tests/laws.test.ts` | The owner's front-end laws, measured in a browser and asserted in tests |
| `public/traces/` | Runs recorded from the Python simulator with `depot-twin trace` |
| `public/grid/`, `public/facts.json` | Grid data and tested forecast scores, written by `depot-twin data grid facts` |

Two things keep the two simulators honest. `tests/trace.test.ts` loads a trace recorded from Python and checks it against the contract, so neither side can change the format alone. `tests/sim.test.ts` runs the browser simulator on fixed cases with matched definitions and requires its rides served to match Python's (`tests/reference.json`, written by `scripts/reference.py`) within half a point at 500 vehicles and a point and a half at 1,000, and the two power rules to rank the same way.

The browser simulator has no day-ahead plan and no forecasts. Runs that need them are replayed from recordings.

## Guarding against regression

- **Pinned numbers.** Small seeded runs with their headline figures stored in `tests/golden.json`. A change that moves one has to regenerate the file on purpose.
- **Invariants.** A miniature of each headline finding runs on every change (`tests/test_invariants.py`).
- **Documents agree with results.** The scoreboard is generated, and a test fails if the committed copy differs or if any registered test lacks a result. A result file whose code has changed shows as stale.
- **CI.** Lint; tests on three Python versions; a smoke job that runs a visitor's commands from a clean checkout; type-check, tests and build of the front end. A release is built from a tag only after the same checks pass.

## The quality bar

- `ruff check` and `ruff format --check` pass, with limits on function complexity and length.
- Every public function has a docstring that says what it returns. Comments explain why, not what.
- CI runs the linter and the tests on three Python versions.
- Results that appear in documents are rebuilt by a script, and CI fails if they drift.
