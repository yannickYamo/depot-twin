# Design

The visual system of the depot-twin front end (`web/`), recorded from what is built. Product facts are in `PRODUCT.md`.

## The idea

An airy white page around one dark stage. The stage is the depot seen at night from above, and energy is the only thing on it that glows. The look follows the visual style of the service's public site: a light page, one dark stage, mint and blue, a geometric sans, pill controls. It uses no logo or wordmark and no asset of theirs, and the page states that the project is independent.

## The tokens

| Token | This page |
|---|---|
| Palette | `#00e89d`, `#006fee`, `#050f1e`, `#23233c`, `#5d6e83`, `#7c899a`, `#a2abb9`, `#ccd3dc`, `#e5e9f0`, `#f4f6f9`, `#ea0000`, `#00929d`, `#132237`, each given one job (below). The marker teal `#00929d` fails contrast as text on white (3.75:1), so text in teal uses `#007068` |
| Typeface | Outfit at 400 and 500 |
| Sizes | Body 1 rem, labels 0.85 to 0.95, section heads 1.5, figures 2, title 2.5 to 3.125 |
| Tracking and line height | −0.02em in text, −0.04 to −0.05em in display; line height 1.1 display, 1.2 subheads, 1.5 text, as `--track-text`, `--track-display` |
| Radii | 3 px stalls, 4 px small, 8 px selects, 16 px panels, 20 px stage, pills |
| Spacing | `--space` 8 px, `--space-group` 40 px |
| Shadows | One shadow, on the hover tag; the stage is a surface, not a card |
| Transitions | 0.2 to 0.25s ease-out on controls |

## Color

Each color has one job, on the stage and on the page alike.

| Token | Value | Job |
|---|---|---|
| Mint | `#00E89D` | Energy: a charger filling, power from the grid, the play control |
| Blue | `#006FEE` (stage `#3D95FF`) | Vehicles on the road |
| Red | `#EA0000` (stage `#FF5C5C`) | The site limit and rides lost |
| Ink | `#050F1E` | The stage, text, primary controls on the page |
| Slate | `#5D6E83` | Secondary text |
| Mist, Line, Wash | `#CCD3DC`, `#E5E9F0`, `#F4F6F9` | Tracks, hairlines, the mode switch |
| Stage text, stage line | `#A2ABB9`, `#2A3A52` | Labels and outlines on the stage |

Mint is never text on white: its contrast is too low. On the page, the served-rides line uses the darker `#00929D`.

## Type

Outfit, weights 400 and 500. Title 2.5 to 4.5rem at weight 400 with tight tracking. Figures 2.1rem with tabular numerals. Body 1rem, secondary 0.85 to 0.95rem. No capitals for labels, no label above a heading.

## Shape and layout

- Stage: 20px corners, 16px on phones. Yard outline 16px. Charger stalls 3px.
- Actions, the mode switch and the speed dial are pills; the dial lights one choice in white. Selects have 12px corners.
- No cards. Figures and settings sit on the page, divided by hairlines; a full-ink rule opens each group.
- Two columns from 1020px: stage and charts on the left, figures and settings in a sticky rail on the right. One column below that.

## The stage

- Road vehicles are blue dots, one per vehicle. Depot vehicles are pale.
- A stall fills with mint as its vehicle charges. A plugged-in vehicle that is getting no power shows the same fill dimmed.
- Under the floor, the heartbeat: arrivals every five minutes as bars, then grid power as a mint area against a dashed red limit, with peak-price hours shaded.

## Vehicles

Every vehicle off the road is a named mark (V-0001 upward). Hovering shows its name, station, charge and power in a small white tag. Clicking follows it: a white ring and name tag on the floor, a dark chip in the station list, and its visit told as a timed list. A followed vehicle on the road takes a dot of its own among the blue. The station list under the stage is folded by default (a `details` element); the floor itself carries dots, not names.

## The followed vehicle, drawn

Following a vehicle shows the vehicle: an authored SVG electric crossover in side profile (low body, roof sensor dome with a puck, corner pods, slim lamps; no logo or wordmark), shaded so it reads as a body under light: paint as a vertical gradient lightest along the shoulder and darker under the belt line, a white shoulder highlight, glass as a dark gradient with a diagonal glare, pillars in body colour over the glass, wheels with a radial tyre and a lit rim, a blurred floor shadow. It sits on a piece of the night stage (a radial navy) inside the white page, 360 px wide at desktop. Each place is a scene: on the road the paint turns blue with motion lines and a rolling lane; driving in and out the wheels and lane dashes roll (reversed on the way out); in the queue the hazards blink; parked for staff a loose cable sways from the charger post; charging, the cable reaches the port and the post's lamp and screen go mint; full, the lamp holds; in the bay a wash arch sweeps spray across. Nothing fills inside the car: the battery bar under it carries the charge in mint, with a soft glow that breathes while charging. One line in the depot's words sits under the drawing, then the visit log. All motion is CSS and stops under reduced motion; the scene still reads standing still.

