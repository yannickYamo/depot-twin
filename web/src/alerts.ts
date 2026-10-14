// What a chosen design cannot do, worked out from the site's figures: fleet against grid, plugs against
// grid, plugs against fleet, people against fleet. These are sizing rules of thumb, quick and approximate.
// Where the project measured the same thing in its tests, the alert sets the measurement beside the
// arithmetic and takes its level from the measurement.

import { AC_LIMIT_KW, USABLE, type Params } from "./sim";
import { whole } from "./views/canvas";

/** One feeder's connection at this parcel, in kW; two feeders give twice that. */
export const ONE_FEEDER_KW = 2750;
export const TWO_FEEDERS_KW = 2 * ONE_FEEDER_KW;

export type Design = Pick<Params, "fleet" | "siteKw" | "chargers" | "chargerKw" | "staff" | "ridesPerVehicleDay">;

/** The fleet the tests carried on one feeder at the estimated energy use, the largest they still served with the feeder at its
 *  limit, and the rides a vehicle-day both were measured at (demand.json). */
export interface Measured {
  fleet: number;
  /** The fleet to plan for: the largest that still fits with more energy use than estimated. */
  planned?: number;
  limit: number;
  rides: number;
}

export interface Alert {
  level: "stop" | "warn";
  text: string;
}

/** What a vehicle actually takes from a charger of the chosen power: 11 kW on AC whatever the post is rated, and
 *  on a fast charger no more than the batteries accept (100 kW and 150 kW on the two models, 120 kW across the mix). */
export function drawKw(design: Design): number {
  return design.chargerKw <= AC_LIMIT_KW ? Math.min(design.chargerKw, 11) : Math.min(design.chargerKw, 120);
}

/** Plugs the usable connection feeds at once at the chosen charger power. */
export function feedable(design: Design): number {
  return Math.max(1, Math.floor((design.siteKw * USABLE * 0.93) / drawKw(design)));
}

/** Past this many plugs the grid cannot use them: two for every one it feeds at once, the way paired dispensers
 *  share one power cabinet. The slider is not stopped there; the page says so instead (E19: half as many again bought nothing). */
export function chargerCeiling(design: Design): number {
  return (2 * feedable(design)) & ~1;
}

/** What a vehicle draws in a day, from the calibrated fleet: a fixed part for computers, climate and idle
 *  driving, and a part per ride, into the battery: about 88 kWh at 25 rides a day and 78 at 15, as this
 *  simulator measures them. At 25 rides that is 95 kWh from the grid, the figure the Python sizing rule uses. */
export function energyPerVehicleDay(rides: number): number {
  return 61.6 + 1.07 * rides;
}

/** The fleet whose daily energy equals what the usable connection delivers all day. */
export function sustainableFleet(design: Design): number {
  return Math.floor((design.siteKw * USABLE * 0.93 * 24) / energyPerVehicleDay(design.ridesPerVehicleDay));
}

/** The measured one-feeder fleet carried over to the chosen connection and rides a day: in proportion to the
 *  power, and to the energy a vehicle uses. On one feeder at the measured rides it is the measurement itself. */
export function measuredFleet(design: Design, measured: Measured): number {
  const power = design.siteKw / ONE_FEEDER_KW;
  const energy = energyPerVehicleDay(measured.rides) / energyPerVehicleDay(design.ridesPerVehicleDay);
  return Math.floor(measured.fleet * power * energy + 1e-9);
}

/** The largest fleet the tests still served, carried over to the chosen connection and rides a day the same way. */
export function measuredLimit(design: Design, measured: Measured): number {
  return measuredFleet(design, { ...measured, fleet: measured.limit });
}

/** Chargers the fleet's energy asks for: the sizing rule, a charger averaging five sixths of its rating, busy 60% of the day. */
export function chargersNeeded(design: Design): number {
  return Math.ceil((design.fleet * energyPerVehicleDay(design.ridesPerVehicleDay)) / 0.93 / (drawKw(design) * (5 / 6) * 24 * 0.6));
}

const mw = (kw: number) => `${(kw / 1000).toFixed(2)} MW`;

