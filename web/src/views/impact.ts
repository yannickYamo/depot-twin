// What the four decisions are worth: each one a measured pair, the same depot with the decision taken and
// not taken. The figures come from outcome.json, which is read from the test records; nothing is typed in.
// Nothing is added across decisions either: they were measured at different fleets.

import type { RecordedChargers, RecordedTypes } from "./types";
import { percent, whole } from "./canvas";
import { forecastMarkup, type Forecasts } from "./models";

export interface Arm {
  fleet: number;
  rides_per_day: number;
  contribution_per_day: number;
  rides_served_share?: number;
  rides_served_share_lowest_run?: number;
  energy_per_kwh?: number;
  power_share_used?: number;
}

export interface Outcome {
  fare_per_ride: number;
  runs: number;
  rides_per_vehicle_day: number;
  area_vehicles_today: [number, number];
  one_feeder: {
    planned: Arm;
    power_share_used_at_the_plan_with_more_energy_use: number;
    margin: number;
    carried_by_energy_use: Record<string, number>;
    registered_rule_gives: number;
    carried_in_every_fortnight_by_energy_use: Record<string, number | null>;
    carried_in_every_fortnight_with_the_parked_load: Record<string, number | null>;
    carried_with_the_parked_load: Record<string, number>;
    carried_in_every_fortnight_with_both: number;
    planned_holds_with_the_parked_load: boolean;
    fortnights: number;
    draws_a_fortnight: number;
    served_at_the_limit: number;
    feeder_kwh_per_vehicle_day: number;
    usable_kwh_a_day: number;
  };
  decisions: {
    calling: {
      steps: number[];
      without: Arm;
      with: Arm;
      plain_at_the_larger_fleet: { fleet: number; rides_served_share: number; fortnights_at_the_floor: number; fortnights: number };
    };
    power: { without: Arm; with: Arm; no_gain_at: number[] };
    plan: { without: Arm; with: Arm; energy_saving: number; energy_saving_at_the_planned_fleet: number };
    feeder: {
      capital: number;
      months_until_one_feeder_is_full: [number, number];
      a_year_late_at_base_costs_on_the_faster_growth_readings: [number, number];
      a_year_late_at_base_costs_on_the_slowest_growth_reading: [number, number];
      a_year_late_across_fleet_costs: [number, number];
      carrying_cost_of_applying_a_year_early: [number, number];
      lead_months: number[];
      scenarios: number;
      growth_since_the_footprint_settled: number;
      months_on_that_growth: number[];
      a_year_late_on_that_growth_by_lead: Record<string, [number, number]>;
    };
  };
  /** Where the depot is: the parcel and the feeder, from the site record and the utility's map reading. */
  site: {
    name: string;
    address: string;
    lat: number;
    lon: number;
    feeder_kw: number;
    usable_share: number;
    feeder_kv: number;
    feeders_with_headroom: Array<{ name: string; min_kw: number; max_kw: number }>;
    source: string;
  };
  /** The energy budget: the feeder's day over a vehicle's day, and the fleets that gives. */
  budget: {
    usable_kwh_a_day: number;
    feeder_kwh_per_vehicle_day: number;
    fleet_by_arithmetic: number;
    fleet_by_arithmetic_with_power_to_spare: number | null;
    carried: number;
    planned: number;
  };
  /** The dollars a year behind each decision, from the same account as the cards. */
  money: {
    per_vehicle_day_at_the_plan: number;
    planned_per_year: number;
    calling_rule_per_day: number;
    calling_rule_per_year: number;
    metering_span_vehicles: number;
    metering_span_per_year: number;
    energy_per_day_at_the_plan: number | null;
    plan_saving_per_day_at_the_plan: number | null;
    plan_saving_per_year_at_the_plan: number | null;
    plan_saving_per_day_at_500: number;
    plan_saving_per_year_at_500: number;
  };
  /** What the plan does at the planned fleet: whether it, or the low-battery floor, is in charge there. */
  plan_at_the_planned_fleet?: {
    forced_call_share: number | null;
    quota_at_ceiling_share: number | null;
    charge_on_the_road: number | null;
    arrived_at_floor_share: number | null;
    carried_by_fortnight: Record<string, boolean> | null;
  };
  /** The fleet carried at each share of the second vehicle type, and what each type does at the plan (E30 to E32). */
  fleet_mix?: {
    shares: Array<{ share_ojai: number; carried: number | null; carried_with_more_energy: number | null; planned: number }>;
    types_at_the_plan: RecordedTypes;
    always_on_kw: { low: number; high: number; carried_low: number | null; carried_high: number | null };
    by_range: { carried: number | null; the_rule_that_waits: number };
  };
  /** Each charger design's fleet on one feeder and two, its cost, and each type's time on the charger (E33, E34). */
  chargers?: RecordedChargers;
  /** The hourly program against a threshold that only knows the clock: what the optimizer adds on its own. */
  program?: {
    plan_with_prices_at_500_per_kwh: number | null;
    clock_aware_threshold_that_waits_at_500_per_kwh: number | null;
    saving_over_the_clock_aware_threshold_that_waits: number | null;
    plan_with_prices_at_500_served?: number | null;
    clock_aware_threshold_that_waits_at_500_served?: number | null;
    quota_at_ceiling_share_at_500: number | null;
    beats_the_clock_aware_threshold: boolean | null;
    decides_in_a_quarter_of_hours: boolean | null;
  };
}

