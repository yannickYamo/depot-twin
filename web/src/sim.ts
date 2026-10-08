// A depot simulator small enough to run in the browser.
//
// This is a second implementation of the depot's core, written so that a visitor can change the site, the
// fleet and the rules and watch what happens without a server. The reference is the Python simulator in
// src/depot_twin. A test holds this one to it: on a fixed set of cases the headline numbers must agree
// within a stated tolerance (tests/sim.test.ts).
//
// What it models: rides offered through the week, each vehicle's battery on the road, the drive to and
// from the depot, a queue for chargers, charging under the site's power limit with the battery's own
// charge curve, cleaning, and two ways of sharing power when it is short.
// What it leaves out: the day-ahead plan and the ride forecasts. Where the page shows a result that
// depends on those, it replays a run recorded from Python instead.

import { WEEKLY_SHAPE } from "./shape";
import { PLACE, tariffAt, type Step, type TraceMeta } from "./trace";

export type PowerRule = "in_order" | "emptiest_first";
export type RecallRule = "threshold" | "slots";

export interface Params {
  fleet: number;
  siteKw: number;
  chargers: number;
  chargerKw: number;
  /** How vehicles are called in: at a fixed charge level, or in energy slots paced to the chargers. */
  recall: RecallRule;
  powerRule: PowerRule;
  /** Charge level under which a vehicle is called in (threshold rule). */
  callBelow: number;
  /** A vehicle is cleaned on every Nth of its visits; the filings' cadence needs the wash off the charging path. */
  cleanEvery: number;
  /** Charge level a vehicle is released at. */
  target: number;
  /** Length of a charging slot in minutes (slots rule). A slot is the energy a charger delivers in that time. */
  slotMin: number;
  /** Minutes to drive between the riders and the depot, each way. */
  legMin: number;
  ridesPerVehicleDay: number;
  /** People who plug in, unplug and clean. Zero means one per cleaning bay, as in the reference scenarios. */
  staff: number;
  seed: number;
}

export const DEFAULTS: Params = {
  fleet: 500,
  siteKw: 2750,
  chargers: 66,
  chargerKw: 60,
  recall: "threshold",
  powerRule: "in_order",
  callBelow: 0.55,
  cleanEvery: 4,
  target: 0.85,
  slotMin: 60,
  legMin: 8,
  ridesPerVehicleDay: 25,
  staff: 0,
  seed: 1,
};

// Figures shared with the Python simulator. Sources are in docs/SITE.md.
const STEP_MIN = 5;
const RIDE_MIN = 23;
const RIDE_MILES = 0.99 + 3.93;
const IDLE_MPH = 2.4;
const PLUG_MIN = 2;
const CLEAN_MIN = 8;
/** A vehicle is inspected on every tenth of its own visits, whether or not that visit is a cleaning one. */
const INSPECT_EVERY = 10;
const INSPECT_MIN = 20;
/** How long a rider waits for a vehicle to come free before giving up (assumed; the same figure as the Python model). */
const MAX_WAIT_MIN = 10;
const EFFICIENCY = 0.93;
/** A Level 2 charger is AC: the vehicle's own charger sets the rate, 11 kW on both models. Anything at or under this is AC. */
export const AC_LIMIT_KW = 22;
const AC_ACCEPT_KW = 11;
/** The share of the connection the load manager lets the chargers draw; the rest is its margin (docs/SITE.md). */
export const USABLE = 0.95;
const FLOOR_SOC = 0.08;
const MUST_COME_IN = 0.12;
const SPREAD = 0.08;

interface Model {
  capacity: number;
  drive: number; // kWh per mile
  alwaysOn: number; // kW
  accept: (soc: number) => number; // kW the battery takes on a fast charger
}

const IPACE_CURVE: [number, number][] = [[0, 100], [0.4, 100], [0.6, 70], [0.8, 50], [0.9, 35], [1, 10]];

function interpolate(points: [number, number][], x: number): number {
  for (let k = 1; k < points.length; k++) {
    if (x <= points[k][0]) {
      const [x0, y0] = points[k - 1];
      const [x1, y1] = points[k];
      return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0);
    }
  }
  return points[points.length - 1][1];
}

