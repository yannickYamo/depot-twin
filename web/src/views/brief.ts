// The short version: where the depot is, the energy budget, the answer and why, the one rule, what the
// forecast and the plan are worth, the money a year, and what to do first. Seven beats that read in about a
// minute and a half. Every figure comes from outcome.json, which is read from the test records; nothing is
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

/** What the plan does at the planned fleet, read from its record: whether it, or the floor, is in charge there. */
function planVerdict(outcome: Outcome): { runsThePlan: boolean; text: string } {
  const at = outcome.plan_at_the_planned_fleet;
  const plan = outcome.one_feeder.planned.fleet;
  if (!at || typeof at.forced_call_share !== "number" || typeof at.charge_on_the_road !== "number") {
    return { runsThePlan: false, text: `At ${whole(plan)} vehicles a simple rule runs the planned fleet.` };
  }
  const runsThePlan = at.forced_call_share < 0.1 && at.charge_on_the_road >= 0.5;
  return {
    runsThePlan,
    text: runsThePlan
      ? `At ${whole(plan)} vehicles the plan keeps the fleet at ${percent(at.charge_on_the_road)} charge; the floor forces ${percent(at.forced_call_share)} of its calls.`
      : `At ${whole(plan)} the floor forces ${percent(at.forced_call_share)} of the plan's calls and its fleet rides at ${percent(at.charge_on_the_road)} charge, so a simple rule runs the planned fleet.`,
  };
}

/** How the forecast is used and how right it is, from the held-out days; empty until the scores arrive. */
function forecastSentence(f: Forecasts | null | undefined): string {
  if (!f) return "";
  return `The forecast sets the hourly plan that calls vehicles in. An hour ahead it misses rides by ${percent(f.sf.reference.error)} on ${whole(f.holdout_days)} held-out days, against ${percent(f.sf.last_week.error)} for last week's same hour. `;
}