/** The fleet against the grid: what the energy arithmetic says, what the tests measured, and which side the fleet is on. */
export function fleetAlert(design: Design, measured: Measured | null): Alert | null {
  const byArithmetic = sustainableFleet(design);
  const byTests = measured ? measuredFleet(design, measured) : null;
  const asMeasured = measured !== null && design.siteKw === ONE_FEEDER_KW && design.ridesPerVehicleDay === measured.rides;
  const sums = `Energy arithmetic at the use a vehicle has with power to spare puts the limit near ${whole(byArithmetic)} vehicles (a day of ${mw(design.siteKw)} at ${Math.round(USABLE * 100)}%, at ${design.ridesPerVehicleDay} rides a day; a fleet at the limit parks more and takes a little less)`;
  const byLimit = measured ? measuredLimit(design, measured) : null;
  const tests = !measured ? ""
    : asMeasured ? `; the tests carried ${whole(measured.fleet)} at the estimated energy use${measured.planned ? `, plan on ${whole(measured.planned)} so that the fleet still fits with 10% more,` : ""} and served ${whole(measured.limit)} with the feeder at its limit around the clock`
    : `; the tests carried ${whole(measured.fleet)} on one feeder at ${measured.rides} rides a day and served ${whole(measured.limit)} with the feeder at its limit, which scales to about ${whole(byTests!)} and ${whole(byLimit!)} here`;
  const fleet = `${whole(design.fleet)} vehicles`;
  const pastArithmetic = design.fleet > byArithmetic;
  const pastCarried = byTests !== null && design.fleet > byTests;
  const pastLimit = byLimit !== null && design.fleet > byLimit;
  if (pastArithmetic && (pastLimit || byLimit === null)) {
    const need = (design.fleet * energyPerVehicleDay(design.ridesPerVehicleDay)) / (USABLE * 0.93 * 24);
    const more = need > TWO_FEEDERS_KW
      ? "more than the two feeders at this parcel give; the rest is another site or a substation upgrade"
      : "a second service connection";
    return {
      level: "stop",
      text: `${sums}${tests}. ${fleet} ${byLimit === null ? "is past it" : "is past both"} and needs about ${mw(need)}, ${more}. Expect rides to be lost once the batteries run down.`,
    };
  }
  if (pastLimit) {
    return { level: "warn", text: `${sums}${tests}. ${fleet} is within the arithmetic and past what the tests served: expect some rides to be lost.` };
  }
  if (pastCarried) {
    return { level: "warn", text: `${sums}${tests}. ${fleet} is past what the tests carried and within what they served: expect the feeder at its limit all week and most visits starting on a low battery.` };
  }
  if (pastArithmetic) {
    return { level: "warn", text: `${sums}${tests}. ${fleet} is past the arithmetic and within what the tests carried: expect the feeder at its limit for most of the day, with no room to spare.` };
  }
  if (design.fleet > 0.9 * Math.min(byArithmetic, byTests ?? byArithmetic)) {
    return { level: "warn", text: `Near the site's limit. ${sums}${tests}.` };
  }
  return null;
}

/** Every check on the chosen design, the fleet against the grid first. */
export function designAlerts(design: Design, measured: Measured | null): Alert[] {
  const out: Alert[] = [];
  const first = fleetAlert(design, measured);
  if (first) out.push(first);
  const fed = feedable(design);
  const ceiling = chargerCeiling(design);
  const draw = drawKw(design);
  if (design.chargers > ceiling) {
    out.push({ level: "warn", text: `More plugs than the grid can use. ${mw(design.siteKw)} feeds ${whole(fed)} vehicles at once at the ${draw} kW a vehicle takes at most from a ${design.chargerKw} kW charger; with power sharing two plugs per fed one, ${whole(ceiling)}, is the most that pays. The ${whole(design.chargers - ceiling)} beyond that wait for power.` });
  }
  const needed = chargersNeeded(design);
  if (design.chargers < 0.75 * needed) {
    out.push({ level: "warn", text: `Too few chargers for this fleet: ${whole(design.fleet)} vehicles want about ${whole(needed)} at ${design.chargerKw} kW. Vehicles will queue for a plug.` });
  } else if (design.chargers > 2 * needed && design.chargers <= ceiling) {
    out.push({ level: "warn", text: `More chargers than this fleet can use: about ${whole(needed)} would do at ${design.chargerKw} kW. The rest is capital standing still.` });
  }
  if (design.chargers * draw < design.siteKw * USABLE * 0.93 * 0.9) {
    out.push({ level: "warn", text: `Power left on the table: the grid could feed ${whole(fed)} vehicles at once at ${draw} kW each and only ${whole(design.chargers)} chargers are installed.` });
  }
  if (design.staff < design.fleet / 100) {
    out.push({ level: "warn", text: `Too few people: ${whole(design.staff)} for ${whole(design.fleet)} vehicles. Vehicles will sit full on chargers waiting to be unplugged.` });
  }
  return out;
}
