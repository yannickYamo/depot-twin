// The decision cards are read from outcome.json, which is built from the test records. These tests hold
// the cards to that file: each switch shows its own arm, and no figure is typed into the page.

import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { ACCOUNT_LABEL, DECISIONS, answerMarkup, impactMarkup, worthMarkup, isOutcome, money, type Outcome, type Taken } from "../src/views/impact";
import { percent, whole } from "../src/views/canvas";
import { forecastLine, forecastMarkup, forecasts } from "../src/views/models";

const outcome = JSON.parse(readFileSync(new URL("../public/outcome.json", import.meta.url), "utf8")) as Outcome;
const all = (value: boolean): Taken => ({ calling: value, power: value, plan: value, feeder: value });

test("money is written at the size a reader compares", () => {
  expect(money(84683)).toBe("$84,700");
  expect(money(40_935_845)).toBe("$40.9M");
  expect(money(585)).toBe("$585");
  expect(money(1585)).toBe("$1,590");
  expect(money(-50317)).toBe("−$50,300");
});

test("each switch shows its own measured arm", () => {
  const { calling, power } = outcome.decisions;
  const on = impactMarkup(outcome, all(true), null);
  const off = impactMarkup(outcome, all(false), null);
  expect(on).toContain(`<dd>${whole(calling.with.fleet)}</dd>`);
  expect(off).toContain(`<dd>${whole(calling.without.fleet)}</dd>`);
  expect(on).toContain(money(calling.with.contribution_per_day));
  expect(off).toContain(money(calling.without.contribution_per_day));
  expect(on).toContain(`${(100 * power.with.rides_served_share!).toFixed(1)}%`);
  expect(off).toContain(`${(100 * power.without.rides_served_share!).toFixed(1)}%`);
});

