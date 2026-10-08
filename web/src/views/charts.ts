// The heartbeat strip and the two charts under the floor. One axis per chart, labelled directly.

import type { Grid } from "../grid";
import type { Step, TraceMeta } from "../trace";
import { LABEL, PAGE, STAGE, type Tone, clock, narrow, surface, text, whole } from "./canvas";

// The palette of the surface being drawn on: the night stage for the heartbeat, the page for the charts.
let T: Tone = PAGE;

interface Plot {
  x: number;
  y: number;
  w: number;
  h: number;
}

function path(ctx: CanvasRenderingContext2D, plot: Plot, values: number[], top: number, close = false): void {
  ctx.beginPath();
  values.forEach((value, k) => {
    const x = plot.x + (values.length > 1 ? (k / (values.length - 1)) * plot.w : 0);
    const y = plot.y + plot.h * (1 - Math.min(1, value / top));
    if (k === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  if (close) {
    ctx.lineTo(plot.x + plot.w, plot.y + plot.h);
    ctx.lineTo(plot.x, plot.y + plot.h);
    ctx.closePath();
  }
}

/** Mark midnights along the bottom of a plot, and noon when there is room. */
function timeAxis(ctx: CanvasRenderingContext2D, plot: Plot, first: number, last: number): void {
  const span = Math.max(1, last - first);
  // Six-hour marks when their labels fit, days otherwise.
  const every = (plot.w * 360) / span >= 72 ? 360 : 1440;
  for (let minute = Math.ceil(first / every) * every; minute <= last; minute += every) {
    const x = plot.x + ((minute - first) / span) * plot.w;
    ctx.strokeStyle = T.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, plot.y);
    ctx.lineTo(x, plot.y + plot.h + 4);
    ctx.stroke();
    const label = every === 1440 ? clock(minute).slice(0, 3) : clock(minute);
    if (x < plot.x + plot.w - 56) text(ctx, label, x + 3, plot.y + plot.h + 15, LABEL, T.label);
  }
}

function levels(ctx: CanvasRenderingContext2D, plot: Plot, top: number): void {
  for (const share of [0.5, 1]) {
    const y = plot.y + plot.h * (1 - share);
    ctx.strokeStyle = T.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    text(ctx, whole(top * share), plot.x - 6, y + 4, LABEL, T.label, "right");
  }
  ctx.strokeStyle = T.ink;
  ctx.beginPath();
  ctx.moveTo(plot.x, plot.y + plot.h);
  ctx.lineTo(plot.x + plot.w, plot.y + plot.h);
  ctx.stroke();
}

/** A round number at or above a value, for the top of an axis. */
function ceiling(value: number): number {
  const scale = 10 ** Math.floor(Math.log10(Math.max(1, value)));
  return [1, 2, 2.5, 5, 10].map((m) => m * scale).find((candidate) => candidate >= value) ?? value;
}

/**
 * The heartbeat: vehicles arriving at the depot every five minutes, over what the grid delivered against
 * the site's limit, for the day up to now. Two bands on one time axis, each with its own labelled scale.
 */
export function drawPulse(canvas: HTMLCanvasElement, meta: TraceMeta, day: Step[]): void {
  T = STAGE;
  // Never shorter than 160 units, so both bands stay readable on a mid-sized screen.
  const wide = Math.max(canvas.clientWidth || 800, 620);
  const { ctx, w, h } = narrow(canvas) ? surface(canvas, 0.36, 470) : surface(canvas, Math.max(0.17, 160 / wide), 620);
  if (day.length < 2) return;
  const first = day[0].minute;
  const last = day[day.length - 1].minute;
  const beat: Plot = { x: 16, y: 22, w: w - 32, h: (h - 90) * 0.5 };
  const power: Plot = { x: 16, y: beat.y + beat.h + 26, w: w - 32, h: h - beat.y - beat.h - 46 };
  const across = (minute: number) => beat.x + ((minute - first) / (last - first)) * beat.w;

  const most = Math.max(4, ...day.map((s) => s.arrivals));
  const bar = Math.max(1, beat.w / day.length - 1);
  ctx.fillStyle = T.ink;
  for (const step of day) {
    const tall = (step.arrivals / most) * beat.h;
    ctx.fillRect(across(step.minute) - bar, beat.y + beat.h - tall, bar, tall);
  }
  text(ctx, `Vehicles arriving every five minutes (most: ${most})`, beat.x, beat.y - 7, LABEL, T.label);

  const limit = meta.usable_kw ?? meta.site_limit_kw;
  ctx.fillStyle = T.energyFill;
  path(ctx, power, day.map((s) => s.grid_kw), limit * 1.12, true);
  ctx.fill();
  const limitY = power.y + power.h * (1 - 1 / 1.12);
  ctx.strokeStyle = T.limit;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  ctx.moveTo(power.x, limitY);
  ctx.lineTo(power.x + power.w, limitY);
  ctx.stroke();
  ctx.setLineDash([]);
  text(ctx, "Power from the grid", power.x, power.y - 7, LABEL, T.label);
  text(ctx, `usable ${whole(limit)} kW`, power.x + power.w, power.y - 7, LABEL, T.limit, "right");
  // The hours when energy costs most, shaded across both bands.
  let from: number | null = null;
  day.forEach((step, k) => {
    const peak = step.tariff === "peak";
    if (peak && from === null) from = step.minute;
    if (from !== null && (!peak || k === day.length - 1)) {
      const left = across(from);
      ctx.fillStyle = T.shade;
      ctx.fillRect(left, beat.y, across(step.minute) - left, power.y + power.h - beat.y);
      if (left > power.x + 150 && left < power.x + power.w - 250) text(ctx, "peak price", left + 4, power.y - 7, LABEL, T.label);
      from = null;
    }
  });
  timeAxis(ctx, { ...power, y: power.y + power.h, h: 0 }, first, last);
}

export interface Hour {
  minute: number;
  offered: number;
  served: number;
  onRoad: number;
  promised: number | null;
}

/** Add steps up into hours: rides are summed, vehicles on the road averaged. */
export function hourly(steps: Step[]): Hour[] {
  const hours = new Map<number, Step[]>();
  for (const step of steps) {
    const key = Math.floor((step.minute - 1) / 60);
    if (!hours.has(key)) hours.set(key, []);
    hours.get(key)!.push(step);
  }
  return [...hours.entries()]
    .filter(([, group]) => group.length >= 6)
    .map(([key, group]) => ({
      minute: key * 60,
      offered: (group.reduce((sum, s) => sum + s.offered, 0) * 12) / group.length,
      served: (group.reduce((sum, s) => sum + s.served, 0) * 12) / group.length,
      onRoad: group.reduce((sum, s) => sum + s.on_road, 0) / group.length,
      promised: group[group.length - 1].promised,
    }));
}

const SIDE = { left: 52, right: 16, top: 30, bottom: 22 };

function plotOf(w: number, h: number): Plot {
  return { x: SIDE.left, y: SIDE.top, w: w - SIDE.left - SIDE.right, h: h - SIDE.top - SIDE.bottom };
}

function key(ctx: CanvasRenderingContext2D, entries: [string, string, boolean][], x: number, y: number): void {
  for (const [label, color, dashed] of entries) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dashed ? [5, 4] : []);
    ctx.beginPath();
    ctx.moveTo(x, y - 4);
    ctx.lineTo(x + 18, y - 4);
    ctx.stroke();
    ctx.setLineDash([]);
    text(ctx, label, x + 23, y, LABEL, T.label);
    x += 23 + ctx.measureText(label).width + 16;
  }
}

