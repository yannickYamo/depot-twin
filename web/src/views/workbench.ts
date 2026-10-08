// The model workbench: the same forecast built many ways, each scored on held-out days and each handed
// to the plan. The visitor turns one dial at a time and reads two things side by side: what the change
// did to the model, and what it did to the depot.
//
// Nothing is trained or simulated here. Every figure was produced by the Python model and written to
// models.json by `depot-twin data models`.

import { LABEL, PAGE as T, percent, surface, text, whole } from "./canvas";
import { drawOutlook, type Outlook } from "./charts";

interface HorizonScore {
  error: number;
  same_hour_last_week: number;
  upper_bound_held: number;
  by_hour: number[];
}

interface Variant {
  dial: string;
  label: string;
  note: string;
  horizons: Record<string, HorizonScore>;
  trees?: number;
  training_rows?: number;
  curve?: { trees: number[]; train: number[]; validation: number[] };
  importance?: [string, number][];
  days: { mean: number[]; upper: number[]; actual: (number | null)[] };
  reserve: { vehicles_held_in_reserve: number; rides_above_the_bound_per_day: number; bound_above_forecast: number };
  decision: {
    served: number; promises_kept: number; cost_per_kwh: number; bound_held_in_run: number; guard_took_over: number;
    rides_offered_per_day?: number; kwh_per_day?: number; peak_price_share?: number;
  };
  trace: string | null;
}

/** Mean rides an hour on the fortnight, from the chart's own arrays. */
function meanRides(variant: Variant): number {
  const actual = variant.days.actual.filter((v): v is number => v !== null);
  return actual.length ? actual.reduce((a, b) => a + b, 0) / actual.length : 0;
}

/** The error a perfect forecast of the hour's mean would still show, from the counting noise of rides: E|X − μ| / μ for a Poisson count. */
function noiseFloor(variant: Variant): number {
  const mean = meanRides(variant);
  return mean > 0 ? Math.sqrt(2 / Math.PI) / Math.sqrt(mean) : 0;
}

/** One-hour error on the fortnight the chart shows and the depot is run on, from the arrays the chart draws. */
function fortnightError(variant: Variant): number {
  let miss = 0;
  let total = 0;
  variant.days.actual.forEach((actual, k) => {
    if (actual === null) return;
    miss += Math.abs(actual - variant.days.mean[k]);
    total += actual;
  });
  return total > 0 ? miss / total : 0;
}

interface Frontier { nominal: number; achieved: number; reserve: number; width: number }
interface Trust {
  split: Record<string, { from: string; to: string; rows?: number }>;
  slices: { slice: string; n: number; model: number; last_week: number }[];
  importance: { feature: string; gain: number; permutation_loss: number }[];
  frontier_sf: Frontier[];
  cities: Record<string, Record<string, { error: number; reserve_at_95: number | null; frontier: Frontier[] }>>;
  sf_workbench: Record<string, { error: number; reserve_at_nominal_95: number }>;
  sf?: Record<string, { error: number; reserve_at_95: number | null; frontier: Frontier[] }>;
  variants?: Record<string, {
    error: number; reserve_at_95: number | null; frontier: Frontier[];
    slices: { slice: string; n: number; model: number; last_week: number }[];
    importance?: { feature: string; gain: number; permutation_loss: number }[];
    card: { kind: string; target: string; trees: number | null; rows: number | null; features: number | null };
  }>;
  card: { algorithm: string; objective: string; rows: number; trees: number; features: number; horizons: number[]; holdout_days: number; stop_days: number; calibration_days: number };
}

interface Workbench {
  start: string;
  fleet: number;
  /** What a day's figures are worth, for the money view. */
  money?: { fare_per_ride: number; lost_ride_cost: number; vehicle_cost_per_year: number };
  /** The depot the variants ran on, for the arithmetic of why rides do not move. */
  depot?: { chargers: number; ride_minutes: number; rides_per_vehicle_day: number; site_limit_kw: number; usable_kw: number };
  dials: { key: string; name: string; reference: string }[];
  variants: Record<string, Variant>;
}

const FEATURE_NAMES: Record<string, string> = {
  running_vs_last_week: "this week against last, so far",
  target_slot_last_day: "the same hour yesterday",
  target_slot_last_week: "the same hour last week",
  rate_now: "rides in the last hour",
  rate_1h_ago: "rides an hour ago",
  rate_24h_ago: "rides a day ago",
  rate_7d_ago: "rides a week ago",
  rate_mean_24h: "average over the last day",
  rate_max_24h: "busiest hour of the last day",
  rate_min_24h: "quietest hour of the last day",
  step_std_1h: "unevenness within the last hour",
  hour: "hour of the day",
  weekday: "day of the week",
  weekend: "weekend",
  holiday: "public holiday",
  month: "month",
  minute_of_day: "minute of the day",
  temperature_now: "temperature now",
  temperature_target: "temperature forecast",
  rain_now: "rain now",
  rain_target: "rain forecast",
};

function figure(label: string, value: string, note: string): string {
  return `<div><dt>${label}</dt><dd>${value}<small>${note}</small></dd></div>`;
}