const MODELS: Model[] = [
  { capacity: 90, drive: 0.3, alwaysOn: 2.0, accept: (soc) => interpolate(IPACE_CURVE, soc) },
  { capacity: 93, drive: 0.27, alwaysOn: 1.8, accept: (soc) => (soc <= 0.8 ? 150 : 150 * (0.2 + 0.8 * Math.max(0, (1 - soc) / 0.2))) },
];
const MODEL_MIX = [0.6, 0.4];

// Where a vehicle is. The three "Needs" states are waits for a person: people plug vehicles in, unplug
// them and clean them, and there are only so many people.
const enum At { Road, Inbound, Queued, NeedsPlug, Plugging, Charging, NeedsUnplug, Unplugging, NeedsCleaning, Cleaning, Outbound }

/** A small seeded random source, so a run can be repeated exactly. */
class Random {
  private state: number;
  constructor(seed: number) {
    this.state = (seed * 2654435761) >>> 0 || 1;
  }
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  normal(): number {
    return Math.sqrt(-2 * Math.log(1 - this.next())) * Math.cos(2 * Math.PI * this.next());
  }
  poisson(mean: number): number {
    if (mean > 30) return Math.max(0, Math.round(mean + Math.sqrt(mean) * this.normal()));
    const limit = Math.exp(-mean);
    let count = 0;
    for (let product = this.next(); product > limit; product *= this.next()) count++;
    return count;
  }
  /** Mean one, the same spread the Python simulator gives each vehicle's share of the work. */
  workShare(): number {
    return -0.25 * Math.log((1 - this.next()) * (1 - this.next()) * (1 - this.next()) * (1 - this.next()));
  }
}

/** Split `total` vehicle-steps of work across vehicles by weight, none above one step; the excess of a full vehicle
 *  goes to the others until nothing is left or every vehicle is full. Mirrors `fleet.busy_shares` in the Python model. */
export function busyShares(total: number, weights: number[]): number[] {
  const n = weights.length;
  const busy = new Array<number>(n).fill(0);
  const open = new Array<boolean>(n).fill(true);
  let left = Math.min(total, n);
  for (let round = 0; round < n && left > 1e-12; round++) {
    let weightSum = 0;
    for (let k = 0; k < n; k++) if (open[k]) weightSum += weights[k];
    if (weightSum === 0) break;
    let given = 0;
    for (let k = 0; k < n; k++) {
      if (!open[k]) continue;
      const take = Math.min((left * weights[k]) / weightSum, 1 - busy[k]);
      busy[k] += take;
      given += take;
      if (busy[k] >= 1 - 1e-12) open[k] = false;
    }
    left -= given;
  }
  return busy;
}

export class DepotSim {
  readonly params: Params;
  minute = 0;
  private readonly random: Random;
  private readonly model: Model[] = [];
  private readonly capacity: Float64Array;
  private readonly drive: Float64Array;
  private readonly alwaysOn: Float64Array;
  private readonly soc: Float64Array;
  private readonly target: Float64Array;
  private readonly at: Uint8Array;
  private readonly timer: Float64Array; // minutes left in a timed phase
  private readonly since: Float64Array; // when the vehicle joined the queue or plugged in
  private readonly stall: Int32Array;
  private readonly stallFree: boolean[];
  private readonly bays: number;
  private cleaning = 0;
  private visits!: Uint16Array;
  private hasBay!: Uint8Array; // holding a cleaning bay, with or without a person yet
  private bayMin!: Float64Array; // minutes this visit spends in a bay: cleaning, inspection, or both
  private readonly riders: [number, number][] = []; // rides waiting for a vehicle: [minute they give up, rides]
  /** Rides given up on so far. */
  lost = 0;
  private staffBusy = 0;

