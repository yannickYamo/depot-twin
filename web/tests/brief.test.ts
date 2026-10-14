import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CASES, IDEA, OPENING, briefMarkup, carried, carriedView, unknownsMarkup, type Unknowns } from "../src/views/brief";
import { isOutcome, money, type Outcome } from "../src/views/impact";
import { percent, whole } from "../src/views/canvas";
import { forecasts } from "../src/views/models";

const loaded: unknown = JSON.parse(readFileSync(new URL("../public/outcome.json", import.meta.url), "utf8"));
if (!isOutcome(loaded)) throw new Error("outcome.json has the wrong shape");
const outcome: Outcome = loaded;
const one = outcome.one_feeder;
const read = (file: string): unknown => JSON.parse(readFileSync(new URL(`../public/${file}`, import.meta.url), "utf8"));
const scores = forecasts(read("trust.json"), read("models.json"), read("backtest.json"));
if (!scores) throw new Error("the forecast files have the wrong shape");
const page = briefMarkup(outcome, OPENING, scores);
/** What a reader reads: the markup with its tags taken out. */
const words = (html: string): string => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const beats = page.split('<section class="beat').slice(1);

describe("the short version", () => {
  it("shows only measured cases, each equal to its record", () => {
    for (const { pick } of CASES) {
      const record = pick.parked
        ? { all: one.carried_with_the_parked_load[pick.road], every: one.carried_in_every_fortnight_with_the_parked_load[pick.road] }
        : { all: one.carried_by_energy_use[pick.road], every: one.carried_in_every_fortnight_by_energy_use[pick.road] };
      expect(carried(outcome, pick)).toEqual(record);
      expect(carriedView(outcome, pick)!.figure).toBe(whole(record.every!));
      expect(unknownsMarkup(outcome, pick)).toContain(`<b class="bf-now">${whole(record.every!)}</b>`);
    }
    // A case that was not run is not a case: there is no fleet to show for it.
    expect(carried(outcome, { road: "0.9", parked: true })).toBeNull();
    expect(carriedView(outcome, { road: "0.9", parked: true })).toBeNull();
  });

  it("opens on the case the plan is sized for, and says the plan holds against either unknown alone and not against both", () => {
    expect(OPENING).toEqual({ road: "1.1", parked: false });
    const holds = (pick: Unknowns): boolean => unknownsMarkup(outcome, pick).includes(`The plan of ${whole(one.planned.fleet)} vehicles holds.`);
    expect(holds({ road: "0.9", parked: false })).toBe(true);
    expect(holds({ road: "1", parked: false })).toBe(true);
    expect(holds({ road: "1.1", parked: false })).toBe(true);
    expect(holds({ road: "1.1", parked: true })).toBe(false);
    const both = carriedView(outcome, { road: "1.1", parked: true })!;
    expect(both.verdict).toContain(`${whole(one.carried_in_every_fortnight_with_both)} vehicles hold.`);
    expect(both.kind).toBe("short");
  });

  it("has seven beats in order, each with one heading, and exactly one control group", () => {
    expect(beats).toHaveLength(7);
    expect(page.match(/<h2>/g)).toHaveLength(7);
    expect(beats.map((b) => b.split('"')[0].trim())).toEqual(["beat-where", "beat-budget", "beat-answer", "beat-rule", "beat-ml", "beat-money", "last beat-next"]);
    expect(page.match(/role="radiogroup"/g)).toHaveLength(1);
    expect(page).not.toMatch(/<(input|select|textarea)/);
    expect(page.match(/role="radio"/g)).toHaveLength(CASES.length);
    expect(page.match(/aria-checked="true"/g)).toHaveLength(1);
    expect(page.match(/<button type="button" class="watch"/g)).toHaveLength(1);
    expect(page).toContain(">Explore the depot</button>");
    expect(page).toContain('href="readme.html">Decisions and trade-offs</a>');
    expect(page).toContain('docs/SITES.md">Plan your own site</a>');
  });

  it("reads in under 400 words of prose and 660 in all, with no sentence over 28, and never says fortnight", () => {
    const text = words(page);
    expect(text.split(" ").length).toBeLessThan(660);
    // The prose a reader reads straight through: headings, paragraphs and list items, not the figures' captions.
    const read = [...page.matchAll(/<(h2|p|li)[^>]*>(.*?)<\/\1>/g)].filter((m) => !/bf-small|bf-cap/.test(m[0])).map((m) => words(m[2]).split(" ").length).reduce((a, b) => a + b, 0);
    expect(read).toBeLessThan(400);
    expect(text).not.toMatch(/fortnight/i);
    const prose = [...page.matchAll(/<(h2|p|li|dd)[^>]*>(.*?)<\/\1>/g)].map((found) => words(found[2]));
    for (const sentence of prose.flatMap((block) => block.split(/(?<=[.?!])\s+/))) {
      expect(sentence.split(" ").length, sentence).toBeLessThanOrEqual(28);
    }
  });

  it("names the place and the feeder first, from the site record", () => {
    const where = beats[0]!;
    expect(where).toContain(outcome.site.address);
    expect(where).toContain(`${(outcome.site.feeder_kw / 1000).toFixed(2)} MW`);
    expect(where).toContain(`${whole(outcome.site.feeder_kv)} kV`);
    expect(where).toContain("not a connection offer");
  });

  it("draws the energy budget as one division, from the record", () => {
    const b = outcome.budget;
    const budget = beats[1]!;
    expect(budget).toContain(`${(b.usable_kwh_a_day / 1000).toFixed(1)} MWh a day`);
    expect(budget).toContain(`${whole(Math.round(b.feeder_kwh_per_vehicle_day))} kWh`);
    expect(budget).toContain(`${whole(b.fleet_by_arithmetic)} vehicles by arithmetic`);
    expect(budget).toContain(`${whole(b.carried)} in the simulated depot`);
    expect(b.fleet_by_arithmetic).toBe(Math.round(b.usable_kwh_a_day / b.feeder_kwh_per_vehicle_day));
    expect(budget).toContain("no public source");
  });

  it("leads the answer with the idea, the plan, and why it is below the fleet carried", () => {
    const answer = beats[2]!;
    expect(answer).toContain(`${IDEA} <b>On this parcel: plan one feeder for ${whole(one.planned.fleet)} vehicles, ${whole(one.planned.rides_per_day)} rides a day.</b>`);
    expect(answer).toContain(`${whole(one.planned.fleet)} still holds in all four two-week windows`);
    expect(answer).toContain(`gives ${whole(one.registered_rule_gives)}`);
    expect(one.planned.fleet).toBeLessThanOrEqual(one.registered_rule_gives);
  });

  it("prices the rule and the plan from the account, and says what the plan does at the planned fleet", () => {
    const { plan, calling } = outcome.decisions;
    const cash = outcome.money;
    expect(beats[3]).toContain(`worth ${whole(calling.with.fleet - calling.without.fleet)} vehicles, ${whole(calling.with.rides_per_day - calling.without.rides_per_day)} rides and ${money(cash.calling_rule_per_year)} a year`);
    expect(cash.calling_rule_per_year).toBe(Math.round((calling.with.contribution_per_day - calling.without.contribution_per_day) * 365));
    expect(beats[3]).toContain(`carries ${whole(calling.with.fleet)} vehicles with the rule and ${whole(calling.without.fleet)} without`);
    expect(beats[4]).toContain(`buy energy ${percent(plan.energy_saving_at_the_planned_fleet)} cheaper there, and ${percent(plan.energy_saving)} cheaper at ${whole(plan.with.fleet)}`);
    expect(beats[4]).toMatch(/runs the planned fleet|the plan keeps the fleet/);
    expect(beats[5]).toContain(`${money(one.planned.contribution_per_day)} a day after costs, ${money(cash.planned_per_year)} a year`);
    expect(cash.planned_per_year).toBe(Math.round(one.planned.contribution_per_day * 365));
    expect(beats[5]).toContain("It ranks designs. It isn't a profit forecast.");
    expect(beats[6]).toContain(`${whole(cash.metering_span_vehicles)} vehicles between ${whole(one.carried_in_every_fortnight_with_both)} and ${whole(one.carried_by_energy_use["1"]!)}`);
    expect(cash.metering_span_vehicles).toBe(one.carried_by_energy_use["1"]! - one.carried_in_every_fortnight_with_both);
    expect(page).not.toContain("power rule");
  });

  it("says which way the hourly program and the clock-aware threshold differ, by the sign of the record", () => {
    const base = { plan_with_prices_at_500_per_kwh: 0.17, clock_aware_threshold_that_waits_at_500_per_kwh: 0.16, quota_at_ceiling_share_at_500: 0.95, clock_aware_threshold_that_waits_at_500_served: 0.99, beats_the_clock_aware_threshold: false, decides_in_a_quarter_of_hours: false };
    const dearer = words(briefMarkup({ ...outcome, program: { ...base, saving_over_the_clock_aware_threshold_that_waits: -0.09 } }, OPENING));
    expect(dearer).toContain("In the energy-price test at 500 a clock-aware threshold that waits buys 8.3% cheaper still, at 99.0% of rides.");
    const cheaper = words(briefMarkup({ ...outcome, program: { ...base, saving_over_the_clock_aware_threshold_that_waits: 0.05 } }, OPENING));
    expect(cheaper).toContain("In the energy-price test at 500 it buys energy 5.0% cheaper than a clock-aware threshold that waits.");
    expect(cheaper).not.toContain("comes within");
  });

  it("types in no figure of its own", () => {
    const source = readFileSync(new URL("../src/views/brief.ts", import.meta.url), "utf8");
    // The only digits written in the source are the 10% of the cases, the 99% of the service floor, and layout.
    const typed = source.split("\n").filter((line) => !line.trim().startsWith("//")).join("\n").replace(/\$\{[^}]*\}/g, "").match(/>[^<`]*\d{3,}[^<`]*</g);
    expect(typed).toBeNull();
  });
});

describe("the full twin", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

  it("has exactly three tabs, and three folded parts under the hood", () => {
    const tabs = [...html.matchAll(/role="tab"[^>]*>([^<]+)</g)].map((found) => found[1]);
    expect(tabs).toEqual(["Depot", "Decisions", "Under the hood"]);
    expect(html.match(/<details class="fold hood-part"/g)).toHaveLength(3);
    expect(html).not.toMatch(/<details class="fold hood-part"[^>]* open/);
  });

  it("keeps the line that says whose work this is", () => {
    expect(html).toContain("An independent project built on public data. Not affiliated with or endorsed by Waymo.");
  });
  it("says how the forecast is used and how far off it is, from its held-out days", () => {
    const ml = words(beats.find((beat) => beat.startsWith(' beat-ml'))!);
    expect(ml).toContain("The forecast sets the hourly plan that calls vehicles in.");
    expect(ml).toContain(`misses rides by ${percent(scores.sf.reference.error)} on ${whole(scores.holdout_days)} held-out days, against ${percent(scores.sf.last_week.error)}`);
    expect(words(briefMarkup(outcome, OPENING))).not.toContain("held-out days");
  });
});
