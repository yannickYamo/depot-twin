// The money: one depot design and one way of running it, as an operator counts it. Every figure comes
// from a recorded run of the full model on the frozen fortnight (money.json, written from E19). The three
// parameters with no public source (what a vehicle costs a year, what running one costs a day, and what a
// lost ride costs beyond its fare) are sliders, and the account is redone in the page as they move; nothing else is computed here.

import type { Grid } from "../grid";
import { LABEL, PAGE as T, percent, surface, text, whole } from "./canvas";

interface Row {
  fleet: number;
  feeder: string;
  chargers: number;
  control: string;
  per_day: Record<string, number>;
  rides_lost_per_day?: number;
  contribution_per_day: number;
  rides_served_share: number;
  rides_per_vehicle_day: number;
  availability: number;
  kwh_per_ride: number;
  site_capital: number;
  promises_kept?: number | null;
  meets_service: boolean;
  grid_at_limit_share: number;
  vehicles_waiting_share: number;
  vehicles_short_share: number;
  energy_cost_per_kwh_tariff: number;
  energy_cost_per_kwh_day_ahead: number;
  energy_cost_per_kwh_real_time: number;
  fare_per_ride?: number;
  busy_share?: number;
  busy_priced_share?: number;
}

interface Money {
  window: string;
  assumptions: {
    vehicle_cost_per_year: number;
    operations_per_vehicle_day: number;
    delivery_adder_usd_per_kwh: number;
    required_service: number;
    lost_ride_cost?: number;
    pricing?: { published_average_fare: number; busy_threshold: number; busy_cap: number };
  };
  fleets: number[];
  feeders: string[];
  chargers: number[];
  controls: string[];
  rows: Row[];
}

const FEEDER_NAME: Record<string, string> = { one_feeder: "One feeder, 2.75 MW", two_feeders: "Two feeders, 5.5 MW" };
const CONTROL_NAME: Record<string, string> = {
  threshold: "Fixed threshold",
  plan_tariff: "The plan, told the tariff",
  plan_day_ahead: "The plan, told the day-ahead price",
};
const SCENARIO_NAME: Record<string, string> = {
  tariff: "PG&E tariff (what the site pays)",
  day_ahead: "Day-ahead wholesale plus delivery (a scenario)",
  real_time: "Real-time wholesale plus delivery (a scenario)",
};
const LINES: [string, string][] = [
  ["revenue", "Fares"],
  ["energy", "Energy"],
  ["subscription", "Capacity subscription"],
  ["chargers", "Chargers"],
  ["buffer", "Storage"],
  ["connection", "Grid connection"],
  ["land", "Land"],
  ["staff", "People on site"],
  ["vehicles", "Vehicles"],
  ["vehicle_operations", "Running the vehicles"],
  ["reliability", "Rides lost, beyond the fare"],
];

interface Choice {
  fleet: number;
  feeder: string;
  chargers: number;
  control: string;
  scenario: "tariff" | "day_ahead" | "real_time";
  vehicleCost: number;
  operations: number;
  lostRide: number;
}

function dollars(value: number): string {
  return `${value < 0 ? "−" : ""}$${Math.abs(Math.round(value)).toLocaleString("en-US")}`;
}

/** Rides lost a day: the run's own count where the row carries it, else worked back from the share served. */
export function lostPerDay(row: Row): number {
  if (row.rides_lost_per_day != null) return row.rides_lost_per_day;
  const servedPerDay = row.rides_per_vehicle_day * row.fleet;
  return servedPerDay / Math.max(row.rides_served_share, 1e-6) - servedPerDay;
}

/** The account for a row, redone for the chosen parameters and price scenario. */
export function book(row: Row, choice: Choice): { lines: Record<string, number>; contribution: number } {
  const lines: Record<string, number> = { ...row.per_day };
  lines.energy = row.per_day[`energy_${choice.scenario}`] ?? row.per_day.energy_tariff;
  lines.vehicles = (choice.fleet * choice.vehicleCost) / 365;
  lines.vehicle_operations = choice.fleet * choice.operations;
  lines.reliability = lostPerDay(row) * choice.lostRide;
  const costs = LINES.filter(([key]) => key !== "revenue").reduce((sum, [key]) => sum + (lines[key] ?? 0), 0);
  return { lines, contribution: lines.revenue - costs };
}