  constructor(params: Partial<Params> = {}) {
    this.params = { ...DEFAULTS, ...params };
    const n = this.params.fleet;
    this.random = new Random(this.params.seed);
    this.capacity = new Float64Array(n);
    this.drive = new Float64Array(n);
    this.alwaysOn = new Float64Array(n);
    this.soc = new Float64Array(n);
    this.target = new Float64Array(n);
    this.at = new Uint8Array(n);
    this.timer = new Float64Array(n);
    this.since = new Float64Array(n);
    this.visits = new Uint16Array(n);
    this.bayMin = new Float64Array(n);
    this.hasBay = new Uint8Array(n);
    this.stall = new Int32Array(n).fill(-1);
    this.stallFree = new Array(this.params.chargers).fill(true);
    this.bays = Math.max(4, Math.floor(n / 40));
    for (let v = 0; v < n; v++) {
      const model = MODELS[this.random.next() < MODEL_MIX[0] ? 0 : 1];
      this.model.push(model);
      this.capacity[v] = model.capacity;
      // No two vehicles use exactly the same energy.
      this.drive[v] = model.drive * clamp(1 + SPREAD * this.random.normal(), 0.7, 1.3);
      this.alwaysOn[v] = model.alwaysOn * clamp(1 + SPREAD * this.random.normal(), 0.7, 1.3);
      this.soc[v] = 0.35 + 0.55 * this.random.next();
    }
  }

  /** Site settings can change while a run is going, so the number of people is read each time. */
  private get staff(): number {
    return this.params.staff || this.bays;
  }

  meta(label = ""): TraceMeta {
    const p = this.params;
    return {
      label,
      depot: "in the browser",
      fleet: p.fleet,
      site_limit_kw: p.siteKw,
      usable_kw: p.siteKw * USABLE,
      chargers: p.chargers,
      charger_kw: p.chargerKw,
      buffer_kwh: 0,
      cleaning_bays: this.bays,
      step_min: STEP_MIN,
      recall: p.recall,
      power_rule: p.powerRule,
      seed: p.seed,
    };
  }

  /** Rides offered per hour at a given minute of the week. */
  ridesPerHour(minute: number): number {
    const hour = Math.floor(minute / 60) % 168;
    return WEEKLY_SHAPE[hour] * this.params.ridesPerVehicleDay * 7 * this.params.fleet;
  }

  /** Advance five minutes and return what the depot and fleet look like at the end of them. */
  step(): Step {
    const [offered, served] = this.serve();
    this.recall();
    let grid = 0;
    let arrivals = 0;
    let departures = 0;
    for (let m = 0; m < STEP_MIN; m++) {
      const moved = this.depotMinute();
      grid += moved.grid / STEP_MIN;
      arrivals += moved.arrivals;
      departures += moved.departures;
    }
    this.minute += STEP_MIN;
    const count = (place: At) => this.at.reduce((sum, at) => sum + (at === place ? 1 : 0), 0);
    // What to expect of the hour that starts an hour from now. Here that is the weekly pattern itself.
    const forecast = this.ridesPerHour(this.minute + 60);
    return {
      minute: this.minute,
      on_road: count(At.Road),
      inbound: count(At.Inbound),
      queued: count(At.Queued),
      charging: count(At.Charging),
      cleaning: count(At.Cleaning),
      handling: count(At.NeedsPlug) + count(At.Plugging) + count(At.NeedsUnplug) + count(At.Unplugging) + count(At.NeedsCleaning),
      outbound: count(At.Outbound),
      arrivals,
      departures,
      offered,
      served: Math.round(served * 10) / 10,
      grid_kw: Math.round(grid),
      buffer_kwh: 0,
      forecast: Math.round(forecast),
      forecast_upper: Math.round(forecast * 1.2),
      promised: null,
      tariff: tariffAt(this.minute),
      stalls: this.stallSnapshot(),
      chain: this.chainSnapshot(),
    };
  }

  private onRoad(): number[] {
    const list: number[] = [];
    for (let v = 0; v < this.at.length; v++) if (this.at[v] === At.Road) list.push(v);
    return list;
  }

  /** Serve this step's rides with the vehicles on the road, and drain their batteries. */
  private serve(): [number, number] {
    const hours = STEP_MIN / 60;
    const road = this.onRoad();
    const offered = this.random.poisson(this.ridesPerHour(this.minute) * hours);
    // A vehicle with nothing left in its battery is on the road but carries nobody.
    const able = road.filter((v) => this.soc[v] > 0);
    const served = this.takeRides(offered, (able.length * STEP_MIN) / RIDE_MIN);
    // Each vehicle's busy share varies around the fleet's, cannot exceed the whole step, and the shares add up
    // to exactly the minutes the served rides took, so every ride counted drains a battery.
    const shares = busyShares((served * RIDE_MIN) / STEP_MIN, able.map(() => this.random.workShare()));
    const busyOf = new Map(able.map((v, k) => [v, shares[k]]));
    for (const v of road) {
      const busy = busyOf.get(v) ?? 0;
      const miles = (busy * hours * RIDE_MILES) / (RIDE_MIN / 60) + (1 - busy) * hours * IDLE_MPH;
      const energy = miles * this.drive[v] + this.alwaysOn[v] * hours;
      this.soc[v] = Math.max(0, this.soc[v] - energy / this.capacity[v]);
    }
    return [offered, served];
  }

