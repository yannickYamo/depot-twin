// The plan, hour by hour: what model predictive control looks like from the outside. Each hour the
// controller draws a plan for the next 24, acts on its first hour, and draws it again an hour later from
// where the fleet then stands. Shown as the current plan over the ghosts of the plans before it.

import { account, type Plan, type Step } from "../trace";
import { LABEL, PAGE as T, clock, percent, surface, text, whole } from "./canvas";

/** The plan in force at a step, and the ones made just before it. */
export function plansAt(plans: Plan[], index: number, ghosts = 3): { current: Plan | null; before: Plan[] } {
  const made = plans.filter((plan) => plan.step <= index);
  if (made.length === 0) return { current: null, before: [] };
  return { current: made[made.length - 1], before: made.slice(Math.max(0, made.length - 1 - ghosts), made.length - 1) };
}

/** Arrivals at the depot in each hour from a step on, for as many hours as have happened. */
function arrivalsByHour(steps: Step[], from: number, upto: number): number[] {
  const out: number[] = [];
  for (let k = from; k + 12 <= upto + 1; k += 12) {
    let sum = 0;
    for (let j = k; j < k + 12; j++) sum += steps[j].arrivals;
    out.push(sum);
  }
  return out;
}

/** A row of named colours at the top of a chart, each entry set after the width of the one before. */
function legend(ctx: CanvasRenderingContext2D, x: number, entries: [string, string][]): void {
  ctx.font = LABEL;
  for (const [label, color] of entries) {
    text(ctx, label, x, 14, LABEL, color);
    x += ctx.measureText(label).width + 18;
  }
}

function frame(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, top: number, unit: string): void {
  for (const share of [0, 0.5, 1]) {
    const y = plot.y + plot.h * (1 - share);
    ctx.strokeStyle = share === 0 ? T.ink : T.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    if (share > 0) text(ctx, `${whole(top * share)}${unit}`, plot.x - 6, y + 4, LABEL, T.label, "right");
  }
  for (const h of [0, 6, 12, 18, 24]) {
    text(ctx, h === 0 ? "now" : `+${h} h`, plot.x + (h / 24) * plot.w, plot.y + plot.h + 16, LABEL, T.label, h === 24 ? "right" : h === 0 ? "left" : "center");
  }
}

/** Visits the plan calls for in each of the next 24 hours, over the plans made before, with what has happened. */
export function drawPlannedVisits(canvas: HTMLCanvasElement, steps: Step[], plans: Plan[], index: number): void {
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  const { current, before } = plansAt(plans, index);
  if (!current) return;
  const plot = { x: 52, y: 30, w: w - 68, h: h - 56 };
  const top = Math.max(10, Math.ceil(Math.max(...current.visits, ...before.flatMap((p) => p.visits)) / 10) * 10);
  frame(ctx, plot, top, "");
  const slot = plot.w / 24;
  const up = (v: number) => plot.y + plot.h * (1 - v / top);
  // Earlier plans, each shifted by the hours that have passed since it was made, so hours line up.
  before.forEach((plan, k) => {
    const shift = Math.round((current.minute - plan.minute) / 60);
    ctx.strokeStyle = T.rule;
    ctx.lineWidth = 1 + k * 0.5;
    ctx.beginPath();
    plan.visits.forEach((v, t) => {
      const x = plot.x + (t - shift + 0.5) * slot;
      if (t - shift < 0) return;
      ctx.lineTo(x, up(v));
    });
    ctx.stroke();
  });
  ctx.fillStyle = T.road;
  current.visits.forEach((v, t) => ctx.fillRect(plot.x + t * slot + 2, up(v), slot - 4, plot.y + plot.h - up(v)));
  // What has happened since this plan was made: arrivals in each full hour so far.
  const happened = arrivalsByHour(steps, current.step + 1, index);
  ctx.fillStyle = T.ink;
  happened.forEach((v, t) => ctx.fillRect(plot.x + t * slot + slot / 2 - 2, up(v), 4, plot.y + plot.h - up(v)));
  legend(ctx, plot.x, [[`planned at ${clock(current.minute)}`, T.road], ["the plans before it", T.label], ["what came", T.ink]]);
}

/** Vehicles the plan expects on the road each coming hour, over what the fleet has done so far. */
export function drawPlannedRoad(canvas: HTMLCanvasElement, steps: Step[], plans: Plan[], index: number, fleet: number): void {
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  const { current } = plansAt(plans, index);
  if (!current) return;
  const plot = { x: 52, y: 30, w: w - 68, h: h - 56 };
  frame(ctx, plot, fleet, "");
  const slot = plot.w / 24;
  const up = (v: number) => plot.y + plot.h * (1 - v / fleet);
  ctx.strokeStyle = T.ink;
  ctx.lineWidth = 2;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  current.on_road.forEach((v, t) => (t === 0 ? ctx.moveTo(plot.x + (t + 0.5) * slot, up(v)) : ctx.lineTo(plot.x + (t + 0.5) * slot, up(v))));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = T.limit;
  ctx.beginPath();
  ctx.moveTo(plot.x, up(current.committed));
  ctx.lineTo(plot.x + slot, up(current.committed));
  ctx.stroke();
  ctx.strokeStyle = T.road;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let k = current.step; k <= index; k++) {
    const x = plot.x + ((k - current.step) / 12) * slot;
    k === current.step ? ctx.moveTo(x, up(steps[k].on_road)) : ctx.lineTo(x, up(steps[k].on_road));
  }
  ctx.stroke();
  legend(ctx, plot.x, [["the plan expects", T.ink], ["on the road so far", T.road], ["promised this hour", T.limit]]);
}

/** The plan's run against a simple rule on the same days, after the first day. */
export function compareRuns(plan: Step[], simple: Step[]): string {
  const from = 288;
  const a = account(plan.slice(from));
  const b = account(simple.slice(from));
  const row = (name: string, mine: string, theirs: string) => `<tr><th scope="row">${name}</th><td>${mine}</td><td>${theirs}</td></tr>`;
  return (
    `<table><thead><tr><td></td><th scope="col">The plan</th><th scope="col">Fixed threshold</th></tr></thead><tbody>` +
    row("Rides served", percent(a.served), percent(b.served)) +
    row("Energy, per kWh", `$${a.costPerKwh.toFixed(3)}`, `$${b.costPerKwh.toFixed(3)}`) +
    row("Energy bought in peak-price hours", percent(a.peakShare), percent(b.peakShare)) +
    row("Unevenness of grid draw", a.variation.toFixed(2), b.variation.toFixed(2)) +
    `</tbody></table>`
  );
}
