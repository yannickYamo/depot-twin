// The fleet alert sets the energy arithmetic beside what the tests measured, and takes its level from the
// measurement: a fleet the tests served is never told to stop.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ONE_FEEDER_KW, TWO_FEEDERS_KW, designAlerts, energyPerVehicleDay, fleetAlert, measuredFleet, measuredLimit, sustainableFleet, type Design } from "../src/alerts";
import { USABLE } from "../src/sim";
import { whole } from "../src/views/canvas";

const design = (over: Partial<Design> = {}): Design => ({ fleet: 500, siteKw: ONE_FEEDER_KW, chargers: 66, chargerKw: 60, staff: 12, ridesPerVehicleDay: 25, ...over });

describe("the energy arithmetic", () => {
  it("is a day of the usable connection over a vehicle's day of energy", () => {
    // Worked by hand: 2,750 kW x 0.95 usable x 0.93 into the battery x 24 h = 58,311 kWh; a vehicle at 25 rides
    // takes 61.6 + 1.07 x 25 = 88.35 kWh; 58,311 / 88.35 = 660.0.
    expect(USABLE).toBe(0.95);
    expect(energyPerVehicleDay(25)).toBeCloseTo(88.35, 6);
    expect(sustainableFleet(design())).toBe(660);
    expect(sustainableFleet(design({ siteKw: TWO_FEEDERS_KW }))).toBe(1320);
  });
});

describe("the fleet alert against a measured capacity", () => {
  const measured = { fleet: 600, limit: 700, rides: 25 };
  const both = "the tests carried 600 at the estimated energy use and served 700 with the feeder at its limit around the clock";

  it("says nothing well inside both limits", () => {
    expect(fleetAlert(design({ fleet: 500 }), measured)).toBeNull();
  });

  it("warns near the carried fleet and names every figure", () => {
    for (const fleet of [560, 600]) {
      const alert = fleetAlert(design({ fleet }), measured)!;
      expect(alert.level).toBe("warn");
      expect(alert.text).toContain("near 660 vehicles");
      expect(alert.text).toContain(both);
      expect(alert.text).toMatch(/^Near the site's limit/);
    }
  });

  it("warns, and does not stop, between the carried fleet and the one served at the limit", () => {
    for (const fleet of [620, 680, 700]) {
      const alert = fleetAlert(design({ fleet }), measured)!;
      expect(alert.level).toBe("warn");
      expect(alert.text).toContain(both);
      expect(alert.text).toContain("past what the tests carried and within what they served");
      expect(alert.text).toContain("most visits starting on a low battery");
      expect(alert.text).not.toMatch(/rides to be lost/);
    }
  });

  it("stops past the fleet served at the limit, and still shows the arithmetic and the measurement", () => {
    for (const fleet of [750, 800, 1000]) {
      const alert = fleetAlert(design({ fleet }), measured)!;
      expect(alert.level).toBe("stop");
      expect(alert.text).toContain("near 660 vehicles");
      expect(alert.text).toContain(both);
    }
    // 800 x 88.35 kWh over 0.95 x 0.93 x 24 h = 3,333 kW.
    expect(fleetAlert(design({ fleet: 800 }), measured)!.text).toContain("3.33 MW, a second service connection");
    expect(fleetAlert(design({ fleet: 2000 }), measured)!.text).toContain("more than the two feeders");
  });

  it("scales the arithmetic and the measurement alike on two feeders", () => {
    const two = (fleet: number) => fleetAlert(design({ fleet, siteKw: TWO_FEEDERS_KW }), measured);
    expect(measuredFleet(design({ siteKw: TWO_FEEDERS_KW }), measured)).toBe(1200);
    expect(measuredLimit(design({ siteKw: TWO_FEEDERS_KW }), measured)).toBe(1400);
    expect(two(1000)).toBeNull();
    expect(two(1400)!.level).toBe("warn");
    expect(two(1400)!.text).toContain("near 1,320 vehicles");
    expect(two(1400)!.text).toContain("the tests carried 600 on one feeder at 25 rides a day and served 700");
    expect(two(1400)!.text).toContain("about 1,200 and 1,400 here");
    expect(two(1450)!.level).toBe("stop");
  });

  it("carries the measurement over to another number of rides by the energy a vehicle uses", () => {
    // At 15 rides a vehicle takes 77.65 kWh against 88.35: 700 x 88.35 / 77.65 = 796.5.
    expect(measuredLimit(design({ ridesPerVehicleDay: 15 }), measured)).toBe(796);
    expect(measuredFleet(design(), measured)).toBe(600);
  });

  it("warns of lost rides past what the tests served while the arithmetic still allows the fleet", () => {
    const alert = fleetAlert(design({ fleet: 650 }), { fleet: 500, limit: 600, rides: 25 })!;
    expect(alert.level).toBe("warn");
    expect(alert.text).toContain("past what the tests served: expect some rides to be lost");
  });

  it("falls back to the arithmetic alone while no measurement is loaded", () => {
    expect(fleetAlert(design({ fleet: 700 }), null)!.level).toBe("stop");
    expect(fleetAlert(design({ fleet: 700 }), null)!.text).not.toContain("tests");
    expect(fleetAlert(design({ fleet: 620 }), null)!.level).toBe("warn");
  });
});

describe("the fleet alert against the capacity the page loads", () => {
  const demand = JSON.parse(readFileSync(new URL("../public/demand.json", import.meta.url), "utf8")) as {
    capacity_one_feeder: number; served_at_the_limit_one_feeder: number; rides_per_vehicle_day: number;
  };
  const measured = { fleet: demand.capacity_one_feeder, limit: demand.served_at_the_limit_one_feeder, rides: demand.rides_per_vehicle_day };
  const at = (fleet: number, siteKw = ONE_FEEDER_KW) => design({ fleet, siteKw, ridesPerVehicleDay: measured.rides });

  it("never tells a fleet the tests served to stop, and prints the figures it read", () => {
    expect(measured.limit).toBeGreaterThanOrEqual(measured.fleet);
    for (const fleet of [measured.fleet, measured.limit]) {
      const alert = fleetAlert(at(fleet), measured);
      expect(alert?.level).not.toBe("stop");
      if (alert) expect(alert.text).toContain(`the tests carried ${whole(measured.fleet)} at the estimated energy use`);
    }
  });

  it("stops past both the fleet served at the limit and the arithmetic, on one feeder and on two", () => {
    const one = Math.max(measured.limit, sustainableFleet(at(0))) + 50;
    expect(fleetAlert(at(one), measured)!.level).toBe("stop");
    expect(fleetAlert(at(2 * measured.limit, TWO_FEEDERS_KW), measured)?.level).not.toBe("stop");
    const two = Math.max(2 * measured.limit, sustainableFleet(at(0, TWO_FEEDERS_KW))) + 50;
    expect(fleetAlert(at(two, TWO_FEEDERS_KW), measured)!.level).toBe("stop");
  });

  it("puts the fleet check first among the design checks", () => {
    const all = designAlerts(at(measured.fleet + 1000), measured);
    expect(all[0].level).toBe("stop");
    expect(all[0].text).toContain("Energy arithmetic");
  });
});