  /** Serve the riders who have waited longest first. A ride nobody can take waits a few minutes and is then lost. */
  private takeRides(offered: number, canCarry: number): number {
    while (this.riders.length && this.riders[0][0] <= this.minute) this.lost += this.riders.shift()![1];
    if (offered > 0) this.riders.push([this.minute + Math.max(MAX_WAIT_MIN, STEP_MIN), offered]);
    let served = 0;
    while (this.riders.length && canCarry - served > 1e-12) {
      const taken = Math.min(this.riders[0][1], canCarry - served);
      served += taken;
      this.riders[0][1] -= taken;
      if (this.riders[0][1] <= 1e-12) this.riders.shift();
    }
    return served;
  }

  private legMiles(): number {
    return (4 * this.params.legMin) / 15;
  }

  /** Energy for one drive between the road and the depot: the miles, and the always-on load for its minutes. */
  private driveLeg(v: number): void {
    const energy = this.legMiles() * this.drive[v] + (this.alwaysOn[v] * this.params.legMin) / 60;
    this.soc[v] = Math.max(0, this.soc[v] - energy / this.capacity[v]);
  }

  private sendIn(v: number, target: number): void {
    this.driveLeg(v);
    this.target[v] = target;
    this.at[v] = At.Inbound;
    this.timer[v] = this.params.legMin;
  }

  private recall(): void {
    const p = this.params;
    const road = this.onRoad();
    if (p.recall === "threshold") {
      for (const v of road) if (this.soc[v] <= Math.max(p.callBelow, FLOOR_SOC)) this.sendIn(v, p.target);
      return;
    }
    // Slots: a visit is one slot of energy. Call the emptiest vehicles that can take most of a slot, when
    // the road can spare them, a charger will be free, and the site can feed them at full rate.
    // A slot is the energy a vehicle takes in that time: on AC the vehicle's own 11 kW whatever the post is
    // rated, and on a fast charger no more than the batteries accept, 120 kW across the mix.
    const drawKw = p.chargerKw <= AC_LIMIT_KW ? Math.min(p.chargerKw, AC_ACCEPT_KW) : Math.min(p.chargerKw, 120);
    const slotKwh = (drawKw * (p.slotMin - 2 * PLUG_MIN)) / 60;
    const meanCapacity = 91.2;
    const worthCalling = Math.min(0.75, p.target - (0.9 * slotKwh) / meanCapacity);
    const needed = (Math.max(this.ridesPerHour(this.minute), this.ridesPerHour(this.minute + 60)) / (60 / RIDE_MIN)) * 1.1;
    const count = (place: At) => this.at.reduce((sum, at) => sum + (at === place ? 1 : 0), 0);
    const spokenFor = count(At.Inbound) + count(At.Queued);
    const inUse = this.stallFree.filter((free) => !free).length + spokenFor;
    const feedable = Math.floor((p.siteKw * USABLE * EFFICIENCY) / drawKw);
    const room = Math.min(p.chargers, p.powerRule === "in_order" ? feedable : p.chargers) - inUse;
    let take = Math.max(0, Math.min(Math.floor(road.length - needed), room));
    const emptiest = road.slice().sort((a, b) => this.soc[a] - this.soc[b]);
    for (const v of emptiest) {
      const must = this.soc[v] <= MUST_COME_IN;
      if (!must && (take <= 0 || this.soc[v] >= worthCalling)) continue;
      this.sendIn(v, Math.min(p.target, this.soc[v] + slotKwh / this.capacity[v]));
      if (!must) take--;
    }
  }

