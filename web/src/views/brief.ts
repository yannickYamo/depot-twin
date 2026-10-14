// The short version: the decision, the answer, why, the one rule, what I got wrong and what to do first,
// on one page that reads in about a minute and a half. Every figure comes from outcome.json, which is
// read from the test records; nothing is typed in, and nothing is read between two measured cases.

import { percent, whole } from "./canvas";
import type { Outcome } from "./impact";

/** How a vehicle's energy use might differ from the estimate: on the road, and parked. */
export interface Unknowns {
  road: "0.9" | "1" | "1.1";
  parked: boolean;
}

/** The measured cases the page's one control moves between. */
export const CASES: Array<{ pick: Unknowns; name: string }> = [
  { pick: { road: "0.9", parked: false }, name: "10% less" },
  { pick: { road: "1", parked: false }, name: "As estimated" },
  { pick: { road: "1.1", parked: false }, name: "10% more" },
  { pick: { road: "1.1", parked: true }, name: "10% more, systems on while parked" },
];

/** The idea the whole twin stands on, said the same way wherever it is said. */
export const IDEA = "A depot's grid connection sets how many vehicles it can run, and its software rules decide whether it gets there.";

const REPOSITORY = "https://github.com/yannickYamo/depot-twin/blob/main/";

/** The fleet carried under one case, over all runs and in every fortnight; null where the case was not run. */
export function carried(outcome: Outcome, pick: Unknowns): { all: number; every: number } | null {
  const one = outcome.one_feeder;
  const all = pick.parked ? one.carried_with_the_parked_load[pick.road] : one.carried_by_energy_use[pick.road];
  const every = pick.parked ? one.carried_in_every_fortnight_with_the_parked_load[pick.road] : one.carried_in_every_fortnight_by_energy_use[pick.road];
  return typeof all === "number" && typeof every === "number" ? { all, every } : null;
}

const same = (a: Unknowns, b: Unknowns): boolean => a.road === b.road && a.parked === b.parked;

/** The top of the carried-fleet scale: the largest fleet any case carried, with room above it. */
function scaleTop(outcome: Outcome): number {
  return 50 * Math.ceil((Math.max(...Object.values(outcome.one_feeder.carried_by_energy_use)) + 50) / 50);
}

/** What the one bar shows for a case: its width, its colour, its figure and the verdict in one line. */
export function carriedView(outcome: Outcome, pick: Unknowns): { width: string; kind: "with" | "short"; figure: string; verdict: string } | null {
  const now = carried(outcome, pick);
  if (!now) return null;
  const plan = outcome.one_feeder.planned.fleet;
  const holds = now.every >= plan;
  return {
    width: `${((100 * now.every) / scaleTop(outcome)).toFixed(1)}%`,
    kind: holds ? "with" : "short",
    figure: whole(now.every),
    verdict: holds
      ? `The plan of ${whole(plan)} vehicles holds.`
      : `${whole(now.every)} vehicles hold. The plan holds if a vehicle uses 10% more on the road, or keeps its systems on while parked. Not both.`,
  };
}

function bar(label: string, value: number, top: number, kind: string, shown = `${whole(value)}`): string {
  return `<div class="bf-row"><span>${label}</span><span class="bf-track"><i class="${kind}" style="width:${((100 * value) / top).toFixed(1)}%"></i></span><b>${shown}</b></div>`;
}

/** The one thing to try: move the energy estimate and see which fleet is still carried. */
export function unknownsMarkup(outcome: Outcome, pick: Unknowns): string {
  const plan = outcome.one_feeder.planned.fleet;
  const view = carriedView(outcome, pick);
  const cases = CASES.filter((c) => carried(outcome, c.pick) !== null)
    .map((c) => `<button type="button" role="radio" aria-checked="${same(c.pick, pick)}" data-road="${c.pick.road}" data-parked="${c.pick.parked ? 1 : 0}">${c.name}</button>`)
    .join("");
  return (
    `<div class="bf-pick"><div class="switch" role="radiogroup" aria-label="What a vehicle uses, against my estimate">${cases}</div></div>` +
    (view
      ? `<div class="bf-carry" style="--plan-share:${(plan / scaleTop(outcome)).toFixed(4)}">` +
        `<p class="bf-cap">Carried in all four two-week windows</p>` +
        `<div class="bf-scale"><span class="bf-plan">plan: ${whole(plan)}</span><span class="bf-track big"><i class="${view.kind}" style="width:${view.width}"></i></span></div>` +
        `<b class="bf-now">${view.figure}</b></div>`
      : "") +
    `<p class="bf-verdict" aria-live="polite">${view?.verdict ?? ""}</p>` +
    `<p class="bf-small">Carried: 99% of rides served in nine of ten simulated runs, and at most half of charging visits starting on a low battery.</p>`
  );
}

/** Move the bar that is on the page to another case, so its width eases and the control keeps the focus. */
export function showCase(root: Element, outcome: Outcome, pick: Unknowns): void {
  const view = carriedView(outcome, pick);
  const fill = root.querySelector<HTMLElement>(".bf-track.big i");
  const figure = root.querySelector(".bf-now");
  const verdict = root.querySelector(".bf-verdict");
  if (!view || !fill || !figure || !verdict) {
    root.innerHTML = unknownsMarkup(outcome, pick);
    return;
  }
  fill.className = view.kind;
  fill.style.width = view.width;
  figure.textContent = view.figure;
  verdict.textContent = view.verdict;
  root.querySelectorAll<HTMLElement>("[data-road]").forEach((button) => {
    button.setAttribute("aria-checked", String(same({ road: button.dataset.road as Unknowns["road"], parked: button.dataset.parked === "1" }, pick)));
  });
}

