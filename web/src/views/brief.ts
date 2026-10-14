// The short version: where the depot is, the plan, the one rule, when to apply for the second feeder, what to
// measure first, what forecasting is worth, and what to do before signing. Seven beats, each headed by a
// decision and its value, that read in about a minute and a half. Every figure comes from outcome.json, which is read from the test records; nothing is
// typed in, and nothing is read between two measured cases.

import { percent, whole } from "./canvas";
import { ACCOUNT_LABEL, money, type Outcome } from "./impact";
import type { Forecasts } from "./models";

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

/** The case the page opens on: the one the plan is sized for. */
export const OPENING: Unknowns = { road: "1.1", parked: false };

/** The idea the whole twin stands on, said the same way wherever it is said. */
export const IDEA = "A depot's grid connection sets how many vehicles it can run, and its software rules decide whether it gets there.";

const REPOSITORY = "https://github.com/yannickYamo/depot-twin/blob/main/";

/** The fleet carried under one case, over all runs and in every two-week window; null where the case was not run. */
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
  const name = CASES.find((c) => same(c.pick, pick))?.name.toLowerCase() ?? "";
  return {
    width: `${((100 * now.every) / scaleTop(outcome)).toFixed(1)}%`,
    kind: holds ? "with" : "short",
    figure: whole(now.every),
    verdict: holds
      ? `${whole(now.every)} hold in every window at ${name}. The plan of ${whole(plan)} vehicles holds.`
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
    `<p class="bf-cap">What a vehicle uses in a day, against my estimate</p>` +
    `<div class="bf-pick"><div class="switch" role="radiogroup" aria-label="What a vehicle uses, against my estimate">${cases}</div></div>` +
    (view
      ? `<div class="bf-carry" style="--plan-share:${(plan / scaleTop(outcome)).toFixed(4)}">` +
        `<p class="bf-cap">Vehicles carried in all four two-week windows, of ${whole(scaleTop(outcome))}</p>` +
        `<div class="bf-scale"><span class="bf-plan">plan: ${whole(plan)}</span><span class="bf-track big"><i class="${view.kind}" style="width:${view.width}"></i></span></div>` +
        `<b class="bf-now">${view.figure}</b></div>`
      : "") +
    `<p class="bf-verdict" aria-live="polite">${view?.verdict ?? ""}</p>`
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

const mwh = (kwh: number): string => (kwh / 1000).toFixed(1);
const mw = (kw: number): string => `${(kw / 1000).toFixed(2)} MW`;
const word = (count: number): string => ["zero", "one", "two", "three", "four", "five", "six"][count] ?? String(count);

/** How right the forecast is, from the San Francisco held-out days; empty until the scores arrive. */
function forecastSentence(f: Forecasts | null | undefined): string {
  if (!f) return "";
  return ` It misses San Francisco rides by ${percent(f.sf.reference.error)} an hour ahead, against ${percent(f.sf.last_week.error)} for last week's hour.`;
}

/** The clock-aware threshold against the plan at 500 vehicles, read from E12 with its sign. */
function clockSentence(program: Outcome["program"], fleet: number): string {
  const saving = program?.saving_over_the_clock_aware_threshold_that_waits;
  if (typeof saving !== "number") return "";
  const served = program?.clock_aware_threshold_that_waits_at_500_served;
  const rides = typeof served === "number" ? `, at ${percent(served)} of rides` : "";
  if (saving > 0.005) return `At ${whole(fleet)} vehicles the plan buys energy ${percent(saving)} cheaper than a rule that knows only the clock.`;
  if (saving < -0.005) return `At ${whole(fleet)} vehicles a rule that knows only the clock buys ${percent(-saving / (1 - saving))} cheaper still${rides}.`;
  return `At ${whole(fleet)} vehicles a rule that knows only the clock buys energy at the plan's price.`;
}

/** The fleet carried in every window at each tested share of Ojai with more energy use, against the plan; empty until E30 is in the file. */
function mixBars(outcome: Outcome, top: number): string {
  const shares = outcome.fleet_mix?.shares ?? [];
  const name = (share: number): string => (share === 0 ? "No Ojai" : share === 1 ? "All Ojai" : `${Math.round(100 * share)}% Ojai`);
  return shares
    .filter((row) => typeof row.carried_with_more_energy === "number")
    .map((row) => bar(name(row.share_ojai), row.carried_with_more_energy!, top, row.carried_with_more_energy! >= outcome.one_feeder.planned.fleet ? "with" : "short"))
    .join("");
}

/** The fleet carried in every window at the estimate and at both unknowns against it: the span the meter settles. */
function energyBars(outcome: Outcome, top: number): string {
  const one = outcome.one_feeder;
  const by = one.carried_in_every_fortnight_by_energy_use;
  const cases: [string, number | null | undefined][] = [
    ["As estimated", by["1"]],
    ["10% more, systems on while parked", one.carried_in_every_fortnight_with_both],
  ];
  return cases
    .filter((c): c is [string, number] => typeof c[1] === "number")
    .map(([label, value]) => bar(label, value, top, value >= one.planned.fleet ? "with" : "short"))
    .join("");
}

export function briefMarkup(outcome: Outcome, pick: Unknowns, forecast?: Forecasts | null): string {
  const one = outcome.one_feeder;
  const d = outcome.decisions;
  const site = outcome.site;
  const budget = outcome.budget;
  const cash = outcome.money;
  const plan = one.planned;
  const estimate = one.carried_by_energy_use["1"]!;
  const lead = d.feeder.lead_months;
  const longest = Math.max(...lead);
  const shortest = Math.min(...lead);
  const middle = lead.find((months) => months !== longest && months !== shortest) ?? longest;
  const topRule = d.calling.with.fleet;
  const fromTheRule = topRule - d.calling.without.fleet;
  const ridesFromTheRule = d.calling.with.rides_per_day - d.calling.without.rides_per_day;
  const more = Math.round((one.margin - 1) * 100);
  const late = (months: number): number => d.feeder.a_year_late_on_that_growth_by_lead[String(months)]![1];
  const [jumpLow, jumpHigh] = d.feeder.a_year_late_at_base_costs_on_the_faster_growth_readings;
  const [earlyLow, earlyHigh] = d.feeder.carrying_cost_of_applying_a_year_early;
  const kwh = whole(Math.round(budget.feeder_kwh_per_vehicle_day));
  const atPlanYear = cash.plan_saving_per_year_at_the_plan;
  const mix = outcome.fleet_mix;
  const at = (share: number) => mix?.shares.find((row) => row.share_ojai === share);
  const assumed = at(0.4);
  // The smallest share of Ojai at which the plan still holds with more energy use, and what all I-PACE carries then.
  const holdsFrom = mix?.shares.find((row) => typeof row.carried_with_more_energy === "number" && row.carried_with_more_energy >= plan.fleet);
  const ipaceMore = at(0)?.carried_with_more_energy;
  const alwaysOn = mix?.always_on_kw;
  // What two feeders carry with the same margin (E34), and what 150 kW chargers cost over 60 kW for the same fleet (E33).
  const chargers = outcome.chargers;
  const design = (name: string) => chargers?.designs.find((row) => row.name === name);
  const slow = design("all_60");
  const fast = design("all_150");
  const fastMore = slow && fast ? Math.round((365 * (fast.charger_cost_per_day_on_1 - slow.charger_cost_per_day_on_1)) / 1000) * 1000 : null;
  const sameFleet = slow && fast && slow.carried_on_1 !== null && slow.carried_on_1 === fast.carried_on_1 ? slow.carried_on_1 : null;
  const mixTop = 50 * Math.ceil((Math.max(...(mix?.shares ?? []).map((row) => row.carried_with_more_energy ?? 0), plan.fleet) + 50) / 50);
  const energyTop = 50 * Math.ceil((Math.max(...Object.values(one.carried_in_every_fortnight_by_energy_use).map((v) => v ?? 0), estimate) + 50) / 50);
  const lateBar = (months: number): string => {
    const cost = late(months);
    return bar(`${word(Math.round(months / 12))} years`, Math.max(0, cost), late(longest), "short", cost > 0 ? `up to ${money(cost)}` : "nothing");
  };
  return (
    `<section class="beat beat-where"><div><h2>A ${mw(site.feeder_kw)} feeder in ${site.name} decides how many robotaxis this depot can run.</h2>` +
    `<p>${site.address}. A new feeder takes ${word(Math.round(shortest / 12))} to ${word(Math.round(longest / 12))} years, I assume.</p></div>` +
    `<div class="bf-figure"><div class="bf-lead"><div class="bf-row"><span>Chargers and people</span><span class="bf-track"><i class="tick"></i></span><b>weeks</b></div>` +
    `<div class="bf-row"><span>A new feeder</span><span class="bf-track"><i class="without" style="width:${((100 * shortest) / longest).toFixed(1)}%"></i><i class="range" style="left:${((100 * shortest) / longest).toFixed(1)}%;width:${(100 - (100 * shortest) / longest).toFixed(1)}%"></i></span><b>${shortest} to ${longest} months</b></div></div>` +
    `<p class="bf-small">Two ${whole(site.feeder_kv)} kV lines of about ${mw(site.feeder_kw)} each pass the parcel, per the utility's public map; not a connection offer.</p></div></section>` +

    `<section class="beat beat-answer"><div><h2>Plan one feeder for ${whole(plan.fleet)} vehicles, ${whole(plan.rides_per_day)} rides a day.</h2>` +
    `<p>${mwh(budget.usable_kwh_a_day)} MWh a day over about ${kwh} kWh a vehicle, my estimate, is ${whole(budget.fleet_by_arithmetic)}; the simulated depot carries ${whole(budget.carried)}. ` +
    `${whole(plan.fleet)} still holds in all four two-week windows if a vehicle uses ${more}% more` +
    `${holdsFrom && typeof ipaceMore === "number" && holdsFrom.share_ojai > 0 ? `, with at least ${Math.round(100 * holdsFrom.share_ojai)}% of the fleet Ojai${assumed?.share_ojai === holdsFrom.share_ojai ? " as I assume" : ""}. All I-PACE: ${whole(ipaceMore)}.` : "."}</p></div>` +
    `<div class="bf-figure" id="bf-unknowns">${unknownsMarkup(outcome, pick)}</div>` +
    `${mixBars(outcome, mixTop) ? `<div class="bf-figure"><p class="bf-cap">Vehicles carried at ${more}% more, by share of Ojai; plan ${whole(plan.fleet)}</p>${mixBars(outcome, mixTop)}</div>` : ""}</section>` +

    `<section class="beat beat-rule"><div><h2>One dispatch setting is worth ${whole(fromTheRule)} vehicles, ${whole(ridesFromTheRule)} rides and ${money(cash.calling_rule_per_year)} a year.</h2>` +
    `<p>Call a vehicle in only when a charger is free: one feeder carries ${whole(topRule)} vehicles with the rule and ${whole(d.calling.without.fleet)} without. No hardware.` +
    `${sameFleet !== null && fastMore !== null ? ` 150 kW chargers carry the same ${whole(sameFleet)} as 60 kW, for ${money(fastMore)} a year more.` : ""}</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Vehicles carried, on the same steps of ${whole(d.calling.steps[1]! - d.calling.steps[0]!)} · earned after costs, a day</p>` +
    bar("Plain battery threshold", d.calling.without.fleet, topRule, "without", `${whole(d.calling.without.fleet)} · ${money(d.calling.without.contribution_per_day)}`) +
    bar("Wait for a free charger", topRule, topRule, "with", `${whole(topRule)} · ${money(d.calling.with.contribution_per_day)}`) +
    `</div></section>` +

    `<section class="beat beat-feeder"><div><h2>Apply for the second feeder at signing. If the utility takes ${word(Math.round(longest / 12))} years, a year late forgoes up to ${money(late(longest))}.</h2>` +
    `<p>${typeof chargers?.planned_on_two_feeders === "number" ? `Two feeders carry ${whole(chargers.planned_on_two_feeders)} with the same 10% margin. ` : ""}A year early costs ${money(earlyLow)} to ${money(earlyHigh)}.</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Forgone by applying a year late, by how long the utility takes</p>` +
    lateBar(shortest) + lateBar(middle) + lateBar(longest) +
    `<p class="bf-small">Lead times are my assumption. ${whole(d.feeder.scenarios)} scenarios, not a test; ${money(jumpLow)} to ${money(jumpHigh)} if the area's fleet jumps again.</p></div></section>` +

    `<section class="beat beat-meter"><div><h2>Meter one vehicle for a day. What it uses decides ${whole(cash.metering_span_vehicles)} vehicles, about ${money(cash.metering_span_per_year)} a year.</h2>` +
    `<p>Nearly half of the ${kwh} kWh is computers, sensors and climate, with no public source. ` +
    
    `${alwaysOn && typeof alwaysOn.carried_low === "number" && typeof alwaysOn.carried_high === "number" ? ` For an Ojai fleet, ${alwaysOn.low} to ${alwaysOn.high} kW of it moves the fleet from ${whole(alwaysOn.carried_low)} to ${whole(alwaysOn.carried_high)}.` : ""}</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Vehicles carried in all four windows</p>${energyBars(outcome, energyTop)}</div></section>` +

    `<section class="beat beat-ml"><div><h2>The forecast and hourly plan buy cheaper energy, ${atPlanYear !== null ? `about ${money(atPlanYear)} a year at ${whole(plan.fleet)}` : `at ${whole(plan.fleet)}`}, not more vehicles.</h2>` +
    `<p>The forecast sets the hourly plan that calls vehicles in.${forecastSentence(forecast)}</p>` +
    `<p>Next: solar, a battery and paid grid events, where each hour is a choice to store, draw or shed. There a forecast of rides, sun and price should earn its place.</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Worth a year at the plan</p>` +
    bar("The dispatch rule", cash.calling_rule_per_year, cash.calling_rule_per_year, "with", `+${money(cash.calling_rule_per_year)}`) +
    (atPlanYear !== null ? bar("The forecast's cheaper energy", atPlanYear, cash.calling_rule_per_year, "with", `+${money(atPlanYear)}`) : "") +
    `<p class="bf-small">${clockSentence(outcome.program, d.plan.with.fleet)}</p></div></section>` +

    `<section class="beat last beat-next"><div><h2>Before signing the lease</h2>` +
    `<ol><li><b>Meter one vehicle, on the road and parked.</b></li>` +
    `<li><b>Ship the calling rule.</b></li>` +
    `<li><b>Apply for the second feeder.</b></li></ol>` +
    `<p class="bf-close">In one line</p><p>${IDEA}</p></div>` +
    `<div class="bf-figure"><p>Not checked against a real depot. Four two-week windows of one spring in one city.</p>` +
    `<p class="bf-small">At the plan the depot earns about ${money(plan.contribution_per_day)} a day after costs, ${money(cash.planned_per_year)} a year, under my cost assumptions. ${ACCOUNT_LABEL}</p>` +
    `<div class="bf-next"><button type="button" class="watch" data-full="play">Explore the depot</button><a class="watch" href="readme.html">Decisions and trade-offs</a><a class="watch" href="${REPOSITORY}docs/SITES.md">Plan your own site</a></div></div></section>`
  );
}
