import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { run } from "../src/sim";
import { COLUMNS, TRACE_VERSION, problems, unpack, type TraceFile } from "../src/trace";

const sample = JSON.parse(readFileSync(new URL("../public/traces/sample.json", import.meta.url), "utf8")) as TraceFile;

describe("the trace contract", () => {
  it("a trace recorded by the Python simulator is in the shape this viewer expects", () => {
    expect(sample.version).toBe(TRACE_VERSION);
    expect(Object.keys(sample.steps).sort()).toEqual([...COLUMNS].sort());
    const steps = unpack(sample);
    expect(steps.length).toBe(sample.stalls.length);
    expect(problems(sample.meta, steps)).toEqual([]);
  });

  it("the browser simulator produces a sound trace under both power rules", () => {
    for (const powerRule of ["in_order", "emptiest_first"] as const) {
      const { meta, steps } = run({ fleet: 300, chargers: 40, siteKw: 900, powerRule }, 2);
      expect(problems(meta, steps)).toEqual([]);
    }
  });

  it("the checks catch a trace that breaks the rules", () => {
    const { meta, steps } = run({ fleet: 120, chargers: 16 }, 0.5);
    const broken = steps.map((s) => ({ ...s }));
    broken[10].on_road += 1;
    broken[11].grid_kw = 99999;
    const found = problems(meta, broken).join("\n");
    expect(found).toContain("do not add up");
    expect(found).toContain("over the site limit");
  });
});