/** Error against vehicles held at matched reliability: three forecasts of one city, lower left better. */
function drawScatter(canvas: HTMLCanvasElement, arms: { name: string; error: number; reserve: number | null; color: string }[]): void {
  const { ctx, w, h } = surface(canvas, 0.38, 520);
  const plot = { x: 56, y: 18, w: w - 76, h: h - 54 };
  const shown = arms.filter((a) => a.reserve !== null) as { name: string; error: number; reserve: number; color: string }[];
  if (shown.length === 0) return;
  const maxErr = Math.ceil(Math.max(...shown.map((a) => a.error)) * 20) / 20 + 0.02;
  const maxRes = Math.ceil(Math.max(...shown.map((a) => a.reserve)) / 20) * 20 + 10;
  const across = (e: number) => plot.x + (e / maxErr) * plot.w;
  const up = (r: number) => plot.y + plot.h * (1 - r / maxRes);
  ctx.strokeStyle = T.rule; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(plot.x, plot.y); ctx.lineTo(plot.x, plot.y + plot.h); ctx.lineTo(plot.x + plot.w, plot.y + plot.h); ctx.stroke();
  for (let e = 0.05; e < maxErr; e += 0.05) text(ctx, percent(e).replace(".0", ""), across(e), plot.y + plot.h + 16, LABEL, T.label, "center");
  for (let r = 0; r <= maxRes; r += maxRes > 100 ? 50 : 20) text(ctx, whole(r), plot.x - 8, up(r) + 4, LABEL, T.label, "right");
  text(ctx, "forecast error, one hour ahead", plot.x + plot.w, plot.y + plot.h + 30, LABEL, T.label, "right");
  text(ctx, "vehicles held at 95% reliability", plot.x + 8, plot.y + 4, LABEL, T.label);
  for (const a of shown) {
    const x = across(a.error), y = up(a.reserve);
    ctx.fillStyle = a.color;
    ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.fill();
    const label = `${a.name}: ${percent(a.error)}, ${whole(a.reserve)}`;
    if (x > plot.x + plot.w * 0.65) text(ctx, label, x - 12, y + 4, LABEL, T.ink, "right");
    else text(ctx, label, x + 12, y + 4, LABEL, T.ink);
  }
}

/** Requested against achieved coverage for the reference bound on San Francisco and the pretrained one on Chicago, with the reserve beside each point. */
function drawCalibration(canvas: HTMLCanvasElement, trust: Trust): void {
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  const plot = { x: 52, y: 20, w: w - 72, h: h - 52 };
  const lo = 0.84, hi = 1.0;
  const across = (v: number) => plot.x + ((v - lo) / (hi - lo)) * plot.w;
  const up = (v: number) => plot.y + plot.h * (1 - (v - lo) / (hi - lo));
  ctx.strokeStyle = T.rule; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(across(lo), up(lo)); ctx.lineTo(across(hi), up(hi)); ctx.stroke();
  for (const v of [0.85, 0.9, 0.95, 1.0]) {
    text(ctx, percent(v).replace(".0", ""), across(v), plot.y + plot.h + 16, LABEL, T.label, "center");
    text(ctx, percent(v).replace(".0", ""), plot.x - 8, up(v) + 4, LABEL, T.label, "right");
  }
  text(ctx, "asked", plot.x + plot.w, plot.y + plot.h + 30, LABEL, T.label, "right");
  text(ctx, "held", plot.x - 8, plot.y - 6, LABEL, T.label, "right");
  const series: [Frontier[] | undefined, string, string][] = [[trust.frontier_sf, "#006fee", "San Francisco, trained here"], [trust.cities.chicago?.chronos?.frontier, "#007068", "Chicago, pretrained"]];
  series.forEach(([points, color, name], k) => {
    if (!points) return;
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((p, i) => { const x = across(p.nominal), y = up(Math.max(lo, p.achieved)); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
    ctx.stroke();
    for (const p of points) {
      const x = across(p.nominal), y = up(Math.max(lo, p.achieved));
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
      if (p.nominal !== 0.99) text(ctx, whole(p.reserve), x + 7, y + (k === 0 ? -6 : 14), LABEL, color);
    }
    text(ctx, name, plot.x + 4, plot.y + 14 + k * 16, LABEL, color);
  });
}

/** Error on training rows and on validation rows as trees are added, on a log scale of trees. */
function drawCurve(canvas: HTMLCanvasElement, variant: Variant, longest: Variant): void {
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  const curve = variant.curve ?? longest.curve;
  if (!curve) return;
  const plot = { x: 52, y: 30, w: w - 68, h: h - 56 };
  const top = Math.ceil(Math.max(...curve.train, ...curve.validation, ...(longest.curve?.validation ?? [])) * 20) / 20;
  const across = (trees: number) => plot.x + (Math.log(trees) / Math.log(3000)) * plot.w;
  const up = (error: number) => plot.y + plot.h * (1 - error / top);
  for (const share of [0, 0.5, 1]) {
    ctx.strokeStyle = share === 0 ? T.ink : T.rule;
    ctx.beginPath();
    ctx.moveTo(plot.x, up(top * share));
    ctx.lineTo(plot.x + plot.w, up(top * share));
    ctx.stroke();
    if (share > 0) text(ctx, percent(top * share).replace(".0", ""), plot.x - 6, up(top * share) + 4, LABEL, T.label, "right");
  }
  for (const trees of [1, 10, 100, 1000]) text(ctx, whole(trees), across(trees), plot.y + plot.h + 16, LABEL, T.label, "center");
  text(ctx, "3,000 trees", plot.x + plot.w, plot.y + plot.h + 16, LABEL, T.label, "right");
  const line = (trees: number[], errors: number[], color: string, width: number, dashed = false) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dashed ? [4, 4] : []);
    ctx.beginPath();
    trees.forEach((k, i) => (i === 0 ? ctx.moveTo(across(k), up(errors[i])) : ctx.lineTo(across(k), up(errors[i]))));
    ctx.stroke();
    ctx.setLineDash([]);
  };
  // The run with no early stopping, drawn faintly, shows where each line goes if training carries on.
  if (longest.curve && curve !== longest.curve) {
    line(longest.curve.trees, longest.curve.validation, T.rule, 2);
    line(longest.curve.trees, longest.curve.train, T.rule, 2, true);
  }
  line(curve.trees, curve.train, T.label, 2, true);
  line(curve.trees, curve.validation, T.road, 2);
  const used = Math.min(variant.trees ?? curve.trees[curve.trees.length - 1], 3000);
  ctx.strokeStyle = T.ink;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(across(used), plot.y);
  ctx.lineTo(across(used), plot.y + plot.h);
  ctx.stroke();
  text(ctx, `${whole(used)} trees used`, Math.min(across(used) + 6, plot.x + plot.w - 96), plot.y + 12, LABEL, T.ink);
  text(ctx, "validation", plot.x, 14, LABEL, T.road);
  text(ctx, "training (dashed)", plot.x + 74, 14, LABEL, T.label);
}

