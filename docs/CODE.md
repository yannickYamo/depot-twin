# Code map

[Back to the README](../README.md)

*Where everything is, how a result gets its stamp and how to add a test. For someone reading or changing the code. The one thing to take: a result is true of the code that ran, and the stamps hold it to that.*

Python package `src/depot_twin/`, command `depot-twin` (`cli.py`).

## The simulator

These files are hashed together as the `sim` stamp.

- `resources.py`: the depot, chargers and vehicle types. `interfaces.py`: the protocols between simulator and controller.
- `sim.py`: one depot on its own. `fleet.py`: a driverless fleet working out of it (`FleetSim`, `ThresholdRecall`).
- `grid.py`: power at the site. `control.py`: power rules (`slot_power`, `need_first`). `dispatch.py`: calling rules and the low-battery floor.
- `heartbeat.py`: the hourly plan. `ledger.py`: its promise. `guard.py`: its fallback. `steering.py`: which hours are expensive.
- `replay.py`: real days replayed with the forecasts of the time. `trace.py`: a run recorded step by step for the page.
- `economics.py`, `finance.py`, `fares.py`: the account. `growth.py`, `sizing.py`: scaling rules and hand arithmetic. `twin.py`: energy use estimated from telemetry.

## Forecasts

These are the `forecast` stamp.

- `features.py`: one feature builder for training and running. `models/`: the forecasts (`short_horizon`, `transfer`, `backtest`, `reserve`, `lab`, `demand`).
- `newsite.py`, `synth.py`: a site with no ride history. `workbench.py`, `trust.py`, `baseline.py`, `blocks.py`, `backtest_page.py`: forecast studies and the page's forecast files.

## Data

`data/` has one loader per public source (`sftaxi`, `chicago`, `nyc`, `cpuc`, `footprint`, `pge`, `caiso`, `caiso_prices`, `weather`, `donors`). `contracts.py` and `registry.py` say which days serve which purpose (`data/splits.json`). `build.py` holds the builders behind `depot-twin data <name>`.

## Tests with pass bars

`evals/__init__.py` is the registry `depot-twin eval <name>` reads.

- `foundations`: E1 to E6. `forecast`: the forecast tests from E7 to E18. `control`: E8 to E14. `money`: E19 and E20.
- `wide`: E25 and side studies. `margin`: E26. `parked`: E27. `further`: E28. `steer`: E29. `common`: shared settings and the record writer.
- `cadence.py` holds E21, E22 and E23, the capacity test (`capacity_run`, `carried`).
- `first_version/` holds the stand-in model, the design search and the learned policy behind E2 to E5.

## The planner

`siteplan.py`: `load` checks a site file, `plan` runs the arithmetic, the search and the changes, `brief` writes the page, and `write` is `depot-twin plan`. Site files are in `sites/`, committed plans in `sites/plans/`.

## Results and documents

- `provenance.py`: the stamps. `GROUPS` is the code hashed, `RECORDS` each result file's groups and modules, `UPSTREAM` the records a record reads, and `PAGE` the page files, plans and `docs/FACTS.json`.
- `analysis.py`: the carried and planned fleet and the account study, read from records. `facts.py`: the claim ledger and the document check. `scoreboard.py`, `figures.py`, `report.py`: generated documents. `reproduce.py`: six published runs again.
- `app.py`, `local.py`: the local tool for trying settings.

## How a result gets its stamp

A test ends in `evals.common._write(name, payload)`, which adds `provenance.stamp(name)`: a hash of each code group in `RECORDS[name]`, of the modules that ran it, and of the records in `UPSTREAM[name]`. Comments and docstrings are left out of the hash. `depot-twin stale` lists every file whose stamp differs from the tree, and `tests/test_records.py` fails unless each is named in `data/derived/stale.json`.

## Adding a registered test

Write its bars in `EVALS.md` first. Add the function under `evals/`, its name to `EVALS` in `evals/__init__.py`, its file to `provenance.RECORDS` (and `UPSTREAM` if it reads a record) and to `scoreboard.TESTS`. Run `depot-twin eval <name>`, then `depot-twin scoreboard` and `depot-twin facts`.

## Adding a unit test

Put it in `tests/test_<module>.py` and run `make check`. `tests/test_invariants.py` holds a miniature of each headline finding. `tests/regression_cases.py` and `golden.json` pin seeded runs; run `make golden` only after a change meant to move them. `tests/test_facts.py` and `tests/test_records.py` hold the documents to the records.

## The page

`web/src/main.ts` is the page: a short version, and a full twin of three tabs. `src/sim.ts` is the browser simulator, held to Python by `tests/sim.test.ts`. `src/trace.ts` is the step format both simulators fill. `src/views/` has one file per view: `brief` is the short version, `impact` the Decisions tab, `workbench` and `models` Forecasts, `money` The account, and `floor`, `charts`, `board`, `vehicle`, `plan` and `canvas` the depot. `scripts/readme.mjs` renders the README and the story into the site. `scripts/measure.mjs` measures the design laws on the built site. `make web` type-checks, tests and builds.