## Charger classes

The charger power control is four real classes rather than a slider: Level 2 at 19 kW (AC; the vehicle's own charger takes 11 kW), fast at 60 kW (the reference depot's charger), fast at 150 kW, high power at 350 kW (more than either vehicle accepts). Pills in the controls' radio style; the chosen one is ink.

## Where the rides come from

Under the dials in depot mode, a panel headed like the dials' groups: three area chips in the pill style, four readouts (residents, rides a day, vehicles, second feeder due) in the two-column readout grid, one ink button that sizes the fleet, one quiet line on the source and its limit.

## Alerts

The side panel carries alerts between the readouts and the dials, in play mode only: dark ink on a pale tint with no rule (a coloured left border is a default the floor refuses), each opening with a short lead in its own colour ("Worth knowing." in amber, "Over the line." in red); amber for a warning (plugs the grid cannot use, chargers too few or too many for the fleet, too few people, power left on the table) and red for a stop (a fleet the site cannot sustain, more than 5% of the last day's rides lost). Each says the figure and the reason in one or two sentences, and names the resource that binds. The dials are never stopped; the page tells.

## Under the stage

Station list with chips, then four charts: rides, vehicles on the road, forecast against outcome (ink line, blue line, grey band up to the bound), and grid net demand (grey area, pale red band for the hardest quarter of the week, a teal ribbon for the depot's own draw). Each chart has a line of plain text under it that states its figures.

## The plan in replay

Four figures, then two charts: planned visits as blue bars over grey ghost plans with dark marks for what came; expected vehicles on the road as a dashed ink line, the hour's promise as a short red line, the fleet's actual path in blue. A small table sets the plan against a fixed threshold on the same days.

## Model mode

Dials in a sticky left column, as groups of pills; the chosen option is ink. To the right, in order: one sentence on what changed, four figures, four charts (validation in blue, training dashed grey, the naive rule in pale grey), a ranked list of features, then six figures for the plan. Differences from the reference are stated in words under each figure.

## Forecast mode: the folds

The page answers three questions in view and keeps the evidence in `details` folds with a chevron, each heading carrying its own scent ("Where it fails: late evening (21 to 24), behind last week"). A toast at the foot of the window, ink on the page's colour, says "Reset to the reference: one change at a time" for three seconds when a second dial is moved.

## The selected model

A strip in the page's wash under the headline names the selection and its two deltas; the four headline readouts carry a delta against last week and, off the reference, against the reference. Every fold below follows the selection; the reference is named where it appears.

## The trust views

A split time line (four tinted blocks in proportion to their days, train in the page's wash, the bound block in a mint tint, the test block in a blue tint); compact tables in the account style with right-aligned tabular figures and a green or red delta column; a requested-against-achieved coverage chart with the diagonal as the ideal and the vehicles held written beside each point; a two-column model card closed by one line on what the model is not.

## Money mode

The workbench's layout: dials and three sliders on the left; on the right the account as six figures and an eleven-line table with a ruled total, then two charts: contribution against fleet size (hollow points miss service, a ring marks the sweet spot) and the three prices through a week (tariff as ink steps, day-ahead in teal, real-time in pale grey).

## Story mode

One page of prose in a 70-character measure: section heads at 1.35rem under a full-ink rule, body at 1.02rem on a 1.6 line height.

## Motion

The depot itself is the only thing that moves. Controls ease on hover (0.2 to 0.25s, exponential ease-out). With reduced motion the depot does not play on load and lanes do not move.

## The laws the page is held to

From the owner's front-end rules, measured, not eyeballed:

- Every interactive target at least 24 by 24 px: sliders' thumbs are 24 px targets drawn as 18 px discs; the checkbox is 24 px; pills and chips exceed it.
- Text contrast at least 4.5:1 against every ground it sits on: `web/tests/laws.test.ts` asserts every text colour against every ground it is read on, page and stage.
- No horizontal overflow, nothing unreachable above the fold, no two hit areas overlapping, no console errors: `npm run measure` (`web/scripts/measure.mjs`) measures the built site in all five modes at 1440 and 390 px. Run against `vite preview`, never the dev server.
- One accent marks the thing that matters: mint is energy and nothing else; it is never a text colour.
- The judgment laws (proximity, similarity, serial position, peak-end) are decisions raised with the owner, not restyled in passing.

Measured on the built site: all five modes, both widths, every target at or above 24 px, no overlaps, no overflow, nothing unreachable, no console errors.

## Browser surfaces

Selection is mint on ink. Focus is a 2px blue ring (mint on the stage). Sliders have a hairline track and an ink thumb, mint on the stage. Scrollbars are thin and grey.