export function briefMarkup(outcome: Outcome, pick: Unknowns): string {
  const one = outcome.one_feeder;
  const d = outcome.decisions;
  const plan = one.planned;
  const estimate = one.carried_by_energy_use["1"]!;
  const lead = d.feeder.lead_months;
  const word = (count: number): string => ["zero", "one", "two", "three", "four", "five", "six"][count] ?? String(count);
  const years = (months: number): string => word(Math.round(months / 12));
  const longest = Math.max(...lead);
  const shortest = Math.min(...lead);
  const topRule = d.calling.with.fleet;
  const fromTheRule = topRule - d.calling.without.fleet;
  const atThePlan = d.plan.energy_saving_at_the_planned_fleet;
  return (
    `<section class="beat"><div><h2>A depot's grid connection is decided years before its vehicles arrive.</h2>` +
    `<p>A new feeder takes ${years(shortest)} to ${years(longest)} years, I assume.</p></div>` +
    `<div class="bf-figure"><div class="bf-lead"><div class="bf-row"><span>Chargers and people</span><span class="bf-track"><i class="tick"></i></span><b>weeks</b></div>` +
    `<div class="bf-row"><span>A new feeder</span><span class="bf-track"><i class="without" style="width:${((100 * shortest) / longest).toFixed(1)}%"></i><i class="range" style="left:${((100 * shortest) / longest).toFixed(1)}%;width:${(100 - (100 * shortest) / longest).toFixed(1)}%"></i></span><b>${shortest} to ${longest} months</b></div></div></div></section>` +

    `<section class="beat beat-answer"><h2>${IDEA} <b>On this parcel: plan for ${whole(plan.fleet)}.</b></h2>` +
    `<dl class="bf-three"><div><dt>Vehicles planned</dt><dd>${whole(plan.fleet)}</dd></div>` +
    `<div><dt>One feeder, at my estimate</dt><dd>${whole(estimate)}</dd></div>` +
    `<div><dt>From one rule</dt><dd>+${whole(fromTheRule)}</dd></div></dl>` +
    `<p>A spreadsheet gets the energy right. It can't show that one rule is worth ${whole(fromTheRule)} vehicles, or what's left when the estimate is wrong.</p></section>` +

    `<section class="beat"><div><h2>Why ${whole(plan.fleet)} and not ${whole(estimate)}: one figure is my estimate.</h2>` +
    `<p>A vehicle's daily energy use has no public source. I ran it 10% either way.</p></div>` +
    `<div class="bf-figure" id="bf-unknowns">${unknownsMarkup(outcome, pick)}</div></section>` +

    `<section class="beat"><div><h2>One rule in software is worth ${whole(fromTheRule)} vehicles.</h2>` +
    `<p>Call a vehicle in only when a charger is free. In steps of 50, one feeder carries ${whole(topRule)} vehicles with it and ${whole(d.calling.without.fleet)} without.</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Vehicles carried</p>` +
    bar("Plain battery threshold", d.calling.without.fleet, topRule, "without") +
    bar("Wait for a free charger", topRule, topRule, "with") +
    `</div></section>` +

    `<section class="beat"><div><h2>What I got wrong: my hourly charging schedule wasn't what served the rides.</h2>` +
    `<p>I built an hourly charging schedule on a ride forecast and credited it with the extra rides. Taken apart, they came from one charging rule.</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Energy cost saved by the hourly schedule</p>` +
    bar(`${whole(d.plan.with.fleet)} vehicles`, d.plan.energy_saving, d.plan.energy_saving, "with", percent(d.plan.energy_saving)) +
    bar(`${whole(plan.fleet)} vehicles`, atThePlan, d.plan.energy_saving, "with", percent(atThePlan)) +
    `<p>At ${whole(d.plan.with.fleet)} vehicles the schedule buys energy ${percent(d.plan.energy_saving)} cheaper. At the planned ${whole(plan.fleet)}, ${percent(atThePlan)} is left to save.</p></div></section>` +

    `<section class="beat last"><div><h2>Before signing the lease</h2>` +
    `<ol><li><b>Meter one vehicle through a whole day.</b> ${whole(estimate - one.carried_in_every_fortnight_with_both)} vehicles of the answer depend on what one vehicle uses in a day.</li>` +
    `<li><b>Put the calling rule in the dispatch software.</b></li>` +
    `<li><b>Apply for the second feeder at signing.</b> The grid can't follow the fleet.</li></ol></div>` +
    `<div class="bf-figure"><p>Not checked against a real depot. One spring, one city.</p>` +
    `<div class="bf-next"><button type="button" class="watch" data-full="play">Explore the depot</button><a class="watch" href="readme.html">Decisions and trade-offs</a><a class="watch" href="${REPOSITORY}docs/SITES.md">Plan your own site</a></div></div></section>`
  );
}