/** Bars: one group for each of a few named values, the model's bar beside the naive rule's. */
function drawBars(canvas: HTMLCanvasElement, names: string[], model: number[], naive: number[] | null): void {
  const { ctx, w, h } = surface(canvas, 0.42, 420);
  const plot = { x: 52, y: 30, w: w - 68, h: h - 56 };
  const top = Math.ceil(Math.max(...model, ...(naive ?? [])) * 20) / 20;
  const up = (value: number) => plot.y + plot.h * (1 - value / top);
  for (const share of [0, 0.5, 1]) {
    ctx.strokeStyle = share === 0 ? T.ink : T.rule;
    ctx.beginPath();
    ctx.moveTo(plot.x, up(top * share));
    ctx.lineTo(plot.x + plot.w, up(top * share));
    ctx.stroke();
    if (share > 0) text(ctx, percent(top * share).replace(".0", ""), plot.x - 6, up(top * share) + 4, LABEL, T.label, "right");
  }
  const group = plot.w / names.length;
  const bar = Math.min(34, (group - 8) / (naive ? 2 : 1) - 2);
  names.forEach((name, k) => {
    const middle = plot.x + group * (k + 0.5);
    const left = naive ? middle - bar - 1 : middle - bar / 2;
    ctx.fillStyle = T.road;
    ctx.fillRect(left, up(model[k]), bar, plot.y + plot.h - up(model[k]));
    if (naive) {
      ctx.fillStyle = "#c3ccd8";
      ctx.fillRect(middle + 1, up(naive[k]), bar, plot.y + plot.h - up(naive[k]));
    }
    if (name) text(ctx, name, middle, plot.y + plot.h + 16, LABEL, T.label, "center");
  });
  text(ctx, "this model", plot.x, 14, LABEL, T.road);
  if (naive) text(ctx, "same hour last week", plot.x + 80, 14, LABEL, T.label);
}

/** The train, stop, calibrate and holdout blocks as one time line, widths by days. */
function splitTimeline(trust: Trust): string {
  const order: [string, string][] = [["train", "Train"], ["stop", "Stop"], ["calibrate", "Bound"], ["holdout", "Test, once"]];
  const days = (k: string) => (new Date(trust.split[k].to).getTime() - new Date(trust.split[k].from).getTime()) / 86400000 + 1;
  const total = order.reduce((sum, [k]) => sum + days(k), 0);
  const blocks = order.map(([k, name]) => {
    const span = trust.split[k];
    const month = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "2-digit" });
    const w = Math.max(17, (days(k) / total) * 100);
    return `<div class="split-block split-${k}" style="flex: ${w} 1 0"><b>${name}</b><span>${month(span.from)} to ${month(span.to)}</span><small>${whole(span.rows ?? 0)} rows</small></div>`;
  });
  return `<div class="split" role="img" aria-label="Training, stopping, calibration and held-out blocks in time order">${blocks.join("")}</div>`;
}

/** Error by slice on the 60 held-out days, the model against last week. */
type Slice = { slice: string; n: number; model: number; last_week: number };
type Importance = { feature: string; gain: number; permutation_loss: number };
type Card = { kind: string; target: string; trees: number | null; rows: number | null; features: number | null };

function slicesTable(slices: Slice[]): string {
  const rows = slices.map((r) => {
    const delta = r.model - r.last_week;
    return `<tr><th scope="row">${r.slice}</th><td>${whole(r.n)}</td><td>${percent(r.model)}</td><td>${percent(r.last_week)}</td><td class="${delta < 0 ? "good" : "bad"}">${delta < 0 ? "−" : "+"}${(Math.abs(delta) * 100).toFixed(1)}</td></tr>`;
  });
  return `<table class="account slices"><thead><tr><td></td><th scope="col">Five-minute rows</th><th scope="col">This model</th><th scope="col">Last week</th><th scope="col">Points</th></tr></thead><tbody>${rows.join("")}</tbody></table>
    <p class="wb-note">The 60 held-out days, one hour ahead. Where this model is least ahead of last week it is least needed; where it falls behind, it is not to be trusted alone.</p>`;
}