  /** One minute at the depot: move vehicles between stations, then share out the power. */
  private depotMinute(): { grid: number; arrivals: number; departures: number } {
    const p = this.params;
    const now = this.minute;
    let arrivals = 0;
    let departures = 0;
    for (let v = 0; v < this.at.length; v++) {
      const timed = this.at[v] === At.Inbound || this.at[v] === At.Plugging || this.at[v] === At.Unplugging
        || this.at[v] === At.Cleaning || this.at[v] === At.Outbound;
      if (!timed || --this.timer[v] > 0) continue;
      switch (this.at[v]) {
        case At.Inbound:
          this.at[v] = At.Queued;
          this.since[v] = now;
          arrivals++;
          break;
        case At.Plugging:
          this.staffBusy--;
          this.at[v] = At.Charging;
          this.since[v] = now;
          break;
        case At.Unplugging:
          this.staffBusy--;
          this.stallFree[this.stall[v]] = true;
          this.stall[v] = -1;
          this.visits[v]++;
          // A vehicle is cleaned on every Nth of its visits and inspected on every tenth; the others leave
          // straight from the charger.
          this.bayMin[v] = (this.visits[v] % Math.max(1, p.cleanEvery) === 0 ? CLEAN_MIN : 0)
            + (this.visits[v] % INSPECT_EVERY === 0 ? INSPECT_MIN : 0);
          if (this.bayMin[v] > 0) {
            this.at[v] = At.NeedsCleaning;
            this.since[v] = now;
          } else {
            this.at[v] = At.Outbound;
            this.timer[v] = p.legMin;
            departures++;
          }
          break;
        case At.Cleaning:
          this.staffBusy--;
          this.cleaning--;
          this.hasBay[v] = 0;
          this.at[v] = At.Outbound;
          this.timer[v] = p.legMin;
          departures++;
          break;
        case At.Outbound:
          this.driveLeg(v);
          this.at[v] = At.Road;
          break;
      }
    }
    this.assignChargers();
    this.assignStaff();
    return { grid: this.sharePower(), arrivals, departures };
  }

  private waiting(place: At, emptiestFirst: boolean): number[] {
    const list: number[] = [];
    for (let v = 0; v < this.at.length; v++) if (this.at[v] === place) list.push(v);
    return list.sort((a, b) => (emptiestFirst ? this.soc[a] - this.soc[b] || this.since[a] - this.since[b] : this.since[a] - this.since[b]));
  }

  private assignChargers(): void {
    for (const v of this.waiting(At.Queued, this.params.powerRule === "emptiest_first")) {
      const free = this.stallFree.indexOf(true);
      if (free < 0) return;
      this.stallFree[free] = false;
      this.stall[v] = free;
      this.at[v] = At.NeedsPlug;
      this.since[v] = this.minute;
    }
  }

  /**
   * Hand the free people their next job, first come first served across plugging in, unplugging and
   * cleaning. When many vehicles finish charging together, the unplugging queues behind the cleaning, and
   * chargers sit blocked by vehicles that are full. This is part of why finishing vehicles in turn works.
   */
  private assignStaff(): void {
    // A vehicle that needs a bay takes one first, in turn, and only then asks for a person, holding the bay
    // while it waits. That is the order the Python model works in, and it matters when people are short.
    for (const v of this.waiting(At.NeedsCleaning, false)) {
      if (this.cleaning >= this.bays) break;
      if (this.hasBay[v]) continue;
      this.hasBay[v] = 1;
      this.cleaning++;
      this.since[v] = this.minute;
    }
    const asking: number[] = [];
    for (let v = 0; v < this.at.length; v++) {
      if (this.at[v] === At.NeedsPlug || this.at[v] === At.NeedsUnplug || (this.at[v] === At.NeedsCleaning && this.hasBay[v])) asking.push(v);
    }
    asking.sort((a, b) => this.since[a] - this.since[b]);
    for (const v of asking) {
      if (this.staffBusy >= this.staff) return;
      if (this.at[v] === At.NeedsCleaning) {
        this.at[v] = At.Cleaning;
        this.timer[v] = this.bayMin[v];
      } else {
        this.at[v] = this.at[v] === At.NeedsPlug ? At.Plugging : At.Unplugging;
        this.timer[v] = PLUG_MIN;
      }
      this.staffBusy++;
    }
  }