/** Whether a loaded file has the shape this view reads: checked once, where the file comes in. */
export function isOutcome(value: unknown): value is Outcome {
  const file = value as Partial<Outcome> | null;
  const d = file?.decisions;
  return (
    typeof file?.fare_per_ride === "number" &&
    typeof file.one_feeder?.planned?.fleet === "number" &&
    typeof file.one_feeder.carried_by_energy_use === "object" &&
    typeof d?.calling?.with?.fleet === "number" &&
    typeof d.calling.plain_at_the_larger_fleet?.rides_served_share === "number" &&
    typeof d.power?.with?.rides_per_day === "number" &&
    typeof d.plan?.energy_saving === "number" &&
    typeof d.plan.energy_saving_at_the_planned_fleet === "number" &&
    Array.isArray(d.feeder?.a_year_late_at_base_costs_on_the_faster_growth_readings) &&
    Array.isArray(d.feeder.lead_months) &&
    typeof file.site?.address === "string" &&
    typeof file.budget?.fleet_by_arithmetic === "number" &&
    typeof file.money?.calling_rule_per_year === "number"
  );
}

export const DECISIONS = ["calling", "power", "plan", "feeder"] as const;
export type Decision = (typeof DECISIONS)[number];
export type Taken = Record<Decision, boolean>;

/** Dollars at the size a reader compares: millions with a decimal, thousands rounded to the hundred. */
export function money(value: number): string {
  const sign = value < 0 ? "−" : "";
  const size = Math.abs(value);
  if (size >= 1e6) return `${sign}$${(size / 1e6).toFixed(1)}M`;
  if (size >= 1e4) return `${sign}$${whole(Math.round(size / 100) * 100)}`;
  if (size >= 1e3) return `${sign}$${whole(Math.round(size / 10) * 10)}`;
  return `${sign}$${whole(Math.round(size))}`;
}

function signed(value: number, show: (v: number) => string): string {
  return `${value < 0 ? "−" : "+"}${show(Math.abs(value)).replace("−", "")}`;
}

interface Card {
  title: string;
  costs: string;
  where: string;
  figures: [string, string][];
  worth: string;
  off: string;
  on: string;
  watch: string;
}