/** The hourly program against a threshold that waits for a charger and only knows the clock, read from E12 with its sign. */
function programSentence(program: Outcome["program"]): string {
  if (
    !program ||
    typeof program.saving_over_the_clock_aware_threshold_that_waits !== "number" ||
    typeof program.quota_at_ceiling_share_at_500 !== "number"
  ) {
    return "";
  }
  const saving = program.saving_over_the_clock_aware_threshold_that_waits;
  const ceiling = ` Its program sits at its ceiling in ${percent(program.quota_at_ceiling_share_at_500)} of hours.`;
  const served = program.clock_aware_threshold_that_waits_at_500_served;
  const rides = typeof served === "number" ? `, at ${percent(served)} of rides` : "";
  if (saving >= 0.01) {
    return `${ceiling} In the energy-price test at 500 it buys energy ${percent(saving)} cheaper than a clock-aware threshold that waits.`;
  }
  if (saving <= -0.01) {
    return `${ceiling} In the energy-price test at 500 a clock-aware threshold that waits buys ${percent(-saving / (1 - saving))} cheaper still${rides}.`;
  }
  return `${ceiling} In the energy-price test at 500 a clock-aware threshold that waits buys energy at the same price.`;
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
  const topRule = d.calling.with.fleet;
  const fromTheRule = topRule - d.calling.without.fleet;
  const ridesFromTheRule = d.calling.with.rides_per_day - d.calling.without.rides_per_day;
  const more = Math.round((one.margin - 1) * 100);
  const atThePlan = d.plan.energy_saving_at_the_planned_fleet;
  const verdict = planVerdict(outcome);
  const fourYear = d.feeder.a_year_late_on_that_growth_by_lead[String(longest)]![1];
  const [jumpLow, jumpHigh] = d.feeder.a_year_late_at_base_costs_on_the_faster_growth_readings;
  const [earlyLow, earlyHigh] = d.feeder.carrying_cost_of_applying_a_year_early;
  const kwh = whole(Math.round(budget.feeder_kwh_per_vehicle_day));
  const budgetShare = (100 * budget.carried * budget.feeder_kwh_per_vehicle_day) / budget.usable_kwh_a_day;
  const programLine = programSentence(outcome.program);
  const scale = Math.max(d.plan.energy_saving, atThePlan);
  const atPlanYear = cash.plan_saving_per_year_at_the_plan;
  return (
    `<section class="beat beat-where"><div><h2>A ${mw(site.feeder_kw)} feeder in ${site.name} decides how many robotaxis this depot can run.</h2>` +
    `<p>${site.address}. Chargers and people arrive in weeks; a new feeder takes ${word(Math.round(shortest / 12))} to ${word(Math.round(longest / 12))} years, I assume.</p></div>` +
    `<div class="bf-figure"><div class="bf-lead"><div class="bf-row"><span>Chargers and people</span><span class="bf-track"><i class="tick"></i></span><b>weeks</b></div>` +
    `<div class="bf-row"><span>A new feeder</span><span class="bf-track"><i class="without" style="width:${((100 * shortest) / longest).toFixed(1)}%"></i><i class="range" style="left:${((100 * shortest) / longest).toFixed(1)}%;width:${(100 - (100 * shortest) / longest).toFixed(1)}%"></i></span><b>${shortest} to ${longest} months</b></div></div>` +
    `<p class="bf-small">Two ${whole(site.feeder_kv)} kV lines of about ${mw(site.feeder_kw)} each pass the parcel, per the utility's public map; not a connection offer.</p></div></section>` +

    `<section class="beat beat-budget"><div><h2>One feeder is ${mwh(budget.usable_kwh_a_day)} MWh a day. A vehicle takes about ${kwh} kWh. That is ${whole(budget.fleet_by_arithmetic)} vehicles by arithmetic, and ${whole(budget.carried)} in the simulated depot.</h2>` +
    `<p>The ${kwh} kWh is my estimate. Nearly half of it is the always-on load of computers, sensors and climate, which has no public source.</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">${whole(site.feeder_kw)} kW at the ${Math.round(100 * site.usable_share)}% the load manager allows, over a day, and what ${whole(budget.carried)} vehicles take from it</p>` +
    `<div class="bf-budget"><span class="bf-track big"><i class="with" style="width:${budgetShare.toFixed(1)}%"></i></span>` +
    `<div class="bf-budget-ends"><span>${whole(budget.carried)} × ${kwh} kWh = ${mwh(budget.carried * budget.feeder_kwh_per_vehicle_day)} MWh</span><span>${mwh(budget.usable_kwh_a_day)} MWh usable</span></div></div>` +
    `<p class="bf-small">Carried: 99% of rides served in nine of ten runs, and at most half of depot visits starting on a low battery.</p></div></section>` +

    `<section class="beat beat-answer"><h2>${IDEA} <b>On this parcel: plan one feeder for ${whole(plan.fleet)} vehicles, ${whole(plan.rides_per_day)} rides a day.</b></h2>` +
    `<div class="bf-why"><p>${whole(plan.fleet)} still holds in all four two-week windows if a vehicle uses ${more}% more than I estimated. ` +
    `My registered rule gives ${whole(one.registered_rule_gives)}; one window of four fails it.</p>` +
    `<div class="bf-figure" id="bf-unknowns">${unknownsMarkup(outcome, pick)}</div></div></section>` +

    `<section class="beat beat-rule"><div><h2>One dispatch setting is worth ${whole(fromTheRule)} vehicles, ${whole(ridesFromTheRule)} rides and ${money(cash.calling_rule_per_year)} a year.</h2>` +
    `<p>Call a vehicle in only when a charger is free, so it serves rides instead of queueing. ` +
    `One feeder carries ${whole(topRule)} vehicles with the rule and ${whole(d.calling.without.fleet)} without. No hardware.</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Vehicles carried, on the same steps of ${whole(d.calling.steps[1]! - d.calling.steps[0]!)} · earned after costs, a day</p>` +
    bar("Plain battery threshold", d.calling.without.fleet, topRule, "without", `${whole(d.calling.without.fleet)} · ${money(d.calling.without.contribution_per_day)}`) +
    bar("Wait for a free charger", topRule, topRule, "with", `${whole(topRule)} · ${money(d.calling.with.contribution_per_day)}`) +
    `</div></section>` +

    `<section class="beat beat-ml"><div><h2>The ride forecast and hourly charging plan add no rides at ${whole(plan.fleet)} vehicles. They buy energy ${percent(atThePlan)} cheaper there, and ${percent(d.plan.energy_saving)} cheaper at ${whole(d.plan.with.fleet)}.</h2>` +
    `<p>${forecastSentence(forecast)}${verdict.text}</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">Energy bought cheaper by the plan · a year</p>` +
    bar(`${whole(d.plan.with.fleet)} vehicles`, d.plan.energy_saving, scale, "with", `${percent(d.plan.energy_saving)} · ${money(cash.plan_saving_per_year_at_500)}`) +
    bar(`${whole(plan.fleet)} vehicles`, atThePlan, scale, "with", `${percent(atThePlan)}${atPlanYear !== null ? ` · ${money(atPlanYear)}` : ""}`) +
    `<p class="bf-small">${programLine.trim()}</p></div></section>` +

    `<section class="beat beat-money"><div><h2>At the plan the depot earns about ${money(plan.contribution_per_day)} a day after costs, ${money(cash.planned_per_year)} a year, under my cost assumptions.</h2>` +
    `<p>${ACCOUNT_LABEL} Owning and running the vehicles is more than half of the fares, and has no public source.</p></div>` +
    `<div class="bf-figure"><p class="bf-cap">What each decision is worth, a year</p><dl class="bf-money">` +
    `<div><dt>The calling rule</dt><dd>+${money(cash.calling_rule_per_year)}</dd></div>` +
    `<div><dt>The plan's cheaper energy at ${whole(plan.fleet)}</dt><dd>${atPlanYear !== null ? `+${money(atPlanYear)}` : "not measured"}</dd></div>` +
    `<div><dt>The second feeder applied for a year late</dt><dd>up to ${money(fourYear)} forgone at a ${word(Math.round(longest / 12))}-year lead; ${money(jumpLow)} to ${money(jumpHigh)} if the area jumps again</dd></div>` +
    `<div><dt>Applied for a year early</dt><dd>${money(earlyLow)} to ${money(earlyHigh)}</dd></div>` +
    `</dl><p class="bf-small">Measured at different fleets, so not added. The feeder row is ${whole(d.feeder.scenarios)} scenarios, not a test.</p></div></section>` +

    `<section class="beat last beat-next"><div><h2>Before signing the lease</h2>` +
    `<ol><li><b>Meter one vehicle for a day, on the road and parked.</b> The ${whole(cash.metering_span_vehicles)} vehicles between ${whole(one.carried_in_every_fortnight_with_both)} and ${whole(estimate)} are about ${money(cash.metering_span_per_year)} a year.</li>` +
    `<li><b>Put the calling rule in the dispatch software.</b></li>` +
    `<li><b>Apply for the second feeder at signing.</b> The grid can't follow the fleet.</li></ol></div>` +
    `<div class="bf-figure"><p>Not checked against a real depot. Four two-week windows of one spring in one city.</p>` +
    `<div class="bf-next"><button type="button" class="watch" data-full="play">Explore the depot</button><a class="watch" href="readme.html">Decisions and trade-offs</a><a class="watch" href="${REPOSITORY}docs/SITES.md">Plan your own site</a></div></div></section>`
  );
}
