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
    expect(beats.map((b) => b.split('"')[0].trim())).toEqual(["beat-where", "beat-answer", "beat-rule", "beat-feeder", "beat-meter", "beat-ml", "last beat-next"]);
    expect(page.match(/role="radiogroup"/g)).toHaveLength(1);
    expect(page).not.toMatch(/<(input|select|textarea)/);
    expect(page.match(/role="radio"/g)).toHaveLength(CASES.length);
    expect(page.match(/aria-checked="true"/g)).toHaveLength(1);
    expect(page.match(/<button type="button" class="watch"/g)).toHaveLength(1);
    expect(page).toContain(">Explore the depot</button>");
    expect(page).toContain('href="readme.html">Decisions and trade-offs</a>');
    expect(page).toContain('docs/SITES.md">Plan your own site</a>');
  });

  it("reads in about a minute and a half: under 380 words of prose and 620 in all, no sentence over 28, and never says fortnight", () => {
    const text = words(page);
    expect(text.split(" ").length).toBeLessThan(620);
    // The prose a reader reads straight through: headings, paragraphs and list items, not the figures' captions.
    const read = [...page.matchAll(/<(h2|p|li)[^>]*>(.*?)<\/\1>/g)].filter((m) => !/bf-small|bf-cap/.test(m[0])).map((m) => words(m[2]).split(" ").length).reduce((a, b) => a + b, 0);
    expect(read).toBeLessThan(380);
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

  it("states the plan with the energy budget behind it and the mix it rests on, from the records", () => {
    const b = outcome.budget;
    const answer = words(beats[1]!);
    expect(answer).toContain(`Plan one feeder for ${whole(one.planned.fleet)} vehicles, ${whole(one.planned.rides_per_day)} rides a day.`);
    expect(answer).toContain(`${(b.usable_kwh_a_day / 1000).toFixed(1)} MWh a day over about ${whole(Math.round(b.feeder_kwh_per_vehicle_day))} kWh a vehicle, my estimate, is ${whole(b.fleet_by_arithmetic)}; the simulated depot carries ${whole(b.carried)}.`);
    expect(b.fleet_by_arithmetic).toBe(Math.round(b.usable_kwh_a_day / b.feeder_kwh_per_vehicle_day));
    expect(answer).toContain(`${whole(one.planned.fleet)} still holds in all four two-week windows`);
    // The smallest share of Ojai at which the plan holds with more energy use, and what all I-PACE carries.
    const shares = outcome.fleet_mix!.shares;
    const from = shares.find((row) => row.carried_with_more_energy! >= one.planned.fleet)!;
    const ipace = shares.find((row) => row.share_ojai === 0)!;
    expect(ipace.carried_with_more_energy).toBeLessThan(one.planned.fleet);
    expect(answer).toContain(`with at least ${Math.round(100 * from.share_ojai)}% of the fleet Ojai as I assume. All I-PACE: ${whole(ipace.carried_with_more_energy!)}.`);
  });

  it("prices the rule, the feeder and the meter from the account, and draws the fleet carried by mix", () => {
    const { calling, feeder } = outcome.decisions;
    const cash = outcome.money;
    expect(beats[2]).toContain(`worth ${whole(calling.with.fleet - calling.without.fleet)} vehicles, ${whole(calling.with.rides_per_day - calling.without.rides_per_day)} rides and ${money(cash.calling_rule_per_year)} a year`);
    expect(cash.calling_rule_per_year).toBe(Math.round((calling.with.contribution_per_day - calling.without.contribution_per_day) * 365));
    expect(beats[2]).toContain(`one feeder carries ${whole(calling.with.fleet)} vehicles with the rule and ${whole(calling.without.fleet)} without`);
    // The feeder's headline carries the lead time its figure rests on.
    const longest = Math.max(...feeder.lead_months);
    expect(beats[3]).toContain(`If the utility takes four years, a year late forgoes up to ${money(feeder.a_year_late_on_that_growth_by_lead[String(longest)]![1])}.`);
    expect(longest).toBe(48);
    const [early, earlyHigh] = feeder.carrying_cost_of_applying_a_year_early;
    expect(beats[3]).toContain(`A year early costs ${money(early)} to ${money(earlyHigh)}.`);
    expect(beats[4]).toContain(`decides ${whole(cash.metering_span_vehicles)} vehicles, about ${money(cash.metering_span_per_year)} a year`);
    // The meter's chart is the span it settles: the estimate against both unknowns, each in every window.
    expect(words(beats[4]!)).toContain(`As estimated ${whole(one.carried_in_every_fortnight_by_energy_use["1"]!)} 10% more, systems on while parked ${whole(one.carried_in_every_fortnight_with_both)}`);
    expect(cash.metering_span_vehicles).toBe(one.carried_by_energy_use["1"]! - one.carried_in_every_fortnight_with_both);
    const on = outcome.fleet_mix!.always_on_kw;
    expect(beats[4]).toContain(`${on.low} to ${on.high} kW of it moves the fleet from ${whole(on.carried_low!)} to ${whole(on.carried_high!)}`);
    // The mix chart sits with the plan: at 10% more, by share of Ojai, short of the plan only where the fleet is.
    for (const row of outcome.fleet_mix!.shares) {
      const name = row.share_ojai === 0 ? "No Ojai" : row.share_ojai === 1 ? "All Ojai" : `${Math.round(100 * row.share_ojai)}% Ojai`;
      const kind = row.carried_with_more_energy! >= one.planned.fleet ? "with" : "short";
      expect(beats[1]).toMatch(new RegExp(`<span>${name}</span><span class="bf-track"><i class="${kind}"[^>]*></i></span><b>${whole(row.carried_with_more_energy!)}</b>`));
    }
    expect(page).not.toContain("I-PACE</span>");
    expect(page).not.toContain("power rule");
  });

  it("says what the plan buys at the planned fleet, that the next study gives the forecast a job, and keeps the money below the decisions", () => {
    const { plan } = outcome.decisions;
    const cash = outcome.money;
    const ml = words(beats[5]!);
    expect(ml).toContain(`about ${money(cash.plan_saving_per_year_at_the_plan!)} a year at ${whole(one.planned.fleet)}, not more vehicles`);
    expect(ml).toContain("solar, a battery and paid grid events");
    expect(ml).toContain("a forecast of rides, sun and price should earn its place");
    expect(plan.with.fleet).toBe(500);
    const last = beats[6]!;
    expect(last).toContain(`${money(one.planned.contribution_per_day)} a day after costs, ${money(cash.planned_per_year)} a year`);
    expect(cash.planned_per_year).toBe(Math.round(one.planned.contribution_per_day * 365));
    expect(last).toContain("It ranks designs. It isn't a profit forecast.");
    expect(last).toContain(IDEA);
  });

  it("says which way the plan and the clock-aware threshold differ at 500, by the sign of the record", () => {
    const base = { plan_with_prices_at_500_per_kwh: 0.17, clock_aware_threshold_that_waits_at_500_per_kwh: 0.16, quota_at_ceiling_share_at_500: 0.95, clock_aware_threshold_that_waits_at_500_served: 0.99, beats_the_clock_aware_threshold: false, decides_in_a_quarter_of_hours: false };
    const dearer = words(briefMarkup({ ...outcome, program: { ...base, saving_over_the_clock_aware_threshold_that_waits: -0.09 } }, OPENING));
    expect(dearer).toContain("At 500 vehicles a rule that knows only the clock buys 8.3% cheaper still, at 99.0% of rides.");
    const cheaper = words(briefMarkup({ ...outcome, program: { ...base, saving_over_the_clock_aware_threshold_that_waits: 0.05 } }, OPENING));
    expect(cheaper).toContain("At 500 vehicles the plan buys energy 5.0% cheaper than a rule that knows only the clock.");
    const level = words(briefMarkup({ ...outcome, program: { ...base, saving_over_the_clock_aware_threshold_that_waits: 0 } }, OPENING));
    expect(level).toContain("At 500 vehicles a rule that knows only the clock buys energy at the plan's price.");
    // On the record: the clock rule is cheaper than the plan by 1 - its price over the plan's.
    const p = outcome.program!;
    expect(words(page)).toContain(`buys ${percent(1 - p.clock_aware_threshold_that_waits_at_500_per_kwh! / p.plan_with_prices_at_500_per_kwh!)} cheaper still`);
  });

  it("states what two feeders carry and that faster chargers carry no more, from E33 and E34", () => {
    const chargers = outcome.chargers!;
    const slow = chargers.designs.find((row) => row.name === "all_60")!;
    const fast = chargers.designs.find((row) => row.name === "all_150")!;
    const more = Math.round((365 * (fast.charger_cost_per_day_on_1 - slow.charger_cost_per_day_on_1)) / 1000) * 1000;
    const rule = words(beats[2]!);
    const feeder = words(beats[3]!);
    expect(fast.carried_on_1).toBe(slow.carried_on_1);
    expect(rule).toContain(`150 kW chargers carry the same ${whole(slow.carried_on_1!)} as 60 kW, for ${money(more)} a year more.`);
    expect(feeder).toContain(`Two feeders carry ${whole(chargers.planned_on_two_feeders!)} with the same 10% margin.`);
    expect(chargers.planned_on_two_feeders).toBe(2 * one.planned.fleet);
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
  it("says how the forecast is used and how far off it is, naming the city", () => {
    const ml = words(beats.find((beat) => beat.startsWith(' beat-ml'))!);
    expect(ml).toContain("The forecast sets the hourly plan that calls vehicles in");
    expect(ml).toContain(`misses San Francisco rides by ${percent(scores.sf.reference.error)} an hour ahead, against ${percent(scores.sf.last_week.error)}`);
    expect(words(briefMarkup(outcome, OPENING))).not.toContain("misses San Francisco rides");
  });
});