test("the decision taken is the larger depot, and one switch moves one card", () => {
  const { calling, power, plan } = outcome.decisions;
  expect(calling.with.fleet).toBeGreaterThan(calling.without.fleet);
  expect(power.with.rides_per_day).toBeGreaterThan(power.without.rides_per_day);
  expect(plan.with.energy_per_kwh!).toBeLessThan(plan.without.energy_per_kwh!);
  const mixed = impactMarkup(outcome, { ...all(false), power: true }, "power");
  expect(mixed.match(/class="decision taken/g)?.length).toBe(1);
  expect(mixed).toContain('class="decision taken watching"');
  expect(DECISIONS.length).toBe(4);
});

test("the headline is the planned fleet, with what the feeder carries as energy use moves", () => {
  const one = outcome.one_feeder;
  const html = impactMarkup(outcome, all(true), null);
  expect(html).toContain(`Plan one feeder for ${whole(one.planned.fleet)} vehicles`);
  for (const fleet of Object.values(one.carried_by_energy_use)) expect(html).toContain(`<dd>${whole(fleet)}<span class="unit">vehicles</span></dd>`);
  // The plan is no larger than what the feeder carries with more energy use, and that no larger than at the estimate.
  expect(one.planned.fleet).toBeLessThanOrEqual(one.carried_by_energy_use[String(one.margin)]);
  expect(one.carried_by_energy_use[String(one.margin)]).toBeLessThanOrEqual(one.carried_by_energy_use["1"]);
  expect(one.carried_by_energy_use["1"]).toBeLessThanOrEqual(one.carried_by_energy_use["0.9"]);
});

test("the feeder card leads with the growth the filings support and says what the faster readings are", () => {
  const { feeder } = outcome.decisions;
  const html = impactMarkup(outcome, all(false), null);
  expect(html).toContain(`${feeder.scenarios} scenarios`);
  expect(html).toContain(`${feeder.months_on_that_growth[0]} to ${feeder.months_on_that_growth[1]} months`);
  expect(html).toContain(money(feeder.a_year_late_at_base_costs_on_the_faster_growth_readings[1]));
  expect(html).toContain(money(feeder.carrying_cost_of_applying_a_year_early[1]));
  expect(feeder.carrying_cost_of_applying_a_year_early[1]).toBeLessThan(feeder.capital);
  // A saving is never printed as a loss.
  expect(html).not.toMatch(/\$−|−\$\d+,\d+ to/);
});

test("the headline says what the plan holds against, and the fleet when both unknowns go the wrong way", () => {
  const one = outcome.one_feeder;
  const html = impactMarkup(outcome, all(true), null);
  expect(one.planned_holds_with_the_parked_load).toBe(true);
  expect(html).toContain(`holds is ${whole(one.carried_in_every_fortnight_with_both)}`);
  expect(html).toContain(`gives ${whole(one.registered_rule_gives)}`);
  expect(one.carried_in_every_fortnight_with_both).toBeLessThan(one.planned.fleet);
});

test("the answer beside the tabs is the planned fleet, and the table above the account is read from the file", () => {
  const one = outcome.one_feeder;
  const { calling } = outcome.decisions;
  expect(answerMarkup(outcome)).toBe(`Plan ${whole(one.planned.fleet)}`);
  const worth = worthMarkup(outcome);
  expect(worth).toContain(`${whole(calling.with.fleet)} vehicles carried against ${whole(calling.without.fleet)}`);
  expect(worth).toContain(money(outcome.money.plan_saving_per_year_at_500));
  expect(worth).toContain(money(outcome.money.plan_saving_per_year_at_the_plan!));
  // One row a rule: the planned fleet's yearly contribution is not a row, and is not in the lead either.
  expect(worth.match(/<tr><th scope="row">/g)).toHaveLength(4);
  const yearly = money(365 * one.planned.contribution_per_day);
  expect(worth).not.toContain(yearly);
  expect(impactMarkup(outcome, all(true), null)).not.toContain(yearly);
});

test("the account says what it is wherever its dollars are shown", () => {
  expect(ACCOUNT_LABEL).toBe("It ranks designs. It isn't a profit forecast.");
  expect(worthMarkup(outcome)).toContain(ACCOUNT_LABEL);
  expect(impactMarkup(outcome, all(true), null)).toContain(ACCOUNT_LABEL);
  expect(readFileSync(new URL("../index.html", import.meta.url), "utf8")).toContain(ACCOUNT_LABEL);
});

test("the four cards keep their labels: three measured in the twin, one a scenario", () => {
  const html = impactMarkup(outcome, all(true), null);
  expect(html.match(/<article class="decision/g)).toHaveLength(4);
  expect(html.match(/Measured in the twin\./g)).toHaveLength(3);
  expect(html.match(/A scenario, not a measured pair\./g)).toHaveLength(1);
});

test("each tile gives the fleet over all runs and the fleet in every fortnight, and they differ where the plan says", () => {
  const one = outcome.one_feeder;
  const html = impactMarkup(outcome, all(true), null);
  const high = String(one.margin);
  expect(one.carried_in_every_fortnight_by_energy_use[high]).toBe(one.planned.fleet);
  expect(one.carried_in_every_fortnight_with_the_parked_load[high]).toBe(one.carried_in_every_fortnight_with_both);
  expect(html).toContain(`<small>${whole(one.carried_in_every_fortnight_with_both)} in every two-week window</small>`);
});

test("a file of the wrong shape is not taken for the outcome file", () => {
  expect(isOutcome(outcome)).toBe(true);
  expect(isOutcome({})).toBe(false);
  expect(isOutcome({ ...outcome, one_feeder: {} })).toBe(false);
  expect(isOutcome(null)).toBe(false);
});

test("the forecast block is read from the model records, and a file of the wrong shape shows nothing", () => {
  const read = (name: string): unknown => JSON.parse(readFileSync(new URL(`../public/${name}`, import.meta.url), "utf8"));
  const trust = read("trust.json") as { sf: Record<string, { error: number }>; cities: Record<string, Record<string, { error: number }>> };
  const bench = read("models.json") as { variants: Record<string, { reserve: { vehicles_held_in_reserve: number } }> };
  const backtest = read("backtest.json") as { weeks: number; series: Record<string, Record<string, { error: number }>> };
  const models = forecasts(trust, bench, backtest)!;
  expect(models).not.toBeNull();
  const html = forecastMarkup(models);
  for (const arm of ["last_week", "reference", "chronos"]) {
    expect(html).toContain(`<b>${percent(trust.sf[arm].error)}</b>`);
    expect(html).toContain(`<b>${percent(backtest.series.chicago[arm].error)}</b>`);
    expect(html).toContain(`<td>${whole(bench.variants[arm].reserve.vehicles_held_in_reserve)}</td>`);
  }
  // The trained model beats the same hour last week in every city shown, and the pretrained one beats both.
  // Chicago is the city the README quotes, and the page shows the README's figures for it, with the window named.
  const readme = readFileSync(new URL("../../README.md", import.meta.url), "utf8");
  // Held only while the README names the city: a README that leaves the comparison to docs/ML.md has no figure to disagree.
  if (readme.includes("Chicago")) for (const arm of ["last_week", "reference", "chronos"]) expect(readme).toContain(percent(backtest.series.chicago[arm].error));
  expect(html).toContain(`${backtest.weeks} weeks, refit each week`);
  expect(html).not.toContain(`<b>${percent(trust.cities.chicago.reference.error)}</b>`);
  for (const city of [trust.sf, backtest.series.chicago, backtest.series.nyc_yellow]) {
    expect(city.reference.error).toBeLessThan(city.last_week.error);
    expect(city.chronos.error).toBeLessThan(city.reference.error);
  }
  expect(bench.variants.reference.reserve.vehicles_held_in_reserve).toBeLessThan(bench.variants.last_week.reserve.vehicles_held_in_reserve);
  // The fold's one line carries the reserve both ways, and says no rides were bought only while that holds.
  const line = forecastLine(models);
  expect(line).toContain(`from ${whole(bench.variants.last_week.reserve.vehicles_held_in_reserve)} vehicles to ${whole(bench.variants.reference.reserve.vehicles_held_in_reserve)}`);
  expect(line.startsWith("A better forecast bought no rides here")).toBe(true);
  expect(forecastLine(null)).not.toMatch(/\d/);
  expect(impactMarkup(outcome, all(true), null, models)).toContain("What the forecasts add");
  expect(impactMarkup(outcome, all(true), null)).not.toContain("What the forecasts add");
  expect(forecasts({}, bench, backtest)).toBeNull();
  expect(forecasts(trust, { variants: {} }, backtest)).toBeNull();
  expect(forecasts(trust, bench, { ...backtest, hours_ahead: 24 })).toBeNull();
  expect(forecasts(trust, bench, {})).toBeNull();
});