function marker(ctx: CanvasRenderingContext2D, plot: Plot, hours: Hour[], now: number | null): void {
  if (now === null || hours.length < 2) return;
  const first = hours[0].minute;
  const last = hours[hours.length - 1].minute;
  const x = plot.x + ((Math.min(last, Math.max(first, now)) - first) / (last - first)) * plot.w;
  ctx.strokeStyle = T.ink;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, plot.y);
  ctx.lineTo(x, plot.y + plot.h);
  ctx.stroke();
}

/** Rides offered and served per hour. The red between them is rides lost. */
export function drawRides(canvas: HTMLCanvasElement, hours: Hour[], other: Hour[] | null, otherName: string, now: number | null): void {
  T = PAGE;
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  if (hours.length < 2) return;
  const plot = plotOf(w, h);
  const top = ceiling(Math.max(...hours.map((hour) => hour.offered)));
  levels(ctx, plot, top);
  timeAxis(ctx, plot, hours[0].minute, hours[hours.length - 1].minute);
  // Lost rides: the offered area in red, with the served area drawn over it.
  ctx.fillStyle = T.lostFill;
  path(ctx, plot, hours.map((hour) => hour.offered), top, true);
  ctx.fill();
  ctx.fillStyle = T.energyFill;
  path(ctx, plot, hours.map((hour) => hour.served), top, true);
  ctx.fill();
  ctx.strokeStyle = T.energyLine;
  ctx.lineWidth = 2;
  path(ctx, plot, hours.map((hour) => hour.served), top);
  ctx.stroke();
  ctx.strokeStyle = T.label;
  ctx.lineWidth = 1.5;
  path(ctx, plot, hours.map((hour) => hour.offered), top);
  ctx.stroke();
  const entries: [string, string, boolean][] = [["offered", T.label, false], ["served", T.energyLine, false], ["lost", T.limit, false]];
  if (other && other.length === hours.length) {
    ctx.strokeStyle = T.ink;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 4]);
    path(ctx, plot, other.map((hour) => hour.served), top);
    ctx.stroke();
    ctx.setLineDash([]);
    entries.push([narrow(canvas) ? "other rule" : `served if ${otherName}`, T.ink, true]);
  }
  key(ctx, entries, plot.x, 14);
  marker(ctx, plot, hours, now);
}