/** What a model leans on: the error rise when a feature is shuffled first, XGBoost's gain beside it. Five rows, the rest on request. */
function importanceTable(importance: Importance[]): string {
  const row = (r: Importance) => `<tr><th scope="row">${FEATURE_NAMES[r.feature] ?? r.feature}</th><td>+${(r.permutation_loss * 100).toFixed(1)} pts</td><td>${percent(r.gain).replace(".0", "")}</td></tr>`;
  const head = `<thead><tr><td></td><th scope="col">Error rise when shuffled</th><th scope="col">Gain share</th></tr></thead>`;
  const top = importance.slice(0, 5).map(row).join("");
  const rest = importance.slice(5).map(row).join("");
  return `<table class="account slices">${head}<tbody>${top}</tbody></table>` +
    (rest ? `<details class="fold small"><summary>All ${importance.length} features</summary><table class="account slices">${head}<tbody>${rest}</tbody></table></details>` : "");
}

/** The chosen model on a card, the reference beside it, with what neither is. */
function modelCard(trust: Trust, mine: Card | undefined, name: string, isRef: boolean): string {
  const c = trust.card;
  const row = (k: string, v: string) => `<div><dt>${k}</dt><dd>${v}</dd></div>`;
  const algorithm = (card?: Card) => !card ? c.algorithm : card.kind === "pretrained" ? "Chronos-2, pretrained, no local fitting, univariate" : card.kind === "last_week" ? "No model: the same hour last week" : card.kind === "no_local" ? "XGBoost pooled over three cities, this one held out" : c.algorithm;
  const own = mine && !isRef
    ? row("Selected", name.replace(/^./, (ch) => ch.toUpperCase())) + row("Algorithm", algorithm(mine)) + row("Target", mine.target) +
      (mine.trees ? row("Trees", whole(mine.trees)) : "") + (mine.rows ? row("Training rows", whole(mine.rows)) : "") + (mine.features ? row("Features", String(mine.features)) : "") +
      row("Compared with", `the reference: ${c.objective.replace("squared error on the ", "")}, ${whole(c.trees)} trees, ${whole(c.rows)} rows`)
    : row("Algorithm", c.algorithm) + row("Objective", c.objective) + row("Training rows", whole(c.rows)) + row("Trees", whole(c.trees)) + row("Features", String(c.features));
  return `<dl class="card">
      ${own}
      ${row("Horizons", c.horizons.map((h) => `${h} h`).join(", "))}${row("Split", `chronological: stop ${c.stop_days} days, bound ${c.calibration_days} days, test ${c.holdout_days} days`)}
      ${row("Baseline", "same hour last week")}${row("Score", "absolute error over rides served")}${row("What it is for", "the reserve the plan holds for its bound")}
    </dl>
    <p class="wb-note"><b>Not to be read as:</b> demand (rides served, not rides wanted); a robotaxi's demand (taxi and ride-hail records); a model for rare days (holidays are 288 of 17,257 held-out five-minute rows).</p>`;
}

export class WorkbenchView {
  private data: Workbench | null = null;
  private trust: Trust | null = null;
  private chosen = "reference";

  constructor(private readonly root: HTMLElement, private readonly replay: (trace: string, label: string) => void) {
    root.addEventListener("click", (event) => {
      const target = event.target as HTMLElement;
      const option = target.closest<HTMLElement>("[data-variant]");
      if (option) this.choose(option.dataset.variant!);
      if (target.id === "wb-replay" && this.data) {
        const variant = this.data.variants[this.chosen];
        if (variant.trace) this.replay(variant.trace, this.name(variant));
      }
    });
    window.addEventListener("resize", () => this.draw());
  }

  async show(): Promise<void> {
    if (!this.data) {
      try {
        this.data = (await (await fetch("models.json")).json()) as Workbench;
        this.trust = (await (await fetch("trust.json")).json().catch(() => null)) as Trust | null;
      } catch {
        this.root.innerHTML = `<p class="quiet">The model results could not be loaded. Check the connection and choose this mode again.</p>`;
        return;
      }
    }
    this.render();
  }

  private name(variant: Variant): string {
    if (!this.data || variant.dial === "reference") return "the reference model";
    const dial = this.data.dials.find((d) => d.key === variant.dial)!;
    return `${dial.name.toLowerCase()}: ${variant.label.toLowerCase()}`;
  }

  /** The dial that just went back to the reference because another one moved, if any. */
  private reset: string | null = null;

  private choose(ident: string): void {
    const before = this.data!.variants[this.chosen];
    const after = this.data!.variants[ident];
    this.reset = before.dial !== "reference" && after.dial !== before.dial ? before.dial : null;
    this.chosen = ident;
    this.render();
  }

  private dials(): string {
    const data = this.data!;
    const active = data.variants[this.chosen].dial;
    return data.dials.filter((dial) => dial.key !== "feed").map((dial) => {
      const options = Object.entries(data.variants).filter(([, v]) => v.dial === dial.key);
      const pill = (ident: string, label: string, on: boolean) =>
        `<button type="button" role="radio" aria-checked="${on}" data-variant="${ident}">${label}</button>`;
      const reference = pill("reference", dial.reference, active !== dial.key);
      const others = options.map(([ident, v]) => pill(ident, v.label, ident === this.chosen)).join("");
      return `<fieldset><legend>${dial.name}</legend><div class="options" role="radiogroup" aria-label="${dial.name}">${reference}${others}</div></fieldset>`;
    }).join("");
  }

