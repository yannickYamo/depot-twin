// What the forecasts add: their error against the same hour last week, and what the depot does with them.
// San Francisco, the series the depot runs on, is read on its held-out days (trust.json). Chicago and New
// York are read from the 26-week backtest (backtest.json), the comparison the documents quote, so a city
// has one figure wherever it is named. The depot's run on each forecast is models.json.

import { percent, whole } from "./canvas";

interface Score { error: number }
interface Run {
  reserve: { vehicles_held_in_reserve: number };
  decision: { served: number; cost_per_kwh: number };
  horizons: Record<string, { error: number; same_hour_last_week: number; upper_bound_held: number }>;
}

export interface Forecasts {
  sf: Record<string, Score>;
  cities: Record<string, Record<string, Score>>;
  holdout_days: number;
  weeks: number;
  fleet: number;
  runs: Record<string, Run>;
}

const ARMS: [string, string][] = [["last_week", "Same hour last week"], ["reference", "Trained model"], ["chronos", "Pretrained model"]];
const CITIES: [string, string][] = [["sf", "San Francisco taxi"], ["chicago", "Chicago ride-hail"], ["nyc_yellow", "New York taxi"]];

/** The two files as one, or null when either lacks what this view reads: checked once, where they come in. */
export function forecasts(trust: unknown, bench: unknown, backtest: unknown): Forecasts | null {
  const t = trust as { sf?: Record<string, Score>; card?: { holdout_days?: number } } | null;
  const k = backtest as { weeks?: number; hours_ahead?: number; series?: Record<string, Record<string, Score>> } | null;
  const b = bench as { fleet?: number; variants?: Record<string, Run> } | null;
  const scored = (city?: Record<string, Score>): boolean => ARMS.every(([key]) => typeof city?.[key]?.error === "number");
  const ran = ARMS.every(([key]) => typeof b?.variants?.[key]?.reserve?.vehicles_held_in_reserve === "number" && typeof b.variants[key].decision?.cost_per_kwh === "number");
  if (!t?.sf || !k?.series || k.hours_ahead !== 1 || typeof k.weeks !== "number" || !b?.variants || !scored(t.sf) || !CITIES.slice(1).every(([key]) => scored(k.series?.[key])) || !ran) return null;
  if (typeof b.variants.reference.horizons?.["1"]?.upper_bound_held !== "number" || typeof t.card?.holdout_days !== "number" || typeof b.fleet !== "number") return null;
  return { sf: t.sf, cities: k.series, holdout_days: t.card.holdout_days, weeks: k.weeks, fleet: b.fleet, runs: b.variants };
}

/** The forecasts in one line, for the fold that holds them: what a better one bought at the depot. */
export function forecastLine(f: Forecasts | null): string {
  if (!f) return "How well rides are forecast, and what a better forecast changes at the depot.";
  const held = (key: string): number => f.runs[key].reserve.vehicles_held_in_reserve;
  const level = ARMS.every(([arm]) => f.runs[arm].decision.served === f.runs.last_week.decision.served);
  return `${level ? "A better forecast bought no rides here; it" : "A better forecast"} shrinks the reserve from ${whole(held("last_week"))} vehicles to ${whole(held("reference"))}.`;
}

export function forecastMarkup(f: Forecasts): string {
  const city = (key: string): Record<string, Score> => (key === "sf" ? f.sf : f.cities[key]);
  const widest = Math.max(...CITIES.flatMap(([key]) => ARMS.map(([arm]) => city(key)[arm].error)));
  const group = ([key, name]: [string, string]): string =>
    `<div class="fc-city"><h4>${name} <small>${key === "sf" ? `${f.holdout_days} held-out days` : `${f.weeks} weeks, refit each week`}</small></h4>` +
    ARMS.map(([arm, label]) => `<div class="fc-row ${arm}"><span>${label}</span><i style="width:${((100 * city(key)[arm].error) / widest).toFixed(1)}%"></i><b>${percent(city(key)[arm].error)}</b></div>`).join("") +
    `</div>`;
  const run = (key: string): Run => f.runs[key];
  const row = (label: string, show: (r: Run) => string): string =>
    `<tr><th scope="row">${label}</th>${ARMS.map(([arm]) => `<td>${show(run(arm))}</td>`).join("")}</tr>`;
  const one = run("reference").horizons["1"];
  const fewer = run("last_week").reserve.vehicles_held_in_reserve - run("reference").reserve.vehicles_held_in_reserve;
  const cheaper = 1 - run("reference").decision.cost_per_kwh / run("last_week").decision.cost_per_kwh;
  return (
    `<section class="forecast" aria-label="What the forecasts add">` +
    `<h3>What the forecasts add</h3>` +
    `<div class="fc-grid">` +
    `<div><p class="fc-name">Error one hour ahead, on days the trained model had not seen. Shorter is better.</p><div class="fc-cities">${CITIES.map(group).join("")}</div></div>` +
    `<div><p class="fc-name">The same depot at ${whole(f.fleet)} vehicles, run on each forecast.</p>` +
    `<table class="fc-table"><thead><tr><td></td>${ARMS.map(([, label]) => `<th scope="col">${label}</th>`).join("")}</tr></thead><tbody>` +
    row("Vehicles held in reserve", (r) => whole(r.reserve.vehicles_held_in_reserve)) +
    row("Energy, a kWh", (r) => `$${r.decision.cost_per_kwh.toFixed(3)}`) +
    row("Rides served", (r) => percent(r.decision.served)) +
    `</tbody></table>` +
    `<p class="fc-worth">The trained model frees ${whole(fewer)} vehicles from reserve and buys energy ${percent(cheaper)} cheaper. Rides served do not move: at ${whole(f.fleet)} vehicles the depot has vehicles to spare. Its upper bound held in ${percent(one.upper_bound_held)} of hours over ${f.holdout_days} held-out days.</p>` +
    `<p class="fc-worth">The pretrained model, Chronos-2 with no local fitting, is more accurate in all three series. New York is in its training data; Chicago is not.</p>` +
    `<button type="button" class="watch" data-goto="model">Open the forecast workbench</button></div>` +
    `</div></section>`
  );
}