function cards(outcome: Outcome, taken: Taken): Record<Decision, Card> {
  const { calling, power, plan, feeder } = outcome.decisions;
  const pick = <T extends { without: Arm; with: Arm }>(pair: T, key: Decision): Arm => (taken[key] ? pair.with : pair.without);
  const c = pick(calling, "calling");
  const p = pick(power, "power");
  const e = pick(plan, "plan");
  const [low, high] = feeder.a_year_late_at_base_costs_on_the_faster_growth_readings;
  const [, slowHigh] = feeder.a_year_late_at_base_costs_on_the_slowest_growth_reading;
  const [earlyLow, earlyHigh] = feeder.carrying_cost_of_applying_a_year_early;
  const steps = calling.steps[1] - calling.steps[0];
  const leadsIn = feeder.lead_months;
  const slowBy = (lead: number): [number, number] => feeder.a_year_late_on_that_growth_by_lead[String(lead)];
  const moreDay = calling.with.contribution_per_day - calling.without.contribution_per_day;
  return {
    calling: {
      title: "Call a vehicle in only when a charger is free",
      costs: "A software setting. Measured in the twin.",
      where: `Both rules on the same steps of ${steps} vehicles`,
      figures: [
        ["Vehicles the feeder carries", whole(c.fleet)],
        ["Rides a day", whole(c.rides_per_day)],
        ["Earned after costs, a day", money(c.contribution_per_day)],
      ],
      worth: `${signed(calling.with.fleet - calling.without.fleet, whole)} vehicles, ${signed(calling.with.rides_per_day - calling.without.rides_per_day, whole)} rides and ${signed(moreDay, money)} a day, each rule at the largest fleet it carried. At the planned fleet the plain rule misses the service floor in one two-week window of four.`,
      off: "Called in at a set charge, charger free or not",
      on: "Called in once a charger is free",
      watch: "Watch both depots run",
    },
    power: {
      title: "Feed chargers in the order vehicles plugged in",
      costs: "A software setting. Measured in the twin.",
      where: `At ${whole(p.fleet)} vehicles on one feeder, a fleet that has outgrown its connection`,
      figures: [
        ["Rides served", percent(p.rides_served_share ?? 0)],
        ["Rides a day", whole(p.rides_per_day)],
      ],
      worth: `${signed(power.with.rides_per_day - power.without.rides_per_day, whole)} rides a day kept, ${money(outcome.fare_per_ride * (power.with.rides_per_day - power.without.rides_per_day))} a day in fares. No gain at ${power.no_gain_at.map(whole).join(" or ")} vehicles, where the feeder has power to spare: it is insurance.`,
      off: "Power to the emptiest vehicle first",
      on: "Power in order of arrival",
      watch: "Watch the overloaded depot both ways",
    },
    plan: {
      title: "Plan charging around the evening peak",
      costs: "The day-ahead planner. Measured in the twin.",
      where: `At ${whole(e.fleet)} vehicles`,
      figures: [
        ["Energy, a kWh", `$${(e.energy_per_kwh ?? 0).toFixed(3)}`],
        ["Earned after costs, a day", money(e.contribution_per_day)],
      ],
      worth: `Energy ${percent(plan.energy_saving)} cheaper with no ride lost: ${signed(outcome.money.plan_saving_per_day_at_500, money)} a day, ${money(outcome.money.plan_saving_per_year_at_500)} a year on the energy bill. Small beside the other three.`,
      off: "Charging whenever a vehicle is in",
      on: "Charging steered off the peak price",
      watch: "Open the recorded plan",
    },
    feeder: {
      title: "Order the second feeder when the lease is signed",
      costs: `${money(feeder.capital)} of connection, paid a year sooner. A scenario, not a measured pair.`,
      where: `At ${percent(feeder.growth_since_the_footprint_settled)} a month, the growth since the service area last changed, the area outgrows the plan in ${feeder.months_on_that_growth[0]} to ${feeder.months_on_that_growth[feeder.months_on_that_growth.length - 1]} months`,
      figures: taken.feeder
        ? [
            ["Cost of applying a year early", `${money(earlyLow)} to ${money(earlyHigh)}`],
            ["At risk if growth never comes", money(feeder.capital)],
          ]
        : [
            ["Lost by waiting a year, feeder takes two years", atMost(slowBy(leadsIn[0])[1])],
            [`Lost by waiting a year, feeder takes ${leadsIn[leadsIn.length - 1] / 12} years`, `${atMost(slowBy(leadsIn[leadsIn.length - 1])[0])} to ${money(slowBy(leadsIn[leadsIn.length - 1])[1])}`],
          ],
      worth: `A year's delay costs nothing if a feeder takes two years, and up to ${money(slowHigh)} if it takes four. If the area jumps again as it did when the service area was enlarged, ${money(low)} to ${money(high)}. Applying a year early costs ${money(earlyLow)} to ${money(earlyHigh)}. A table of ${feeder.scenarios} scenarios, not a test.`,
      off: "Ordered a year after signing",
      on: "Ordered at signing",
      watch: "Watch one feeder against two",
    },
  };
}

/** A cost of waiting that can be a small saving: said as what it is. */
function atMost(value: number): string {
  return value <= 0 ? "nothing" : money(value);
}

/** What the account is, said wherever a dollar figure from it is shown. */
export const ACCOUNT_LABEL = "It ranks designs. It isn't a profit forecast.";

