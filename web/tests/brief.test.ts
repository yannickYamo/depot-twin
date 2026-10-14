import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CASES, IDEA, briefMarkup, carried, carriedView, unknownsMarkup, type Unknowns } from "../src/views/brief";
import { isOutcome, type Outcome } from "../src/views/impact";
import { percent, whole } from "../src/views/canvas";

const loaded: unknown = JSON.parse(readFileSync(new URL("../public/outcome.json", import.meta.url), "utf8"));
if (!isOutcome(loaded)) throw new Error("outcome.json has the wrong shape");
const outcome: Outcome = loaded;
const one = outcome.one_feeder;
const page = briefMarkup(outcome, { road: "1", parked: false });
/** What a reader reads: the markup with its tags taken out. */
const words = (html: string): string => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

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

  it("says the plan holds against either unknown alone and not against both", () => {
    const holds = (pick: Unknowns): boolean => unknownsMarkup(outcome, pick).includes(`The plan of ${whole(one.planned.fleet)} vehicles holds.`);
    expect(holds({ road: "0.9", parked: false })).toBe(true);
    expect(holds({ road: "1", parked: false })).toBe(true);
    expect(holds({ road: "1.1", parked: false })).toBe(true);
    expect(holds({ road: "1.1", parked: true })).toBe(false);
    const both = carriedView(outcome, { road: "1.1", parked: true })!;
    expect(both.verdict).toContain(`${whole(one.carried_in_every_fortnight_with_both)} vehicles hold.`);
    expect(both.kind).toBe("short");
  });

  it("has six beats, each with one heading, and exactly one control group", () => {
    expect(page.match(/<section class="beat/g)).toHaveLength(6);
    expect(page.match(/<h2>/g)).toHaveLength(6);
    expect(page.match(/role="radiogroup"/g)).toHaveLength(1);
    expect(page).not.toMatch(/<(input|select|textarea)/);
    // Every choice of the one control is a measured case, and one of them is chosen.
    expect(page.match(/role="radio"/g)).toHaveLength(CASES.length);
    expect(page.match(/aria-checked="true"/g)).toHaveLength(1);
    // Past the control, one button opens the twin and two links leave the page.
    expect(page.match(/<button type="button" class="watch"/g)).toHaveLength(1);
    expect(page).toContain(">Explore the depot</button>");
    expect(page).toContain('href="readme.html">Decisions and trade-offs</a>');
    expect(page).toContain('docs/SITES.md">Plan your own site</a>');
  });

  it("reads in under 350 words, with no sentence over 25", () => {
    const text = words(page);
    expect(text.split(" ").length).toBeLessThan(350);
    const prose = [...page.matchAll(/<(h2|p|li)[^>]*>(.*?)<\/\1>/g)].map((found) => words(found[2]));
    for (const sentence of prose.flatMap((block) => block.split(/(?<=[.?!])\s+/))) {
      expect(sentence.split(" ").length, sentence).toBeLessThanOrEqual(25);
    }
  });

  it("leads the answer with the idea, the plan and three figures", () => {
    const { calling } = outcome.decisions;
    const answer = page.split('<section class="beat')[2];
    expect(answer).toContain(`${IDEA} <b>On this parcel: plan for ${whole(one.planned.fleet)}.</b>`);
    expect(answer.match(/<dt>/g)).toHaveLength(3);
    expect(answer.match(/<dd>/g)).toHaveLength(3);
    expect(answer).toContain(`<dd>${whole(one.planned.fleet)}</dd>`);
    expect(answer).toContain(`<dd>${whole(one.carried_by_energy_use["1"]!)}</dd>`);
    expect(answer).toContain(`<dd>+${whole(calling.with.fleet - calling.without.fleet)}</dd>`);
    expect(answer).toContain(`one rule is worth ${whole(calling.with.fleet - calling.without.fleet)} vehicles`);
    expect(page).not.toContain("cliff");
  });

  it("shows one rule, and what the plan saves at both fleets from the record", () => {
    const { plan, calling } = outcome.decisions;
    expect(page).not.toContain("power rule");
    expect(page).toContain(`carries ${whole(calling.with.fleet)} vehicles with it and ${whole(calling.without.fleet)} without.`);
    expect(page).toContain(`At ${whole(plan.with.fleet)} vehicles the schedule buys energy ${percent(plan.energy_saving)} cheaper.`);
    expect(page).toContain(`At the planned ${whole(one.planned.fleet)}, ${percent(plan.energy_saving_at_the_planned_fleet)} is left to save.`);
    expect(plan.energy_saving_at_the_planned_fleet).toBeLessThan(plan.energy_saving);
  });

  it("carries no dollar figure and types in no figure of its own", () => {
    expect(page).not.toContain("$");
    expect(words(page)).not.toMatch(/profit|earn|dollar/i);
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
});