function meets(row: Row, required: number): boolean {
  return row.rides_served_share >= required && (row.control === "threshold" || (row.promises_kept ?? 0) >= 0.95);
}

/** Contribution per day against fleet size, one line per control, the best design that meets service marked. */
function drawSweetSpot(canvas: HTMLCanvasElement, data: Money, choice: Choice): void {
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  const plot = { x: 64, y: 30, w: w - 80, h: h - 56 };
  const rows = data.rows.filter((r) => r.feeder === choice.feeder && r.chargers === choice.chargers);
  const values = rows.map((r) => book(r, { ...choice, fleet: r.fleet }).contribution / 1000);
  const top = Math.ceil(Math.max(...values, 1) / 50) * 50;
  const bottom = Math.min(0, Math.floor(Math.min(...values) / 50) * 50);
  const up = (v: number) => plot.y + plot.h * (1 - (v - bottom) / (top - bottom));
  const across = (fleet: number) => plot.x + ((fleet - data.fleets[0]) / (data.fleets[data.fleets.length - 1] - data.fleets[0])) * plot.w;
  for (const level of [bottom, (bottom + top) / 2, top]) {
    ctx.strokeStyle = level === bottom ? T.ink : T.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(plot.x, up(level));
    ctx.lineTo(plot.x + plot.w, up(level));
    ctx.stroke();
    text(ctx, `$${whole(level)}k`, plot.x - 6, up(level) + 4, LABEL, T.label, "right");
  }
  for (const fleet of data.fleets) text(ctx, whole(fleet), across(fleet), plot.y + plot.h + 16, LABEL, T.label, "center");
  const colors: Record<string, string> = { threshold: T.label, plan_tariff: T.road, plan_day_ahead: T.energyLine };
  let legendX = plot.x;
  for (const control of data.controls) {
    const line = rows.filter((r) => r.control === control).sort((a, b) => a.fleet - b.fleet);
    ctx.strokeStyle = colors[control];
    ctx.lineWidth = control === choice.control ? 2.5 : 1.5;
    ctx.setLineDash(control === choice.control ? [] : [4, 4]);
    ctx.beginPath();
    line.forEach((r, k) => {
      const y = up(book(r, { ...choice, fleet: r.fleet }).contribution / 1000);
      k === 0 ? ctx.moveTo(across(r.fleet), y) : ctx.lineTo(across(r.fleet), y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    // Designs that miss the required service are hollow.
    for (const r of line) {
      const y = up(book(r, { ...choice, fleet: r.fleet }).contribution / 1000);
      ctx.beginPath();
      ctx.arc(across(r.fleet), y, 4, 0, Math.PI * 2);
      if (meets(r, data.assumptions.required_service)) {
        ctx.fillStyle = colors[control];
        ctx.fill();
      } else {
        ctx.strokeStyle = colors[control];
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
    const short = { threshold: "threshold", plan_tariff: "plan, tariff", plan_day_ahead: "plan, day-ahead price" }[control] ?? control;
    text(ctx, short, legendX, 14, LABEL, colors[control]);
    legendX += ctx.measureText(short).width + 18;
  }
  const good = rows.filter((r) => r.control === choice.control && meets(r, data.assumptions.required_service));
  if (good.length) {
    const best = good.reduce((a, b) => (book(b, { ...choice, fleet: b.fleet }).contribution > book(a, { ...choice, fleet: a.fleet }).contribution ? b : a));
    const x = across(best.fleet);
    const y = up(book(best, { ...choice, fleet: best.fleet }).contribution / 1000);
    ctx.strokeStyle = T.ink;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 8, 0, Math.PI * 2);
    ctx.stroke();
    text(ctx, `sweet spot: ${whole(best.fleet)} vehicles`, Math.min(x + 12, plot.x + plot.w - 150), y - 10, LABEL, T.ink);
  }
}

/** The three prices through the first day shown, with the tariff as steps. */
function drawPrices(canvas: HTMLCanvasElement, grid: Grid | null): void {
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  if (!grid) return;
  const plot = { x: 64, y: 30, w: w - 80, h: h - 56 };
  const minutes = Array.from({ length: 7 * 24 * 12 }, (_, k) => k * 5);
  const tariff = minutes.map((m) => {
    const hour = (m % 1440) / 60;
    return hour >= 16 && hour < 21 ? 0.36003 : hour >= 9 && hour < 14 ? 0.12849 : 0.15115;
  });
  const dayAhead = minutes.map((m) => (grid.dayAheadPrice(m) ?? 0) + 0.08);
  const realTime = minutes.map((m) => (grid.realTimePrice(m) ?? 0) + 0.08);
  const top = 0.5;
  const bottom = Math.min(0, Math.floor(Math.min(...realTime) * 10) / 10);
  const up = (v: number) => plot.y + plot.h * (1 - (v - bottom) / (top - bottom));
  const across = (k: number) => plot.x + (k / minutes.length) * plot.w;
  for (const level of [bottom, 0.25, 0.5]) {
    ctx.strokeStyle = level === bottom ? T.ink : T.rule;
    ctx.beginPath();
    ctx.moveTo(plot.x, up(level));
    ctx.lineTo(plot.x + plot.w, up(level));
    ctx.stroke();
    text(ctx, `$${level.toFixed(2)}`, plot.x - 6, up(level) + 4, LABEL, T.label, "right");
  }
  for (let d = 0; d < 7; d++) text(ctx, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d], across(d * 288), plot.y + plot.h + 16, LABEL, T.label);
  const line = (values: number[], color: string, width: number) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    values.forEach((v, k) => (k === 0 ? ctx.moveTo(across(k), up(Math.min(top, v))) : ctx.lineTo(across(k), up(Math.min(top, v)))));
    ctx.stroke();
  };
  line(realTime, "#c3ccd8", 1);
  line(dayAhead, T.energyLine, 2);
  line(tariff, T.ink, 2);
  text(ctx, "tariff", plot.x, 14, LABEL, T.ink);
  text(ctx, "day-ahead plus delivery", plot.x + 44, 14, LABEL, T.energyLine);
  text(ctx, "real-time plus delivery", plot.x + 196, 14, LABEL, T.label);
}

export class MoneyView {
  private data: Money | null = null;
  private choice: Choice = { fleet: 500, feeder: "one_feeder", chargers: 1, control: "plan_tariff", scenario: "tariff", vehicleCost: 60000, operations: 100, lostRide: 20 };

  constructor(private readonly root: HTMLElement, private readonly grid: () => Grid | null) {
    root.addEventListener("input", (event) => this.onInput(event));
    root.addEventListener("change", (event) => this.onChange(event));
    root.addEventListener("click", (event) => {
      const option = (event.target as HTMLElement).closest<HTMLElement>("[data-key][data-value]");
      if (option) this.set(option.dataset.key!, option.dataset.value!);
    });
    window.addEventListener("resize", () => this.draw());
  }

  async show(): Promise<void> {
    if (!this.data) {
      try {
        this.data = (await (await fetch("money.json")).json()) as Money;
        this.choice.vehicleCost = this.data.assumptions.vehicle_cost_per_year;
        this.choice.operations = this.data.assumptions.operations_per_vehicle_day;
        this.choice.lostRide = this.data.assumptions.lost_ride_cost ?? 20;
      } catch {
        this.root.innerHTML = `<p class="quiet">The money results could not be loaded. Check the connection and choose this mode again.</p>`;
        return;
      }
    }
    this.render();
  }

  private set(key: string, value: string): void {
    const choice = this.choice as unknown as Record<string, string | number>;
    choice[key] = typeof choice[key] === "number" ? Number(value) : value;
    this.render();
  }

  private onInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.id === "money-vehicle") this.choice.vehicleCost = Number(input.value);
    if (input.id === "money-operations") this.choice.operations = Number(input.value);
    if (input.id === "money-lost") this.choice.lostRide = Number(input.value);
    if (!["money-vehicle", "money-operations", "money-lost"].includes(input.id)) return;
    // Redrawing replaces the slider under the visitor's hand, which ends a drag and drops keyboard focus. So
    // while a slider moves only its own figure is rewritten; the account is redrawn when it is let go.
    const shown = input.closest("label")?.querySelector("b");
    if (shown) shown.textContent = dollars(Number(input.value));
  }

  private onChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!["money-vehicle", "money-operations", "money-lost"].includes(input.id)) return;
    this.render();
    this.root.querySelector<HTMLInputElement>(`#${input.id}`)?.focus();
  }

  private row(): Row | undefined {
    const c = this.choice;
    return this.data!.rows.find((r) => r.fleet === c.fleet && r.feeder === c.feeder && r.chargers === c.chargers && r.control === c.control);
  }

  private pills(key: keyof Choice, values: (string | number)[], names: (v: string | number) => string): string {
    return values
      .map((v) => `<button type="button" role="radio" aria-checked="${this.choice[key] === v}" data-key="${key}" data-value="${v}">${names(v)}</button>`)
      .join("");
  }

  private render(): void {
    const data = this.data!;
    const row = this.row();
    const c = this.choice;
    const dials =
      `<fieldset><legend>Vehicles in the fleet</legend><div class="options" role="radiogroup">${this.pills("fleet", data.fleets, (v) => whole(Number(v)))}</div></fieldset>` +
      `<fieldset><legend>Grid connection</legend><div class="options" role="radiogroup">${this.pills("feeder", data.feeders, (v) => FEEDER_NAME[String(v)])}</div></fieldset>` +
      `<fieldset><legend>Chargers</legend><div class="options" role="radiogroup">${this.pills("chargers", data.chargers, (v) => (Number(v) === 1 ? "The sizing rule's count" : "One and a half times it"))}</div></fieldset>` +
      `<fieldset><legend>How vehicles are called in</legend><div class="options" role="radiogroup">${this.pills("control", data.controls, (v) => CONTROL_NAME[String(v)])}</div></fieldset>` +
      `<fieldset><legend>What energy costs</legend><div class="options" role="radiogroup">${this.pills("scenario", ["tariff", "day_ahead", "real_time"], (v) => SCENARIO_NAME[String(v)])}</div></fieldset>` +
      `<fieldset><legend>Three figures with no public source</legend>` +
      `<label><span>A vehicle, a year <b>${dollars(c.vehicleCost)}</b></span><input type="range" id="money-vehicle" min="30000" max="100000" step="5000" value="${c.vehicleCost}" /></label>` +
      `<label><span>Running a vehicle, a day <b>${dollars(c.operations)}</b></span><input type="range" id="money-operations" min="50" max="250" step="10" value="${c.operations}" /></label>` +
      `<label><span>A lost ride, beyond its fare <b>${dollars(c.lostRide)}</b></span><input type="range" id="money-lost" min="0" max="60" step="5" value="${c.lostRide}" /></label></fieldset>`;
    let account = `<p class="quiet">No run was recorded for this design.</p>`;
    if (row) {
      const { lines, contribution } = book(row, c);
      const items = LINES.map(([key, name]) => `<tr><th scope="row">${name}</th><td>${key === "revenue" ? "" : "−"}${dollars(lines[key] ?? 0)}</td></tr>`).join("");
      const service = meets(row, data.assumptions.required_service);
      account =
        `<dl class="readouts four">` +
        `<div><dt>Contribution, a day</dt><dd>${dollars(contribution)}<small>${dollars(contribution / c.fleet)} a vehicle-day; ${dollars((contribution * 7) / (row.rides_per_vehicle_day * c.fleet * 7))} a ride</small></dd></div>` +
        `<div><dt>Rides served</dt><dd>${percent(row.rides_served_share)}<small>${service ? "meets" : "misses"} the required ${percent(data.assumptions.required_service)}${row.promises_kept != null ? `; promises kept ${percent(row.promises_kept)}` : ""}</small></dd></div>` +
        `<div><dt>A ride pays</dt><dd>${row.fare_per_ride != null ? "$" + row.fare_per_ride.toFixed(2) : "—"}<small>${row.busy_priced_share != null ? `busy pricing in ${percent(row.busy_priced_share)} of the fortnight; fleet ${percent(row.busy_share ?? 0)} busy` : "the published average"}</small></dd></div>` +
        `<div><dt>Rides lost, a day</dt><dd>${whole(lostPerDay(row))}<small>${dollars(lines.reliability)} beyond their fares at ${dollars(c.lostRide)} each</small></dd></div>` +
        `<div><dt>Vehicles on the road</dt><dd>${percent(row.availability)}<small>of all vehicle-hours; ${row.rides_per_vehicle_day.toFixed(1)} rides a vehicle-day</small></dd></div>` +
        `<div><dt>Energy, per kWh</dt><dd>$${(lines.energy / Math.max(1, (row.kwh_per_ride * row.rides_per_vehicle_day * c.fleet))).toFixed(3)}<small>${row.kwh_per_ride.toFixed(2)} kWh a ride</small></dd></div>` +
        `<div><dt>Site capital</dt><dd>${dollars(row.site_capital)}<small>chargers, storage and connection; ${contribution > 0 ? (row.site_capital / (365 * contribution)).toFixed(2) + " years to pay back" : "not paid back"}</small></dd></div>` +
        `<div><dt>What binds</dt><dd>${whole(100 * Math.max(row.grid_at_limit_share, row.vehicles_waiting_share, row.vehicles_short_share))}%<small>of the time: ${row.grid_at_limit_share >= Math.max(row.vehicles_waiting_share, row.vehicles_short_share) ? "the grid at its limit" : row.vehicles_waiting_share >= row.vehicles_short_share ? "vehicles waiting for a charger" : "every vehicle busy"}</small></dd></div>` +
        `</dl><table class="account"><tbody>${items}<tr class="total"><th scope="row">Contribution</th><td>${dollars(contribution)}</td></tr></tbody></table>`;
    }
    this.root.innerHTML = `
      <div class="wb-grid">
        <aside class="wb-dials" aria-label="The design and the assumptions">${dials}</aside>
        <div class="wb-main">
          <p class="wb-note"><b>One fortnight, every input dated.</b> Real San Francisco rides from ${data.window === "sf_e8" ? "15 April 2024" : data.window}, the trained forecasts, PG&E's BEV-2 tariff of March 2026, and California ISO net demand, emissions and wholesale prices for the same days. The second week is scored. Each ride priced the way the service prices: base, distance and time levelled on a published average, and busy pricing up to 1.3 times when the fleet is nearly all busy; chargers, land, people and connection from the site notes. The three sliders are the figures this project has no public source for.</p>
          <h2>The account, a day</h2>
          ${account}
          <div class="charts">
            <figure><figcaption>Contribution against fleet size</figcaption><canvas id="money-spot"></canvas>
              <p class="probe">For the connection and chargers chosen, under the prices chosen and the three sliders. Hollow points miss the required service. The ring marks the sweet spot for the chosen way of calling vehicles in.</p></figure>
            <figure><figcaption>What energy costs, hour by hour</figcaption><canvas id="money-prices"></canvas>
              <p class="probe">The first week shown. The tariff is what the site pays. The wholesale lines are what the grid paid at the PG&E load point, plus an assumed $${data.assumptions.delivery_adder_usd_per_kwh.toFixed(2)} a kWh for delivery: a scenario for an operator with a pass-through contract.</p></figure>
          </div>
        </div>
      </div>`;
    this.draw();
  }

  private draw(): void {
    if (!this.data || this.root.hidden) return;
    const spot = this.root.querySelector<HTMLCanvasElement>("#money-spot");
    const prices = this.root.querySelector<HTMLCanvasElement>("#money-prices");
    if (!spot || !prices) return;
    drawSweetSpot(spot, this.data, this.choice);
    drawPrices(prices, this.grid());
  }
}