/** The answer as a chip beside the twin's one sentence, so every tab states it. */
export function answerMarkup(outcome: Outcome): string {
  return `Plan ${whole(outcome.one_feeder.planned.fleet)}`;
}

/** What each rule is worth in dollars, above the account: one row a rule, from the same records as the cards. */
export function worthMarkup(outcome: Outcome): string {
  const { calling, power, plan, feeder } = outcome.decisions;
  const [low, high] = feeder.a_year_late_at_base_costs_on_the_faster_growth_readings;
  const [, slowHigh] = feeder.a_year_late_at_base_costs_on_the_slowest_growth_reading;
  const [earlyLow, earlyHigh] = feeder.carrying_cost_of_applying_a_year_early;
  const row = (what: string, worth: string, where: string): string => `<tr><th scope="row">${what}</th><td>${worth}</td><td>${where}</td></tr>`;
  return (
    `<h2>What each rule is worth, in dollars a year</h2>` +
    `<p class="wb-note account-label"><b>${ACCOUNT_LABEL}</b></p>` +
    `<table class="worth-table"><thead><tr><th scope="col">Decision</th><th scope="col">A year</th><th scope="col">A day, and the basis</th></tr></thead><tbody>` +
    row("Call a vehicle in only when a charger is free", `${signed(outcome.money.calling_rule_per_year, money)} after costs`, `${signed(calling.with.contribution_per_day - calling.without.contribution_per_day, money)} a day: ${whole(calling.with.fleet)} vehicles carried against ${whole(calling.without.fleet)}`) +
    row("Feed chargers in the order vehicles plugged in", `${money(365 * outcome.fare_per_ride * (power.with.rides_per_day - power.without.rides_per_day))} in fares`, `${money(outcome.fare_per_ride * (power.with.rides_per_day - power.without.rides_per_day))} a day at ${whole(power.with.fleet)} vehicles, a fleet past its feeder; nothing at the plan`) +
    row("Plan charging around the evening peak", `${signed(outcome.money.plan_saving_per_year_at_500, money)} on energy at ${whole(plan.with.fleet)} vehicles${outcome.money.plan_saving_per_year_at_the_plan !== null ? `; ${signed(outcome.money.plan_saving_per_year_at_the_plan, money)} at ${whole(outcome.one_feeder.planned.fleet)}` : ""}`, `${signed(outcome.money.plan_saving_per_day_at_500, money)} a day: energy ${percent(plan.energy_saving)} cheaper at ${whole(plan.with.fleet)} vehicles, ${percent(plan.energy_saving_at_the_planned_fleet)} at ${whole(outcome.one_feeder.planned.fleet)}`) +
    row("Order the second feeder at signing", `Up to ${money(slowHigh)} forgone a year late; ${money(low)} to ${money(high)} if the area jumps`, `A scenario on an assumed lead time: against ${money(earlyLow)} to ${money(earlyHigh)} for applying a year early`) +
    `</tbody></table>` +
    `<p class="wb-note">Every figure is money an operator would keep under my cost assumptions: fares, less energy, the site, people and the vehicles. Measured at different fleets, so not added together. The account below shows where each comes from.</p>`
  );
}

