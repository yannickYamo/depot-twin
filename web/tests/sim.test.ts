import { describe, expect, it } from "vitest";
import reference from "./reference.json";
import { run, summarize, type PowerRule } from "../src/sim";
import { problems } from "../src/trace";

// The Python simulator is the reference. tests/reference.json holds its numbers for the East Oakland depot on
// one feeder, written by web/scripts/reference.py: both simulators set up alike (weekly shape, a fixed
// threshold, seven days less the first) and measured alike (rides served, arrivals a vehicle-day, grid kWh a
// vehicle-day), each the mean of three seeds. The browser simulator is a separate implementation with its
// own random numbers, so what is left between them is the two implementations and seed noise.
const POLICY: Record<PowerRule, "slot_power" | "need_first"> = { in_order: "slot_power", emptiest_first: "need_first" };
const CHARGERS = { 500: 66, 1000: 132 } as const;
const SEEDS = [1, 2, 3];
const CASES = {
  "": { callBelow: 0.2, cleanEvery: 1, legMin: 15 },
  _cadence: { callBelow: 0.55, cleanEvery: 4, legMin: 8 },
  _few_people: { callBelow: 0.2, cleanEvery: 1, legMin: 15, staff: 4 },
  _waits: { callBelow: 0.55, cleanEvery: 4, legMin: 8, recall: "threshold_waits" },
} as const;
// Half a point where the depot serves every ride, a point and a half where it is losing some (short of
// energy, of people, or of power fed to the emptiest first) and seeds spread.
const ridesTolerance = (reference: number) => (reference >= 0.999 ? 0.005 : 0.015);

const memo = new Map<string, ReturnType<typeof summarize>>();
function browser(fleet: 500 | 1000, powerRule: PowerRule, setting: keyof typeof CASES = "") {
  const key = `${fleet}_${powerRule}${setting}`;
  if (!memo.has(key)) {
    const runs = SEEDS.map((seed) =>
      summarize(run({ fleet, chargers: CHARGERS[fleet], siteKw: 2750, recall: "threshold" as const, powerRule, ...CASES[setting], seed }, 7).steps, fleet));
    const mean = (pick: (r: (typeof runs)[number]) => number) => runs.reduce((sum, r) => sum + pick(r), 0) / runs.length;
    memo.set(key, {
      ridesServedShare: mean((r) => r.ridesServedShare),
      onRoadWhenBusiest: mean((r) => r.onRoadWhenBusiest),
      visitsPerVehicleDay: mean((r) => r.visitsPerVehicleDay),
      gridKwhPerVehicleDay: mean((r) => r.gridKwhPerVehicleDay),
      queueMean: mean((r) => r.queueMean),
    });
  }
  return memo.get(key)!;
}

