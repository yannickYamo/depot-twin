# Product

## Platform

web

## Users

People who plan or run robotaxi depots and charging: fleet operations, site planning and energy teams. They arrive with a question about a site ("how many vehicles can this carry, and what gives first?") and want to see the answer move when they change the fleet, the grid connection, the chargers, the staff or the rules. Engineers who clone the repository are a second audience.

## Product Purpose

depot-twin simulates one depot and the driverless fleet that works out of it: rides, calling vehicles in, queueing, charging under a site power limit, cleaning, returning to service. The front end lets a visitor watch a depot run and change it, or replay a run recorded from the full model. Success is a visitor who can say what limits the site and which rule to change first.

## Positioning

Every figure on the page comes from a simulator whose claims are registered tests with published misses. The browser model is held to the Python model by a parity test on matched definitions: within half a point of rides at 500 vehicles and a point and a half at 1,000.

## Operating Context

Read at a desk in working hours, beside spreadsheets and site plans. The vocabulary is the depot's: feeder, site limit, chargers, people, cleaning bays, rides served, rides lost, peak price.

## Capabilities and Constraints

- Play: a simulator in the browser with live settings (fleet, grid power, chargers, charger class from Level 2 to 350 kW, people, power rule, how vehicles are called in, rides per vehicle). It models inspections (every tenth of a vehicle's own visits) and the rider's wait (up to ten minutes for a free vehicle).
- Replay: a run recorded from the full Python model on real San Francisco days, with the day-ahead plan, its hourly promise and the trained forecast.
- In replay, the plan is shown hour by hour with the plans before it, and set against a fixed threshold on the same days.
- Every vehicle off the road is named and can be followed through its visit: a drawn robotaxi acts out what it is doing (driving, queued, plugged in, charging, cleaned) with one line in the depot's words and its visit log; the list by station is there when the visitor opens it.
- The forecast is scored on screen against the rides that came.
- A real week of California grid data shows how strained the grid was when the depot drew its power.
- Money mode: the account for a recorded design on a frozen fortnight, under the tariff and two wholesale scenarios, with the three unsourced figures as sliders.
- Forecast mode: one question (can better demand prediction cut the vehicles held in reserve), four figures, a trust line, the dials, accuracy against reserve for one city at a time, what it changes at the depot; the evidence (split, horizons, curve, calibration, failure slices, what it learned, model card) in folds. For the forecast built fourteen ways one change at a time. All recorded; nothing trains in the browser.
- Where the rides come from: three service areas around the parcel from the filings' served tracts and census populations, each with residents, rides a day at the filings' penetration, the vehicles that is, and the month a second feeder is due at the measured growth and at half of it; one button sizes the fleet to the area.
- The browser depot runs at the filings' visit cadence (called in at 55%, cleaned every fourth visit, a five-minute leg, about three visits a day); E22 sets the call-in and the cleaning and finds the leg moves little. Visits a vehicle-day is a readout.
- Dials run free; alerts computed from the design say what the site cannot do (a fleet the connection cannot sustain, plugs the grid cannot feed, chargers too few or too many for the fleet, too few people) and what the running depot lost in the last day and which resource bound it. The power dial alone is bounded by the parcel's feeders.
- Story: one page in the owner's voice on the problem, the choices and what it found, rendered from `docs/STORY.md` at build time.
- Static site, no server. TypeScript, canvas, Vite.
- The browser model has no day-ahead plan and no forecasts; the page says so.
- Not a live operations tool. It shows a simulation.

## Brand Commitments

- Name: depot-twin.
- The look follows the visual style of the service's public site: mint green, blue, deep navy, slate greys, a geometric sans, pill controls and an airy white layout.
- No Waymo logo, wordmark or asset anywhere.
- The line "An independent project built on public data. Not affiliated with or endorsed by Waymo." stays visible on the page.

## Evidence on Hand

`EVALS.md` (twenty-three registered tests, 54 of 95 bars), `docs/SCOREBOARD.md`, `web/public/traces/sample.json` (a recorded run), `web/tests/reference.json` (parity figures, written by `web/scripts/reference.py`). No testimonials, customers or deployments exist and none may be implied.

## Product Principles

1. The running depot is the page. Explanation follows what the visitor sees.
2. Every number shown is one the model produced on screen or in a recorded test.
3. Say what the model leaves out where it matters.
4. Settings use the depot's own words and units.

## Accessibility & Inclusion

Keyboard operable controls with visible focus, text contrast of at least 4.5:1, reduced motion respected (no automatic play, no moving lanes), usable at phone width.