  private toastTimer = 0;
  /** The city whose three forecasts the accuracy-against-reserve chart shows. */
  private city = "sf";

  /** The forecast feed, intact or broken, kept apart: it is a test of the plan, not a way to build a model. */
  private feedDial(): string {
    const data = this.data!;
    const dial = data.dials.find((d) => d.key === "feed");
    if (!dial) return "";
    const options = Object.entries(data.variants).filter(([, v]) => v.dial === "feed");
    const pill = (ident: string, label: string, on: boolean) => `<button type="button" role="radio" aria-checked="${on}" data-variant="${ident}">${label}</button>`;
    return `<p class="quiet">What the controller does when its forecast breaks mid-run.</p><div class="options" role="radiogroup" aria-label="${dial.name}">${pill("reference", dial.reference, data.variants[this.chosen].dial !== "feed")}${options.map(([ident, v]) => pill(ident, v.label, ident === this.chosen)).join("")}</div>`;
  }

  private render(): void {
    const data = this.data!;
    const trust = this.trust;
    const variant = data.variants[this.chosen];
    const reference = data.variants.reference;
    const isRef = this.chosen === "reference";
    const one = variant.horizons["1"];
    const lastWeek = data.variants.last_week?.horizons["1"].error ?? one.same_hour_last_week;
    const held = variant.reserve.vehicles_held_in_reserve;
    const delta = (value: number, ref: number, unit: string, digits = 1) =>
      isRef ? "" : Math.abs(value - ref) < 10 ** -(digits + 1) ? "no change" : `${value > ref ? "+" : "−"}${Math.abs(value - ref).toFixed(digits)}${unit} against the reference`;
    const gapLast = 100 * (lastWeek - one.error);
    const vsLast = `${Math.abs(gapLast).toFixed(1)} pts ${gapLast >= 0 ? "better" : "worse"} than last week`;
    const vsRef = isRef ? "" : ` · ${delta(100 * one.error, 100 * reference.horizons["1"].error, " pts")}`.replace(" against the reference", " vs reference");
    const headline =
      figure("Error, one hour ahead", percent(one.error), vsLast + vsRef) +
      figure("Vehicles held in reserve", whole(held), isRef ? "for the forecast's margin" : delta(held, reference.reserve.vehicles_held_in_reserve, "", 0)) +
      figure("Bound held", percent(one.upper_bound_held), "asked to hold 95% of hours") +
      figure("Error on the run's fortnight", percent(fortnightError(variant)), delta(100 * fortnightError(variant), 100 * fortnightError(reference), " pts"));
    const dec = variant.decision;
    const refDec = reference.decision;
    const depot =
      figure("Rides served", percent(dec.served), delta(100 * dec.served, 100 * refDec.served, " pts")) +
      figure("Reserve at the stated 95%", `${whole(held)} vehicles`, delta(held, reference.reserve.vehicles_held_in_reserve, "", 0)) +
      figure("Energy", `$${dec.cost_per_kwh.toFixed(3)}/kWh`, delta(dec.cost_per_kwh, refDec.cost_per_kwh, "", 3)) +
      figure("Bought at the peak price", percent(dec.peak_price_share ?? 0), delta(100 * (dec.peak_price_share ?? 0), 100 * (refDec.peak_price_share ?? 0), " pts"));
    const more =
      figure("Promises kept", percent(dec.promises_kept), delta(100 * dec.promises_kept, 100 * refDec.promises_kept, " pts")) +
      figure("Rides above the bound, a day", whole(variant.reserve.rides_above_the_bound_per_day), delta(variant.reserve.rides_above_the_bound_per_day, reference.reserve.rides_above_the_bound_per_day, "", 0)) +
      figure("Bound held in the run", percent(dec.bound_held_in_run), delta(100 * dec.bound_held_in_run, 100 * refDec.bound_held_in_run, " pts")) +
      figure("Guard took over", dec.guard_took_over > 0 ? "Yes" : "No", "a simple rule replaces the plan when the bound keeps breaking");
    const trained = variant.trees === undefined ? "" : ` ${whole(variant.trees)} trees on ${whole(variant.training_rows ?? 0)} rows.`;
    // The reference stops where its validation error stops improving; the other tree counts are fixed by hand.
    const stopsEarly = variant.dial !== "rounds" || this.chosen === "reference";
    const curveCopy = stopsEarly
      ? `Each round adds one tree. Training error (dashed) keeps falling; validation error stops improving at ${whole(variant.trees ?? reference.trees ?? 0)} trees, so training stops there.`
      : `Each round adds one tree. This variant is cut at ${whole(variant.trees ?? 0)} trees by hand; the reference stops at ${whole(reference.trees ?? 0)}, where its validation error stops improving. Training error (dashed) keeps falling either way.`;
    const validation = variant.curve ? Math.min(...variant.curve.validation) : null;
    const replay = variant.trace ? `<button type="button" id="wb-replay" class="solid">Replay this model's run on the depot floor</button>` : "";
    const mine = trust?.variants?.[this.chosen];
    const slices = mine?.slices ?? trust?.slices ?? null;
    const worst = slices ? slices.filter((r) => r.slice !== "All hours").sort((x, y) => (y.model - y.last_week) - (x.model - x.last_week))[0] : null;
    const strip = isRef
      ? `<p class="strip"><b>Selected: the reference.</b> Every figure below is the reference model's.</p>`
      : `<p class="strip"><b>Selected: ${this.name(variant)}.</b> Everything else at the reference. Error ${percent(one.error)} (${delta(100 * one.error, 100 * reference.horizons["1"].error, " pts").replace(" against the reference", "")}) · reserve at the stated 95% ${whole(held)} (${delta(held, reference.reserve.vehicles_held_in_reserve, "", 0).replace(" against the reference", "")}).</p>`;
    const scent = worst ? `${worst.slice.toLowerCase()}, ${worst.model > worst.last_week ? "behind" : "barely ahead of"} last week` : "";
    void slices;
    this.root.innerHTML = `
      ${this.reset ? `<div class="toast" role="status">Reset to the reference: one change at a time.</div>` : ""}
      <p class="wb-question"><b>Forecast.</b> Can better demand prediction cut the vehicles the depot holds in reserve?</p>
      <dl class="readouts four">${headline}</dl>
      <p class="trust-line">Scored on 60 untouched days, after a chronological split, once.</p>
      <div class="wb-grid">
        <aside class="wb-dials" aria-label="Ways to build the forecast">
          <h3 class="aside-title">Model experiment</h3>
          <p class="quiet">Change one thing. The others stay at the reference.</p>
          ${this.dials()}
          <h3 class="aside-title group">Operational failure test</h3>
          ${this.feedDial()}
        </aside>
        <div class="wb-main">
          ${strip}
          <p class="wb-note">${variant.note}${trained}</p>

          <h2>Accuracy against reserve</h2>
          ${trust ? this.cityChips() : ""}
          <figure class="wide"><canvas id="wb-scatter"></canvas></figure>
          ${trust ? this.scatterNote(trust) : ""}

          <h2>What it changes at the depot</h2>
          ${this.whyRidesHold(variant, reference)}
          <dl class="readouts four">${depot}</dl>
          <p class="wb-note"><b>So:</b> better forecasts buy no rides here; the fleet has vehicles to spare, and when the site is short it is short of energy, which no forecast supplies. Their value is the fleet held against uncertainty, the reserve; charging timing can also move the energy bill.</p>
          <details class="fold"><summary>Full depot outcomes</summary>
            <dl class="readouts four">${more}</dl>
            ${this.worth(variant, reference)}
            <p class="wb-note">Reserve = (reference vehicles − this model's) × $${whole(data.money?.vehicle_cost_per_year ?? 60000)} ÷ 365, a day. The vehicle-year is a parameter of this page, not a claimed cost.</p>
            ${replay}
          </details>

          <details class="fold"><summary>How we know the score is real</summary>
            ${trust ? splitTimeline(trust) : ""}
            <p class="wb-note">Chronological, never random. Trees fit on the first block; validation chose when to stop; the next block sized the bound; the last 60 days were scored once. No row sees its future.</p>
            <div class="charts">
              <figure><figcaption>How wrong, 1, 6 and 24 hours ahead</figcaption><canvas id="wb-horizons"></canvas>
                <p class="probe">Grey is "same hour last week". The gap is what the model adds.</p></figure>
              <figure><figcaption>Forecast against the rides that came</figcaption><canvas id="wb-days"></canvas>
                <p class="probe">One hour ahead, the fortnight from ${data.start}; error here ${percent(fortnightError(variant))}. Shading reaches the upper bound.</p></figure>
            </div>
            ${this.fortnightNote(variant, reference)}
            <details class="fold"><summary>Why ${whole(variant.trees ?? reference.trees ?? 0)} trees</summary>
              <figure class="wide"><canvas id="wb-curve"></canvas><p class="probe">${curveCopy}${validation === null ? "" : ` Validation is February 2024, just after January's rise in rides, so it sits at ${percent(validation)} where the test days give ${percent(one.error)}.`}</p></figure>
              <p class="quiet">Poisson counting reference: about ${percent(noiseFloor(reference)).replace(".0", "")} at ${whole(meanRides(reference))} rides an hour. A theoretical reference, not a measured floor.</p>
            </details>
            <details class="fold"><summary>Requested against achieved coverage</summary>
              <figure class="wide"><canvas id="wb-calibration"></canvas><p class="probe">A bound is good when it holds as often as asked and no wider. Diagonal: as asked. Labels: vehicles held for it.</p></figure>
            </details>
          </details>

          <details class="fold"><summary>Where this model fails: ${scent}</summary>${slices ? slicesTable(slices) : ""}</details>
          <details class="fold"><summary>What this model learned</summary>
            ${mine?.importance ? importanceTable(mine.importance) : trust?.importance && isRef ? importanceTable(trust.importance) : `<p class="quiet">${mine?.card.kind === "pretrained" ? "Pretrained: it reads the series alone, no features to rank." : "Nothing was trained here, so there is nothing to rank."}</p>`}
            <p class="wb-note">Error rise: how many points worse the validation block scores when that one feature is shuffled, so whether the information helps. Gain is XGBoost's own share of the splits, descriptive only; lagged features split credit.</p>
          </details>
          <details class="fold"><summary>This model, on a card</summary>${trust ? modelCard(trust, mine?.card, this.name(variant), isRef) : ""}</details>
        </div>
      </div>`;
    this.root.querySelectorAll<HTMLElement>("[data-city]").forEach((chip) => chip.addEventListener("click", () => { this.city = chip.dataset.city!; this.render(); }));
    this.root.querySelectorAll<HTMLDetailsElement>("details.fold").forEach((fold) => fold.addEventListener("toggle", () => this.draw()));
    window.clearTimeout(this.toastTimer);
    if (this.reset) this.toastTimer = window.setTimeout(() => { this.reset = null; this.root.querySelector(".toast")?.remove(); }, 3500);
    this.draw();
  }

  /** The three forecasts of a city as (error, reserve) at matched 95% achieved coverage, for the chart. */
  private arms(trust: Trust): { name: string; error: number; reserve: number | null; color: string }[] {
    const names: [string, string, string][] = [["last_week", "Same hour last week", T.label], ["reference", "Trained here", "#006fee"], ["chronos", "Pretrained (Chronos-2)", "#007068"]];
    const source = this.city === "sf" ? trust.sf : trust.cities[this.city];
    if (!source) return [];
    const arms = names.filter(([k]) => source[k]).map(([k, name, color]) => ({ name, error: source[k].error, reserve: source[k].reserve_at_95, color }));
    const mine = this.city === "sf" ? trust.variants?.[this.chosen] : undefined;
    if (mine && !["reference", "last_week", "chronos"].includes(this.chosen)) arms.push({ name: `Selected: ${this.name(this.data!.variants[this.chosen])}`, error: mine.error, reserve: mine.reserve_at_95, color: "#ea0000" });
    return arms;
  }

  private cityChips(): string {
    const cities: [string, string][] = [["sf", "San Francisco"], ["chicago", "Chicago"], ["nyc_yellow", "New York"]];
    return `<div class="options chips" role="radiogroup" aria-label="City">${cities.map(([k, n]) => `<button type="button" role="radio" aria-checked="${k === this.city}" data-city="${k}">${n}</button>`).join("")}</div>`;
  }

  private scatterNote(trust: Trust): string {
    const arms = this.arms(trust);
    const by = Object.fromEntries(arms.map((a) => [a.name, a]));
    const local = by["Trained here"], pre = by["Pretrained (Chronos-2)"], last = by["Same hour last week"];
    if (!local || !last) return "";
    const fewer = pre && pre.reserve && local.reserve ? Math.round(100 * (1 - pre.reserve / local.reserve)) : null;
    const preLine = !pre ? "" : fewer === null ? " The pretrained model's reserve could not be read at 95%." : fewer > 5 ? ` The pretrained model is more accurate and tighter: ${fewer}% fewer vehicles held at the same reliability.` : fewer < -5 ? ` The pretrained model is more accurate but wider: ${-fewer}% more vehicles held at the same reliability.` : " The pretrained model is more accurate but no tighter: the same vehicles held at the same reliability.";
    const caveat = this.city === "nyc_yellow" ? " New York is in the pretrained model's training data; this is a comparison of parts, not a zero-shot claim. Chicago, from 2025, is not." : "";
    const sel = arms.find((a) => a.name.startsWith("Selected"));
    const selLine = sel && local.reserve && sel.reserve ? ` <b>Selected:</b> ${sel.name.replace("Selected: ", "")}, ${percent(sel.error)} and ${whole(sel.reserve)} vehicles: ${sel.error > local.error ? "+" : "−"}${(100 * Math.abs(sel.error - local.error)).toFixed(1)} pts and ${sel.reserve > local.reserve ? "+" : "−"}${whole(Math.abs(sel.reserve - local.reserve))} vehicles against the reference.` : "";
    return `<p class="wb-note">Lower left is better: fewer vehicles held at 95% achieved reliability, with less error. This chart reads every forecast at the reliability its bound actually reached; the figures above read each at the 95% its bound states, so the two can differ. The reference (trained here) beats last week by ${(100 * (last.error - local.error)).toFixed(1)} points and ${local.reserve && last.reserve ? whole(last.reserve - local.reserve) : "—"} vehicles.${preLine.replace("The pretrained model", "Chronos-2")}${selLine}${caveat}</p>`;
  }

  /** When the fortnight is kinder to a model than its 60 days were, or harsher, say so: the depot run below sees only the fortnight. */
  private fortnightNote(variant: Variant, reference: Variant): string {
    const data = this.data!;
    const lastWeek = data.variants.last_week;
    if (!lastWeek || variant.dial === "reference") return "";
    const here = fortnightError(variant);
    const hereRef = fortnightError(reference);
    const hereLast = fortnightError(lastWeek);
    const sixty = variant.horizons["1"].error - reference.horizons["1"].error;
    const gap = here - hereRef;
    if (Math.abs(sixty - gap) < 0.01) return "";
    return `<p class="wb-note"><b>The depot run is not the test set.</b> This model is ${(Math.abs(sixty) * 100).toFixed(1)} points ${sixty < 0 ? "better" : "worse"} than the reference over the 60 held-out days, but ${(Math.abs(gap) * 100).toFixed(1)} points ${gap < 0 ? "better" : "worse"} on the run's fortnight, where last week alone scores ${percent(hereLast)}. The run shows operations; the 60 days decide forecast quality.</p>`;
  }