describe("the browser simulator against the Python simulator", () => {
  for (const setting of ["", "_cadence", "_few_people", "_waits"] as const) {
    for (const fleet of [500, 1000] as const) {
      for (const powerRule of ["in_order", "emptiest_first"] as const) {
        it(`${fleet} vehicles, power ${powerRule.replace("_", " ")}${setting === "_cadence" ? ", at the filings' cadence" : setting === "_few_people" ? ", with four people" : setting === "_waits" ? ", waiting for a free charger" : ""}`, () => {
          const mine = browser(fleet, powerRule, setting);
          const theirs = (reference as unknown as Record<string, { rides_served_share: number; visits_per_vehicle_day: number; grid_kwh_per_vehicle_day: number }>)[`${fleet}_${POLICY[powerRule]}${setting}`];
          expect(Math.abs(mine.ridesServedShare - theirs.rides_served_share)).toBeLessThan(ridesTolerance(theirs.rides_served_share));
          expect(Math.abs(mine.visitsPerVehicleDay - theirs.visits_per_vehicle_day)).toBeLessThan(0.05);
          expect(Math.abs(mine.gridKwhPerVehicleDay / theirs.grid_kwh_per_vehicle_day - 1)).toBeLessThan(0.02);
        });
      }
    }
  }

  it("agrees on the headline: feeding in order serves more rides when power is short", () => {
    const gain = browser(1000, "in_order").ridesServedShare - browser(1000, "emptiest_first").ridesServedShare;
    const theirs = reference["1000_slot_power"].rides_served_share - reference["1000_need_first"].rides_served_share;
    expect(theirs).toBeGreaterThan(0.03);
    expect(Math.abs(gain - theirs)).toBeLessThan(0.02);
  });

  it("and that it makes little difference when power is plentiful", () => {
    const gap = Math.abs(browser(500, "in_order").ridesServedShare - browser(500, "emptiest_first").ridesServedShare);
    expect(gap).toBeLessThan(0.01);
  });

  it("is repeatable from a seed", () => {
    const a = run({ fleet: 200, chargers: 26, seed: 5 }, 1).steps.map((s) => s.on_road);
    const b = run({ fleet: 200, chargers: 26, seed: 5 }, 1).steps.map((s) => s.on_road);
    expect(a).toEqual(b);
  });

  // The staffing study (EVALS.md): the gain from in-order feeding shrinks with more people, because the
  // loss under "emptiest first" is full vehicles waiting on chargers to be unplugged.
  it("agrees on why: more people narrow the gap, and in-order feeding does not need them", () => {
    const served = (powerRule: PowerRule, staff: number) => {
      const { steps } = run({ fleet: 1000, chargers: 132, siteKw: 2750, powerRule, staff, callBelow: 0.2, cleanEvery: 1, seed: 1 }, 7);
      return summarize(steps, 1000).ridesServedShare;
    };
    const few = served("in_order", 25) - served("emptiest_first", 25);
    const many = served("in_order", 100) - served("emptiest_first", 100);
    expect(many).toBeLessThan(few);
    expect(many).toBeGreaterThan(0);
    expect(Math.abs(served("in_order", 25) - served("in_order", 100))).toBeLessThan(0.005);
  });

  it("keeps every vehicle accounted for under the slot rule", () => {
    const { meta, steps } = run({ fleet: 400, chargers: 52, recall: "slots", slotMin: 45, seed: 3 }, 3);
    expect(problems(meta, steps)).toEqual([]);
    expect(summarize(steps, 400).ridesServedShare).toBeGreaterThan(0.9);
  });
});

describe("the invariants both implementations must satisfy, not only agree on", () => {
  it("offers two depots with the same seed the same rides, whatever their rules do with the vehicles", () => {
    const pairs: [Partial<Parameters<typeof run>[0]>, Partial<Parameters<typeof run>[0]>][] = [
      [{ fleet: 650, recall: "threshold_waits" }, { fleet: 650, recall: "threshold" }],
      [{ fleet: 1000, powerRule: "in_order" }, { fleet: 1000, powerRule: "emptiest_first" }],
      [{ fleet: 1000, siteKw: 5500 }, { fleet: 1000, siteKw: 2750 }],
    ];
    for (const [one, other] of pairs) {
      const a = run({ ...one, seed: 7 }, 3).steps.map((s) => s.offered);
      const b = run({ ...other, seed: 7 }, 3).steps.map((s) => s.offered);
      expect(a).toEqual(b);
      expect(a.reduce((x, y) => x + y, 0)).toBeGreaterThan(0);
    }
  });

  it("busy shares add up to the served rides' minutes and no vehicle exceeds a step", async () => {
    const { busyShares } = await import("../src/sim");
    const weights = Array.from({ length: 50 }, (_, k) => 0.5 + ((k * 37) % 11) / 10);
    for (const total of [3, 45, 49.9, 50]) {
      const shares = busyShares(total, weights);
      expect(shares.reduce((a, b) => a + b, 0)).toBeCloseTo(total, 6);
      expect(Math.max(...shares)).toBeLessThanOrEqual(1);
      expect(Math.min(...shares)).toBeGreaterThanOrEqual(0);
    }
    expect(busyShares(80, weights).reduce((a, b) => a + b, 0)).toBeCloseTo(50, 6);
    // A vehicle low on energy takes only the share of a step its battery covers; the rest goes to the others.
    const capped = busyShares(2, [1, 1, 1, 1], [1, 1, 0.25, 0]);
    expect(capped.map((v) => Math.round(v * 1000) / 1000)).toEqual([0.875, 0.875, 0.25, 0]);
    expect(busyShares(5, [1, 1, 1, 1], [1, 1, 0.25, 0]).reduce((a, b) => a + b, 0)).toBeCloseTo(2.25, 6);
  });

  it("cleans the same physical vehicle on every Nth of its own visits", () => {
    // Short, frequent visits so that cleaning cadence shows: the bays' use halves from every visit to every second.
    const bays = (cleanEvery: number) => {
      const { steps } = run({ fleet: 200, chargers: 26, callBelow: 0.55, cleanEvery, seed: 4 }, 3);
      return steps.reduce((sum, s) => sum + s.cleaning, 0);
    };
    const every = bays(1);
    const second = bays(2);
    const fourth = bays(4);
    expect(second / every).toBeGreaterThan(0.35);
    expect(second / every).toBeLessThan(0.65);
    expect(fourth / every).toBeGreaterThan(0.1);
    expect(fourth / every).toBeLessThan(0.4);
    expect(second).not.toBe(fourth);
  });
});

