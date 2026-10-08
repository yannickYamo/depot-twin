// The trace format: what a run looks like step by step. The Python simulator records traces in this shape
// (src/depot_twin/trace.py) and the browser simulator produces the same shape, so one viewer draws both.

export const TRACE_VERSION = 1;

export interface TraceMeta {
  label: string;
  depot: string;
  fleet: number;
  site_limit_kw: number;
  /** What the site may draw at any moment: the share of the connection its load manager uses. */
  usable_kw?: number;
  chargers: number;
  charger_kw: number;
  buffer_kwh: number;
  cleaning_bays: number;
  step_min: number;
  recall: string;
  power_rule: string;
  seed: number;
}

/** One step of a run. Every vehicle is in exactly one of the seven places. */
export interface Step {
  minute: number;
  on_road: number;
  inbound: number;
  queued: number;
  charging: number;
  cleaning: number;
  handling: number;
  outbound: number;
  arrivals: number;
  departures: number;
  offered: number;
  served: number;
  grid_kw: number;
  buffer_kwh: number;
  /** Rides forecast for the hour that starts one hour from now, and the level they should stay under. */
  forecast: number;
  forecast_upper: number;
  promised: number | null;
  tariff: "peak" | "off_peak" | "super_off_peak";
  /** [stall, vehicle, charge in percent, kW] for each vehicle on a charger. */
  stalls: number[][];
  /** Every vehicle off the road, three numbers each: vehicle, place (see PLACE), charge in percent. */
  chain: number[];
}

/** Where a vehicle that is off the road can be, numbered in the order a visit runs. */
export const PLACE = { inbound: 1, queued: 2, pluggingIn: 3, charging: 4, afterCharging: 5, cleaning: 6, outbound: 7 } as const;

/** A vehicle's name on screen. The number is its index in the fleet. */
export function vehicleName(vehicle: number): string {
  return `V-${String(vehicle + 1).padStart(4, "0")}`;
}

/** A trace as stored on disk: one array per column, which is far smaller than one object per step. */
export interface TraceFile {
  version: number;
  meta: TraceMeta;
  steps: Record<string, (number | string | null)[]>;
  stalls: number[][][];
  /** Every vehicle off the road, by name; a trace may leave it out. */
  chains?: number[][];
  /** The day plan each time the controller redrew it. Absent for rules that make no plan. */
  plans?: Plan[];
}

/** A day plan as it stood when it was made: 24 hours of visits, vehicles on the road, rides and energy. */
export interface Plan {
  step: number;
  minute: number;
  quota: number;
  committed: number;
  visits: number[];
  on_road: number[];
  served: number[];
  energy_kwh: number[];
}

/** PG&E's BEV-2-P energy prices in dollars per kWh, by tariff period, sheet of March 2026. */
export const PRICE: Record<Step["tariff"], number> = { peak: 0.36003, off_peak: 0.15115, super_off_peak: 0.12849 };

/** What a stretch of a run cost and delivered: rides, energy, money. */
export function account(steps: Step[]): { served: number; costPerKwh: number; peakShare: number; variation: number } {
  const hours = 5 / 60;
  let offered = 0;
  let served = 0;
  let energy = 0;
  let cost = 0;
  let peak = 0;
  for (const step of steps) {
    offered += step.offered;
    served += step.served;
    const kwh = step.grid_kw * hours;
    energy += kwh;
    cost += kwh * PRICE[step.tariff];
    if (step.tariff === "peak") peak += kwh;
  }
  const mean = steps.reduce((sum, s) => sum + s.grid_kw, 0) / Math.max(1, steps.length);
  const spread = Math.sqrt(steps.reduce((sum, s) => sum + (s.grid_kw - mean) ** 2, 0) / Math.max(1, steps.length));
  return { served: served / Math.max(1, offered), costPerKwh: cost / Math.max(1, energy), peakShare: peak / Math.max(1, energy), variation: spread / Math.max(1, mean) };
}

export const PLACES = ["on_road", "inbound", "queued", "charging", "cleaning", "handling", "outbound"] as const;
export const COLUMNS = [
  "minute", ...PLACES, "arrivals", "departures", "offered", "served", "grid_kw", "buffer_kwh",
  "forecast", "forecast_upper", "promised", "tariff",
] as const;

/** Turn a stored trace into a list of steps. */
export function unpack(file: TraceFile): Step[] {
  const length = file.steps.minute.length;
  const steps: Step[] = [];
  for (let k = 0; k < length; k++) {
    const row: Record<string, unknown> = { stalls: file.stalls[k], chain: file.chains?.[k] ?? [] };
    for (const name of COLUMNS) row[name] = file.steps[name][k];
    steps.push(row as unknown as Step);
  }
  return steps;
}

/**
 * Everything wrong with a run's physics. An empty list means it is sound. The physical checks of `problems`
 * in src/depot_twin/trace.py: vehicles conserved and never negative, limits respected, stalls consistent,
 * rides never served before they were offered. The file's shape (version, columns) is checked there.
 */
export function problems(meta: TraceMeta, steps: Step[]): string[] {
  const found: string[] = [];
  let servedSoFar = 0;
  let offeredSoFar = 0;
  let early = false;
  steps.forEach((s, k) => {
    const total = PLACES.reduce((sum, name) => sum + s[name], 0);
    if (total !== meta.fleet) found.push(`step ${k}: vehicles do not add up to the fleet`);
    if (PLACES.some((name) => s[name] < 0)) found.push(`step ${k}: a negative count of vehicles at a station`);
    if (s.grid_kw > (meta.usable_kw ?? meta.site_limit_kw) + 1) found.push(`step ${k}: grid draw over the site limit`);
    if (s.stalls.length !== s.charging) found.push(`step ${k}: stalls listed do not match vehicles charging`);
    const numbers = s.stalls.map((entry) => entry[0]);
    if (new Set(numbers).size !== numbers.length || numbers.some((n) => n < 0 || n >= meta.chargers)) {
      found.push(`step ${k}: a stall is used twice or does not exist`);
    }
    if (s.stalls.some((e) => e[2] < 0 || e[2] > 100 || e[3] < 0 || e[3] > meta.charger_kw + 1)) {
      found.push(`step ${k}: a charge level or power is out of range`);
    }
    // A ride can be served a step or two after it was offered, never before.
    servedSoFar += s.served;
    offeredSoFar += s.offered;
    if (servedSoFar > offeredSoFar + 0.05 * (k + 1) && !early) {
      early = true;
      found.push(`step ${k}: more rides served than had been offered by then`);
    }
    if (s.chain.length > 0 && s.chain.length !== 3 * (meta.fleet - s.on_road)) {
      found.push(`step ${k}: the vehicles named off the road do not match the count`);
    }
  });
  return found.slice(0, 20);
}

export function tariffAt(minute: number): Step["tariff"] {
  const hour = (minute % 1440) / 60;
  if (hour >= 16 && hour < 21) return "peak";
  if (hour >= 9 && hour < 14) return "super_off_peak";
  return "off_peak";
}