/** Vehicles on the road per hour, against the fleet and, where a plan made one, its promise. */
export function drawRoad(canvas: HTMLCanvasElement, hours: Hour[], fleet: number, now: number | null): void {
  T = PAGE;
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  if (hours.length < 2) return;
  const plot = plotOf(w, h);
  levels(ctx, plot, fleet);
  timeAxis(ctx, plot, hours[0].minute, hours[hours.length - 1].minute);
  ctx.fillStyle = T.roadFill;
  path(ctx, plot, hours.map((hour) => hour.onRoad), fleet, true);
  ctx.fill();
  ctx.strokeStyle = T.road;
  ctx.lineWidth = 2;
  path(ctx, plot, hours.map((hour) => hour.onRoad), fleet);
  ctx.stroke();
  const entries: [string, string, boolean][] = [["on the road", T.road, false]];
  if (hours.some((hour) => hour.promised !== null)) {
    ctx.strokeStyle = T.ink;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 4]);
    path(ctx, plot, hours.map((hour) => hour.promised ?? hour.onRoad), fleet);
    ctx.stroke();
    ctx.setLineDash([]);
    entries.push(["promised by the plan", T.ink, true]);
  }
  key(ctx, entries, plot.x, 14);
  text(ctx, `fleet of ${whole(fleet)}`, plot.x + plot.w, 14, LABEL, T.label, "right");
  marker(ctx, plot, hours, now);
}

export interface Outlook {
  minute: number;
  forecast: number;
  upper: number;
  actual: number;
}

/**
 * Pair each forecast with what then happened. A step carries the forecast for the hour that starts one
 * hour after it, so the truth is the rides offered over the twelve steps that begin twelve steps later.
 * Each pair is placed at the hour it is about.
 */
export function outlook(steps: Step[], phase = 0): Outlook[] {
  const out: Outlook[] = [];
  // Hours are counted from the clock, not from wherever the list happens to begin: a list that has lost
  // steps off its front would otherwise pair each forecast with rides from two different hours. `phase`
  // is the minute past the hour a step is stamped with when it is the first of its hour: 0 for recordings,
  // which stamp a step at its start, and the step's length for the live depot, which stamps it at its end.
  let first = steps.findIndex((step) => step.minute % 60 === phase);
  if (first < 0) first = 0;
  for (let k = first; k + 24 <= steps.length; k += 12) {
    let actual = 0;
    for (let j = 12; j < 24; j++) actual += steps[k + j].offered;
    out.push({ minute: steps[k + 12].minute, forecast: steps[k].forecast, upper: steps[k].forecast_upper, actual });
  }
  return out;
}