describe("the fleet by vehicle type", () => {
  const counted = async (params: Parameters<typeof run>[0], days: number) => {
    const { DepotSim } = await import("../src/sim");
    const sim = new DepotSim(params);
    const steps = Array.from({ length: (days * 1440) / 5 }, () => sim.step());
    return { types: sim.byType(), steps };
  };

  it("builds the fleet from the share asked for, and the assumed 60/40 when none is", async () => {
    const all = (share: number) => counted({ fleet: 300, ojaiShare: share, seed: 3 }, 1).then((r) => r.types.map((t) => t.vehicles));
    expect(await all(0)).toEqual([300, 0]);
    expect(await all(1)).toEqual([0, 300]);
    const [ipace, ojai] = await all(0.4);
    expect(ipace + ojai).toBe(300);
    expect(ojai / 300).toBeGreaterThan(0.3);
    expect(ojai / 300).toBeLessThan(0.5);
    // The default is the assumed mix, drawn the same way: a run with it set reads exactly as one without.
    expect(run({ fleet: 300, ojaiShare: 0.4, seed: 3 }, 2).steps).toEqual(run({ fleet: 300, seed: 3 }, 2).steps);
  });

  it("takes less from the grid with more of the type that uses less energy, with power to spare", () => {
    const grid = (share: number) => summarize(run({ fleet: 400, siteKw: 5500, chargers: 120, ojaiShare: share, seed: 5 }, 4).steps, 400).gridKwhPerVehicleDay;
    expect(grid(1)).toBeLessThan(grid(0.4));
    expect(grid(0.4)).toBeLessThan(grid(0));
  });

  it("counts every arrival after the first day once, under the type of the vehicle that made it", async () => {
    const { types, steps } = await counted({ fleet: 300, chargers: 60, seed: 9 }, 3);
    const arrivals = steps.filter((s) => s.minute > 1440).reduce((sum, s) => sum + s.arrivals, 0);
    const visits = types.reduce((sum, t) => sum + t.visitsPerVehicleDay * t.vehicles * 2, 0);
    expect(visits).toBeCloseTo(arrivals, 6);
    for (const t of types) {
      // Over whole days the hourly chances add up to the visits a vehicle-day; each is a chance, so at most one.
      expect(t.arrivalChanceByHour.reduce((a, b) => a + b, 0)).toBeCloseTo(t.visitsPerVehicleDay, 9);
      expect(Math.max(...t.arrivalChanceByHour)).toBeLessThanOrEqual(1);
      expect(t.minutesOnCharger).not.toBeNull();
      expect(t.kwhPerVisit).toBeGreaterThan(0);
    }
  });
});