/** The headline: the fleet to plan one feeder for, and what the feeder carries as the vehicles' energy use moves. */
function headline(outcome: Outcome, taken: Taken): string {
  const { calling } = outcome.decisions;
  const one = outcome.one_feeder;
  const by = one.carried_by_energy_use;
  const parked = one.carried_with_the_parked_load;
  const more = Math.round((one.margin - 1) * 100);
  const high = String(one.margin);
  const each = one.carried_in_every_fortnight_by_energy_use;
  const eachParked = one.carried_in_every_fortnight_with_the_parked_load;
  const tile = (label: string, all: number, every: number | null): string =>
    `<div><dt>${label}</dt><dd>${whole(all)}<span class="unit">vehicles</span></dd><small>${every === null ? "no fleet run" : whole(every)} in every two-week window</small></div>`;
  const rule = taken.calling
    ? "It needs the calling rule below."
    : `It needs the calling rule, switched off below: the plain rule carries ${whole(calling.without.fleet)}.`;
  return (
    `<p class="impact-headline"><b>Plan one feeder for ${whole(one.planned.fleet)} vehicles, ${whole(one.planned.rides_per_day)} rides a day.</b> ` +
    `It holds in every two-week window with ${more}% more energy on the road, or with systems left on while parked. With both, the fleet that holds is ${whole(one.carried_in_every_fortnight_with_both)}. ${rule}</p>` +
    `<p class="impact-tiles-name">Largest fleet one feeder carried over ${one.fortnights} two-week windows of real demand. Large figure: all runs together. Small figure: every two-week window alone, which the plan asks for.</p>` +
    `<dl class="impact-margin" aria-label="The largest fleet one feeder carried, by the vehicles' energy use">` +
    tile(`${more}% less energy than estimated`, by["0.9"], each["0.9"]) +
    tile("As estimated", by["1"], each["1"]) +
    tile(`${more}% more on the road`, by[high], each[high]) +
    tile("Systems on while parked", parked["1"], eachParked["1"]) +
    tile("Both", parked[high], eachParked[high]) +
    `<div><dt>The plan</dt><dd>${whole(one.planned.fleet)}<span class="unit">vehicles</span></dd><small>holds against either one alone</small></div>` +
    `</dl>` +
    `<p class="impact-rule">The feeder's energy is the limit. ${(one.usable_kwh_a_day / 1000).toFixed(1)} MWh a day over about ${one.feeder_kwh_per_vehicle_day.toFixed(0)} kWh a vehicle is ${whole(outcome.budget.fleet_by_arithmetic)} vehicles by arithmetic; the simulated depot carries ${whole(outcome.budget.carried)}; with ${more}% more energy a vehicle, ${whole(one.planned.fleet)} still holds in every window. The ${one.feeder_kwh_per_vehicle_day.toFixed(0)} kWh has no public source, so meter one vehicle's whole day first. The rule I registered before the test gives ${whole(one.registered_rule_gives)} over all runs together; one two-week window of four does not carry it, so the plan is ${whole(one.planned.fleet)}.</p>`
  );
}

export function impactMarkup(outcome: Outcome, taken: Taken, watching: Decision | null, models: Forecasts | null = null): string {
  const all = DECISIONS.every((key) => taken[key]);
  const none = DECISIONS.every((key) => !taken[key]);
  const made = cards(outcome, taken);
  const card = (key: Decision): string => {
    const it = made[key];
    return (
      `<article class="decision${taken[key] ? " taken" : ""}${watching === key ? " watching" : ""}">` +
      `<p class="decision-cost">${it.costs}</p>` +
      `<h3>${it.title}</h3>` +
      `<div class="switch" role="radiogroup" aria-label="${it.title}">` +
      `<button type="button" role="radio" aria-checked="${!taken[key]}" data-decision="${key}" data-take="0">Without</button>` +
      `<button type="button" role="radio" aria-checked="${taken[key]}" data-decision="${key}" data-take="1">With</button>` +
      `</div>` +
      `<p class="decision-state">${taken[key] ? it.on : it.off}. ${it.where}.</p>` +
      `<dl>${it.figures.map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("")}</dl>` +
      `<p class="decision-worth">${it.worth}</p>` +
      `<button type="button" class="watch" data-watch="${key}">${it.watch}</button>` +
      `</article>`
    );
  };
  return (
    `<div class="impact-head"><h2>What each choice is worth in this model</h2>` +
    `<div class="switch master" role="radiogroup" aria-label="All four decisions">` +
    `<button type="button" role="radio" aria-checked="${none}" data-all="0">Plain depot</button>` +
    `<button type="button" role="radio" aria-checked="${all}" data-all="1">With the four decisions</button>` +
    `</div></div>` +
    headline(outcome, taken) +
    (models ? forecastMarkup(models) : "") +
    `<h3 class="impact-part">What the control rules and the planner add</h3>` +
    `<div class="decisions">${DECISIONS.map(card).join("")}</div>` +
    `<p class="impact-note">Every figure rests on ${outcome.runs} runs of four two-week windows from one spring in one city. The pairs are not added together: they were measured at different fleets. Dollar figures assume a full depot at ${outcome.rides_per_vehicle_day} rides a vehicle a day; the area would keep ${whole(outcome.area_vehicles_today[0])} to ${whole(outcome.area_vehicles_today[1])} vehicles busy today. What a vehicle costs is an assumption the account under the hood moves. ${ACCOUNT_LABEL}</p>`
  );
}
