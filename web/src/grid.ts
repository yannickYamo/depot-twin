// The wider grid: a real week of California's net demand and carbon intensity, five minutes at a time.
//
// The depot's own limit is local. This is the second question: is the grid as a whole strained at the hour
// the depot draws its power? Net demand is demand less wind and solar, the part dispatchable plants must
// cover. The file is written by `depot-twin data grid` from the system operator's public record.

import type { Step } from "./trace";

export interface GridWeek {
  source: string;
  week_of: string;
  /** How many days the file covers; the clock wraps round after them. */
  days?: number;
  step_min: number;
  net_demand_mw: number[];
  co2_g_per_kwh: number[];
  /** Wholesale prices at the PG&E load point, dollars a megawatt-hour: by hour, and by five minutes. */
  day_ahead_usd_per_mwh?: number[];
  real_time_usd_per_mwh?: number[];
}

export class Grid {
  private readonly low: number;
  private readonly high: number;
  /** Net demand at or above this is the hardest quarter of the week. */
  readonly hardFrom: number;

  private readonly span: number;

  constructor(readonly week: GridWeek) {
    this.span = (week.days ?? 7) * 1440;
    const sorted = [...week.net_demand_mw].sort((a, b) => a - b);
    this.low = sorted[0];
    this.high = sorted[sorted.length - 1];
    this.hardFrom = sorted[Math.floor(sorted.length * 0.75)];
  }

  private wrapped(minute: number): number {
    return ((minute % this.span) + this.span) % this.span;
  }

  private index(minute: number): number {
    return Math.floor(this.wrapped(minute) / this.week.step_min);
  }

  /** The day-ahead wholesale price in dollars per kWh, or null when the file has none. */
  dayAheadPrice(minute: number): number | null {
    const prices = this.week.day_ahead_usd_per_mwh;
    return prices ? prices[Math.min(prices.length - 1, Math.floor(this.wrapped(minute) / 60))] / 1000 : null;
  }

  /** The real-time wholesale price in dollars per kWh, or null when the file has none. */
  realTimePrice(minute: number): number | null {
    const prices = this.week.real_time_usd_per_mwh;
    return prices ? prices[Math.min(prices.length - 1, this.index(minute))] / 1000 : null;
  }

  /** Net demand in MW at a minute counted from Monday midnight. */
  netDemand(minute: number): number {
    return this.week.net_demand_mw[this.index(minute)];
  }

  /** Grams of CO2 per kWh delivered. */
  carbon(minute: number): number {
    return this.week.co2_g_per_kwh[this.index(minute)];
  }

  /** How strained the grid is, from 0 at the week's easiest moment to 1 at its hardest. */
  strain(minute: number): number {
    return (this.netDemand(minute) - this.low) / (this.high - this.low);
  }

  /** What a stretch of the depot's charging meant for the grid. */
  footprint(steps: Step[]): { hardShare: number; carbon: number; gridCarbon: number } {
    let energy = 0;
    let hard = 0;
    let carbon = 0;
    let gridCarbon = 0;
    for (const step of steps) {
      energy += step.grid_kw;
      carbon += step.grid_kw * this.carbon(step.minute);
      gridCarbon += this.carbon(step.minute);
      if (this.netDemand(step.minute) >= this.hardFrom) hard += step.grid_kw;
    }
    return {
      hardShare: energy > 0 ? hard / energy : 0,
      carbon: energy > 0 ? carbon / energy : 0,
      gridCarbon: steps.length > 0 ? gridCarbon / steps.length : 0,
    };
  }
}

export async function loadGrid(): Promise<Grid | null> {
  try {
    return new Grid((await (await fetch("grid/california_week.json")).json()) as GridWeek);
  } catch {
    return null;
  }
}