  /** Why rides served do not move between forecasts on this depot, in the depot's own arithmetic. */
  private whyRidesHold(variant: Variant, reference: Variant): string {
    const data = this.data!;
    const depot = data.depot;
    if (!depot) return "";
    const actual = reference.days.actual.filter((v): v is number => v !== null);
    const offered = reference.decision.rides_offered_per_day ?? 0;
    if (!actual.length || !offered) return "";
    // The stored days are in the source city's scale; the run offers its own rides a day with the same shape.
    const scale = offered / (24 * (actual.reduce((a, b) => a + b, 0) / actual.length));
    const peak = Math.max(...actual) * scale;
    const perVehicleHour = 60 / depot.ride_minutes;
    const needed = Math.ceil(peak / perVehicleHour);
    const away = Math.round(depot.chargers * 1.5);
    const spare = data.fleet - needed - away;
    const costDelta = (variant.decision.cost_per_kwh - reference.decision.cost_per_kwh) * (reference.decision.kwh_per_day ?? 0);
    const cost = Math.abs(Math.round(costDelta)) < 1 ? "the same energy cost as the reference" : `$${Math.round(Math.abs(costDelta)).toLocaleString("en-US")} a day ${costDelta > 0 ? "more" : "less"} in energy than the reference`;
    const room = spare >= 0 ? `with about ${whole(away)} off the road at the depot, a fleet of ${whole(data.fleet)} covers it with ${whole(spare)} to spare` : `with about ${whole(away)} off the road at the depot, a fleet of ${whole(data.fleet)} is ${whole(-spare)} short in that hour`;
    return `<p class="wb-note"><b>Rides served barely change here.</b> The busiest hour needs ${whole(needed)} vehicles on the road; ${room}. So the forecast changes the reserve and the timing of charging more than throughput: this one is ${cost}, holding ${whole(variant.reserve.vehicles_held_in_reserve)} vehicles back against ${whole(reference.reserve.vehicles_held_in_reserve)}.</p>`;
  }