/** Error as a share of rides, and how often rides stayed under the upper bound. */
export function outlookScore(hours: Outlook[]): { error: number; held: number } {
  const total = hours.reduce((sum, h) => sum + h.actual, 0);
  const missed = hours.reduce((sum, h) => sum + Math.abs(h.actual - h.forecast), 0);
  const held = hours.filter((h) => h.actual <= h.upper).length;
  return { error: total > 0 ? missed / total : NaN, held: hours.length > 0 ? held / hours.length : NaN };
}

/** The forecast for each coming hour, its upper bound, and the rides that came. */
export function drawOutlook(canvas: HTMLCanvasElement, hours: Outlook[]): void {
  T = PAGE;
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  if (hours.length < 2) return;
  const plot = plotOf(w, h);
  const top = ceiling(Math.max(...hours.map((hour) => Math.max(hour.upper, hour.actual))));
  levels(ctx, plot, top);
  timeAxis(ctx, plot, hours[0].minute, hours[hours.length - 1].minute);
  // The room between the forecast and its upper bound: what the plan keeps in hand.
  ctx.fillStyle = T.rule;
  path(ctx, plot, hours.map((hour) => hour.upper), top, true);
  ctx.fill();
  ctx.fillStyle = "#ffffff";
  path(ctx, plot, hours.map((hour) => hour.forecast), top, true);
  ctx.fill();
  ctx.strokeStyle = T.ink;
  ctx.lineWidth = 2;
  path(ctx, plot, hours.map((hour) => hour.forecast), top);
  ctx.stroke();
  ctx.strokeStyle = T.road;
  ctx.lineWidth = 2;
  path(ctx, plot, hours.map((hour) => hour.actual), top);
  ctx.stroke();
  levels(ctx, plot, top);
  key(ctx, [["forecast", T.ink, false], ["rides that came", T.road, false], ["up to the upper bound", "#c3ccd8", false]], plot.x, 14);
}

/**
 * California's net demand through the stretch shown, with the depot's own draw as a ribbon beneath it:
 * the brighter the ribbon, the more of its limit the depot was drawing in that hour.
 */
export function drawGridStrain(canvas: HTMLCanvasElement, grid: Grid, steps: Step[], limitKw: number): void {
  T = PAGE;
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  if (steps.length < 24) return;
  const plot = plotOf(w, h - 22);
  const net = steps.map((step) => Math.max(0, grid.netDemand(step.minute)) / 1000);
  const top = ceiling(Math.max(...net));
  levels(ctx, plot, top);
  // The hardest quarter of the week, shaded behind the curve.
  const hard = grid.hardFrom / 1000;
  ctx.fillStyle = "rgba(234, 0, 0, 0.08)";
  ctx.fillRect(plot.x, plot.y, plot.w, plot.h * (1 - hard / top));
  ctx.fillStyle = "#dfe4eb";
  path(ctx, plot, net, top, true);
  ctx.fill();
  ctx.strokeStyle = T.label;
  ctx.lineWidth = 2;
  path(ctx, plot, net, top);
  ctx.stroke();
  const ribbon = plot.y + plot.h + 26;
  const each = plot.w / steps.length;
  steps.forEach((step, k) => {
    ctx.globalAlpha = Math.min(1, step.grid_kw / limitKw);
    ctx.fillStyle = T.energyLine;
    ctx.fillRect(plot.x + k * each, ribbon, each + 0.5, 12);
  });
  ctx.globalAlpha = 1;
  timeAxis(ctx, plot, steps[0].minute, steps[steps.length - 1].minute);
  key(ctx, [["grid net demand, GW", T.label, false], ["depot draw, in the ribbon", T.energyLine, false]], plot.x, 14);
  if (!narrow(canvas)) text(ctx, "red band: hardest quarter of the week", plot.x + plot.w, 14, LABEL, T.limit, "right");
}

/** The hour under the pointer, for the line of text beneath a chart. */
export function hourAt(canvas: HTMLCanvasElement, hours: Hour[], clientX: number): Hour | null {
  if (hours.length < 2) return null;
  const box = canvas.getBoundingClientRect();
  const units = Math.max(box.width, 420);
  const share = (((clientX - box.left) / box.width) * units - SIDE.left) / (units - SIDE.left - SIDE.right);
  if (share < 0 || share > 1) return null;
  return hours[Math.round(share * (hours.length - 1))];
}
