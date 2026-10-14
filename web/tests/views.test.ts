import { describe, expect, it } from "vitest";
import { Grid } from "../src/grid";
import { run } from "../src/sim";
import { PLACE, vehicleName, type Step } from "../src/trace";
import { journey, whereabouts } from "../src/views/board";
import { outlook, outlookScore } from "../src/views/charts";

const { meta, steps } = run({ fleet: 300, chargers: 40, seed: 2 }, 2);

describe("every vehicle is named through the depot", () => {
  it("names each vehicle off the road exactly once, and none on it", () => {
    for (const step of steps) {
      const named = step.chain.filter((_, k) => k % 3 === 0);
      expect(new Set(named).size).toBe(named.length);
      expect(named.length).toBe(meta.fleet - step.on_road);
    }
  });

  it("agrees with the stalls about who is charging", () => {
    for (const step of steps) {
      for (const [, vehicle] of step.stalls) expect(whereabouts(step, vehicle).place).toBe(PLACE.charging);
    }
  });

  it("tells a visit in order: called in, charged, cleaned, back on the road", () => {
    const last = steps[steps.length - 1];
    const visited = Array.from({ length: meta.fleet }, (_, v) => v).find((v) => journey(steps, v).some((leg) => leg.place === 0));
    expect(visited).toBeDefined();
    const places = journey(steps, visited!).map((leg) => leg.place);
    const start = places.indexOf(PLACE.inbound);
    const visit = places.slice(start, places.indexOf(0, start) + 1);
    expect(visit[0]).toBe(PLACE.inbound);
    expect(visit).toContain(PLACE.charging);
    expect(visit.indexOf(PLACE.charging)).toBeLessThan(visit.indexOf(PLACE.outbound));
    expect(visit[visit.length - 1]).toBe(0);
    expect(whereabouts(last, -5).place).toBe(0);
    expect(vehicleName(11)).toBe("V-0012");
  });
});

describe("the forecast is scored against what came", () => {
  it("pairs each forecast with the rides of the hour it was about, one hour on", () => {
    // Rides differ at every step, and each step's forecast is exactly the rides of the twelve steps that begin
    // twelve steps later. Paired with any other hour, the error is not zero.
    const offered = (k: number) => 10 + ((k * 7) % 13);
    const hourFrom = (k: number) => Array.from({ length: 12 }, (_, j) => offered(k + j)).reduce((a, b) => a + b, 0);
    const made = Array.from({ length: 49 }, (_, k): Step => ({ ...steps[0], minute: k * 5, offered: offered(k), forecast: hourFrom(k + 12), forecast_upper: hourFrom(k + 12) + 1 }));
    const pairs = outlook(made);
    expect(pairs.length).toBe(3);
    expect(pairs[0].minute).toBe(60);
    expect(pairs.map((p) => p.actual)).toEqual([hourFrom(12), hourFrom(24), hourFrom(36)]);
    expect(outlookScore(pairs)).toEqual({ error: 0, held: 1 });
    // A list that has lost steps off its front is still paired by the clock, not by where the list begins.
    for (const dropped of [1, 5, 11]) {
      const later = outlook(made.slice(dropped));
      expect(later[0].minute).toBe(120);
      expect(outlookScore(later).error).toBe(0);
    }
    // The live depot stamps a step at its end: the first step of an hour reads five past.
    const live = made.map((step) => ({ ...step, minute: step.minute + 5 }));
    expect(outlookScore(outlook(live.slice(7), 5)).error).toBe(0);
    // The same forecasts an hour out of step are wrong, and the score says so.
    const shifted = made.map((step, k) => ({ ...step, forecast: hourFrom(k) }));
    expect(outlookScore(outlook(shifted)).error).toBeGreaterThan(0);
  });
});

describe("the grid week", () => {
  const week = { source: "test", week_of: "2024-04-15", step_min: 5, net_demand_mw: [10, 20, 30, 40], co2_g_per_kwh: [100, 100, 300, 300] };
  const grid = new Grid(week);

  it("runs from 0 at the easiest moment to 1 at the hardest, and wraps round the week", () => {
    expect(grid.strain(0)).toBe(0);
    expect(grid.strain(15)).toBe(1);
    expect(grid.netDemand(7 * 1440)).toBe(10);
  });

  it("weighs carbon by when the depot drew its power", () => {
    const at = (minute: number, kw: number): Step => ({ ...steps[0], minute, grid_kw: kw });
    const mark = grid.footprint([at(0, 0), at(5, 0), at(10, 1000), at(15, 1000)]);
    expect(mark.carbon).toBe(300);
    expect(mark.gridCarbon).toBe(200);
    expect(mark.hardShare).toBe(0.5);
  });
});

describe("the account on the page against the account in the record", () => {
  it("rebuilds every recorded design's contribution to the dollar at the record's own assumptions", async () => {
    const { book } = await import("../src/views/money");
    const { readFileSync } = await import("node:fs");
    const data = JSON.parse(readFileSync(new URL("../public/money.json", import.meta.url), "utf8"));
    expect(data.rows.length).toBeGreaterThan(20);
    for (const row of data.rows) {
      const choice = {
        fleet: row.fleet, feeder: row.feeder, chargers: row.chargers, control: row.control, scenario: "tariff",
        vehicleCost: data.assumptions.vehicle_cost_per_year, operations: data.assumptions.operations_per_vehicle_day, lostRide: data.assumptions.lost_ride_cost,
      };
      const { contribution } = book(row, choice as never);
      expect(Math.abs(contribution - row.contribution_per_day)).toBeLessThan(1.5);
    }
  });

  it("counts lost rides whatever a lost ride is priced at", async () => {
    const { book, lostPerDay } = await import("../src/views/money");
    const row = { fleet: 500, feeder: "one", chargers: 1, control: "plan", per_day: { revenue: 100 }, rides_per_vehicle_day: 24, rides_served_share: 0.96, rides_lost_per_day: 500 };
    expect(lostPerDay(row as never)).toBe(500);
    const free = book(row as never, { fleet: 500, scenario: "tariff", vehicleCost: 0, operations: 0, lostRide: 0 } as never);
    expect(free.lines.reliability).toBe(0);
    expect(lostPerDay({ ...row, rides_lost_per_day: undefined } as never)).toBeCloseTo((24 * 500) / 0.96 - 24 * 500, 6);
  });
});