  /** The money a day between this forecast and the reference: energy, rides, and the reserve if vehicles bind. */
  private worth(variant: Variant, reference: Variant): string {
    const money = this.data!.money ?? { fare_per_ride: 19.69, lost_ride_cost: 20, vehicle_cost_per_year: 60000 };
    const mine = variant.decision;
    const ref = reference.decision;
    const kwh = ref.kwh_per_day ?? 0;
    const offered = ref.rides_offered_per_day ?? 0;
    const energy = (ref.cost_per_kwh - mine.cost_per_kwh) * kwh;
    const rides = (mine.served - ref.served) * offered * (money.fare_per_ride + money.lost_ride_cost);
    const reserve = ((reference.reserve.vehicles_held_in_reserve - variant.reserve.vehicles_held_in_reserve) * money.vehicle_cost_per_year) / 365;
    const sign = (v: number) => (v >= 0 ? "+" : "−") + "$" + Math.round(Math.abs(v)).toLocaleString("en-US");
    const row = (name: string, value: number, note: string) => `<tr><th scope="row">${name}</th><td>${sign(value)}</td><td>${note}</td></tr>`;
    if (!kwh) return `<p class="quiet">Rebuild the workbench to see the money (depot-twin data models).</p>`;
    return (
      `<table class="account worth"><tbody>` +
      row("Energy", energy, `${whole(kwh)} kWh a day at ${mine.cost_per_kwh.toFixed(3)} against ${ref.cost_per_kwh.toFixed(3)} a kWh`) +
      row("Rides", rides, `${(mine.served * 100).toFixed(1)}% served against ${(ref.served * 100).toFixed(1)}%, at $${money.fare_per_ride} a ride plus $${money.lost_ride_cost} for each one lost`) +
      row("Counted: energy and rides", energy + rides, "what the depot actually earned or lost with this forecast on the fortnight") +
      row("Reserve, only if vehicles bind", reserve, `${variant.reserve.vehicles_held_in_reserve} vehicles held against ${reference.reserve.vehicles_held_in_reserve}, at $${whole(money.vehicle_cost_per_year)} a vehicle-year; worth nothing where the fleet has vehicles to spare, as E16 found`) +
      `</tbody></table>`
    );
  }