  /** Share the site's power among the vehicles plugged in, and return what the grid delivered in kW. */
  private sharePower(): number {
    const p = this.params;
    const charging = this.waiting(At.Charging, p.powerRule === "emptiest_first");
    let left = p.siteKw * USABLE * EFFICIENCY;
    let delivered = 0;
    for (const v of charging) {
      const lacking = Math.max(0, this.target[v] - this.soc[v]) * this.capacity[v];
      const rate = p.chargerKw <= AC_LIMIT_KW ? Math.min(p.chargerKw, AC_ACCEPT_KW) : Math.min(p.chargerKw, this.model[v].accept(this.soc[v]));
      const want = Math.min(rate, lacking * 60);
      const kw = Math.max(0, Math.min(want, left));
      left -= kw;
      delivered += kw;
      this.lastKw.set(v, kw);
      this.soc[v] += kw / 60 / this.capacity[v];
      if (this.target[v] - this.soc[v] <= 1e-6) {
        this.at[v] = At.NeedsUnplug;
        this.since[v] = this.minute;
      }
    }
    return delivered / EFFICIENCY;
  }

  private readonly lastKw = new Map<number, number>();

  /** Every vehicle off the road: its number, where it is, and its charge. */
  private chainSnapshot(): number[] {
    const out: number[] = [];
    for (let v = 0; v < this.at.length; v++) {
      if (this.at[v] !== At.Road) out.push(v, PLACE_OF[this.at[v]], Math.round(this.soc[v] * 100));
    }
    return out;
  }

  private stallSnapshot(): number[][] {
    const rows: number[][] = [];
    for (let v = 0; v < this.at.length; v++) {
      if (this.at[v] !== At.Charging) continue;
      rows.push([this.stall[v], v, Math.round(this.soc[v] * 100), Math.round(this.lastKw.get(v) ?? 0)]);
    }
    return rows.sort((a, b) => a[0] - b[0]);
  }
}

// Where each state of a visit shows on screen.
const PLACE_OF: Record<number, number> = {
  [At.Inbound]: PLACE.inbound,
  [At.Queued]: PLACE.queued,
  [At.NeedsPlug]: PLACE.pluggingIn,
  [At.Plugging]: PLACE.pluggingIn,
  [At.Charging]: PLACE.charging,
  [At.NeedsUnplug]: PLACE.afterCharging,
  [At.Unplugging]: PLACE.afterCharging,
  [At.NeedsCleaning]: PLACE.afterCharging,
  [At.Cleaning]: PLACE.cleaning,
  [At.Outbound]: PLACE.outbound,
};

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** Run a simulation for a number of days and return every step. */
export function run(params: Partial<Params>, days: number): { meta: TraceMeta; steps: Step[] } {
  const sim = new DepotSim(params);
  const steps: Step[] = [];
  for (let k = 0; k < (days * 1440) / STEP_MIN; k++) steps.push(sim.step());
  return { meta: sim.meta(), steps };
}

/** Headline numbers for a run, skipping a warm-up at the start. */
export function summarize(steps: Step[], fleet: number, skipDays = 1) {
  const kept = steps.filter((s) => s.minute > skipDays * 1440);
  // A ride can be served a step or two after it was offered; over days the two sums compare, give or take the
  // riders still waiting at either end.
  const offered = kept.reduce((sum, s) => sum + s.offered, 0);
  const served = Math.min(offered, kept.reduce((sum, s) => sum + s.served, 0));
  const busiest = kept.map((s) => s.offered).sort((a, b) => a - b)[Math.floor(kept.length * 0.9)];
  const atPeak = kept.filter((s) => s.offered >= busiest);
  const days = (kept.length * STEP_MIN) / 1440;
  return {
    ridesServedShare: served / offered,
    onRoadWhenBusiest: atPeak.reduce((sum, s) => sum + s.on_road, 0) / atPeak.length / fleet,
    visitsPerVehicleDay: kept.reduce((sum, s) => sum + s.arrivals, 0) / fleet / days,
    gridKwhPerVehicleDay: (kept.reduce((sum, s) => sum + s.grid_kw, 0) * (STEP_MIN / 60)) / fleet / days,
    queueMean: kept.reduce((sum, s) => sum + s.queued, 0) / kept.length,
  };
}