  private draw(): void {
    if (!this.data || this.root.hidden) return;
    const variant = this.data.variants[this.chosen];
    const canvas = (id: string) => this.root.querySelector<HTMLCanvasElement>(`#${id}`);
    const visible = (c: HTMLCanvasElement | null) => c !== null && c.clientWidth > 0;
    const scatter = canvas("wb-scatter");
    if (visible(scatter) && this.trust) drawScatter(scatter!, this.arms(this.trust));
    const curve = canvas("wb-curve");
    if (visible(curve)) drawCurve(curve!, variant, this.data.variants.trees_3000);
    const horizons = canvas("wb-horizons");
    if (visible(horizons)) {
      const names = ["1", "6", "24"];
      drawBars(horizons!, names.map((h) => `${h} h ahead`), names.map((h) => variant.horizons[h].error), names.map((h) => variant.horizons[h].same_hour_last_week));
    }
    const daysCanvas = canvas("wb-days");
    if (visible(daysCanvas)) {
      const days: Outlook[] = [];
      variant.days.actual.forEach((actual, k) => {
        if (actual !== null) days.push({ minute: (k + 1) * 60, forecast: variant.days.mean[k], upper: variant.days.upper[k], actual });
      });
      drawOutlook(daysCanvas!, days);
    }
    const calibration = canvas("wb-calibration");
    if (visible(calibration) && this.trust) drawCalibration(calibration!, this.trust);
  }
}
