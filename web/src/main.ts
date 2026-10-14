// The page: a depot the visitor can run and change, or a recorded run they can move through.
//
// The live depot and the recorded run fill the same list of steps (see trace.ts) and one set of views draws
// it. Live, the steps come from the browser simulator as the clock advances; recorded, they come from a file
// written by the Python simulator. The page has a short version and a full twin of three tabs: the depot,
// the decisions, and what is under the hood.

import "./style.css";
import { DEFAULTS, DepotSim, type Params } from "./sim";
import { loadGrid, type Grid } from "./grid";
import { PLACE, unpack, vehicleName, type Plan, type Step, type TraceFile, type TraceMeta } from "./trace";
import { compareRuns, drawPlannedRoad, drawPlannedVisits, plansAt } from "./views/plan";
import { renderChain, renderFollowed } from "./views/board";
import { ONE_FEEDER_KW, TWO_FEEDERS_KW, chargerCeiling, designAlerts, drawKw, feedable, type Alert, type Measured } from "./alerts";
import { clock, failed, percent, whole } from "./views/canvas";
import {
  drawGridStrain, drawOutlook, drawPulse, drawRides, drawRoad, hourAt, hourly, outlook, outlookScore, type Hour,
} from "./views/charts";
import { drawFloor, type Drawn, type Hit } from "./views/floor";
import { forecastLine, forecasts, type Forecasts } from "./views/models";
import { DECISIONS, answerMarkup, impactMarkup, worthMarkup, isOutcome, money as dollars, type Decision, type Outcome, type Taken } from "./views/impact";
import { IDEA, OPENING, briefMarkup, carried, showCase, type Unknowns } from "./views/brief";
import { MoneyView } from "./views/money";
import { WorkbenchView } from "./views/workbench";

const STEP_MIN = 5;
/** At 1x, one simulated minute passes each second: slow enough to watch a vehicle plug in. */
const MINUTES_PER_SECOND = 1;
const DAY = 1440 / STEP_MIN;
/** Play mode keeps this much history for the charts. */
const KEEP = 3 * DAY;
/** A new depot is run this long before it is shown, so the visitor does not start with an empty yard. */
const WARM_UP = DAY + 7 * 12;

const RULE_NAMES: Record<string, string> = {
  threshold: "called in at a fixed charge level",
  threshold_waits: "called in at a fixed charge level when a charger is free",
  slots: "called in to fill energy slots",
  heartbeat: "called in by the day-ahead plan",
  headroom: "called in to fill every charger",
  in_order: "fed in the order they plugged in",
  slot_power: "fed in the order they plugged in",
  emptiest_first: "emptiest vehicle fed first",
  need_first: "emptiest vehicle fed first",
};

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`the page has no element #${id}`);
  return found as T;
}

const floor = element<HTMLCanvasElement>("floor");
const chainOpen = element<HTMLDetailsElement>("chain-open");
const pulse = element<HTMLCanvasElement>("pulse");
const rides = element<HTMLCanvasElement>("rides");
const road = element<HTMLCanvasElement>("road");
const outlookCanvas = element<HTMLCanvasElement>("outlook");
const strainCanvas = element<HTMLCanvasElement>("strain");
// Asked for each time it matters, so a visitor who turns reduced motion on while the page is open is heard.
const lessMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const still = (): boolean => lessMotion.matches;

/** The page on screen: the short version, or one of the full twin's three tabs. `play` is the Depot tab,
 * `outcome` the Decisions tab and `hood` Under the hood. */
type Mode = "short" | "play" | "outcome" | "hood";
/** The three parts under the hood, each folded until it is asked for. */
type Part = "model" | "money" | "replay";
const PARTS: readonly Part[] = ["model", "money", "replay"];

interface State {
  mode: Mode;
  meta: TraceMeta;
  steps: Step[];
  /** The same depot under the other power rule, step for step, when the visitor asks to compare. */
  otherSteps: Step[] | null;
  /** Position in `steps`, with a fraction: the picture is drawn between two steps. */
  head: number;
  playing: boolean;
  /** Simulated minutes per second of real time. */
  speed: number;
  /** The vehicle the visitor is following, or null. */
  followed: number | null;
  drawnStep: number;
  /** What the steps on screen are: the live depot, or a named recording. Empty while neither is loaded. */
  holds: string;
}

const params: Params = { ...DEFAULTS, staff: 15 };
/** Settings the visitor has set by hand; the others follow the fleet as they do in the reference scenarios. */
const touched = new Set<string>();
let compare = false;
let sim: DepotSim;
let otherSim: DepotSim | null = null;
let hours: Hour[] = [];
let drawn: Drawn | null = null;
/** The plans a recorded run made, and a simple rule's run on the same days to set beside it. */
let plans: Plan[] = [];
let simple: Step[] | null = null;
let grid: Grid | null = null;
/** What the depot's floor and charts are showing: the live depot, or a recorded run under the hood. */
let bench: "play" | "replay" = "play";
const state: State = {
  mode: "play",
  meta: {} as TraceMeta,
  steps: [],
  otherSteps: null,
  head: 0,
  playing: !still(),
  speed: 1,
  followed: null,
  drawnStep: -1,
  holds: "",
};

// ---------------------------------------------------------------------------------------------------
// Play mode: the simulator and its settings.

function otherRule(): Params["powerRule"] {
  return params.powerRule === "in_order" ? "emptiest_first" : "in_order";
}

// The four decisions of the impact panel. Three can be watched in the browser's depot: the same depot is
// run twice, with the decision and without it, on the same rides. The plan needs the full model, so it
// opens the recorded run.
let outcome: Outcome | null = null;
const taken: Taken = { calling: true, power: true, plan: true, feeder: true };
let watching: Decision | null = null;

interface Pair { fleet: number; with: Partial<Params>; without: Partial<Params>; other: [string, string]; name: string; why: string | ((outcome: Outcome) => string) }
const WATCH: Partial<Record<Decision, Pair>> = {
  calling: {
    fleet: 650,
    with: { siteKw: ONE_FEEDER_KW, powerRule: "in_order", recall: "threshold_waits" },
    without: { siteKw: ONE_FEEDER_KW, powerRule: "in_order", recall: "threshold" },
    other: ["called in whether or not a charger is free", "called in only when a charger is free"],
    name: "Calling a vehicle in only when a charger is free",
    why: (o) => {
      const { plain_at_the_larger_fleet: plain, with: waits } = o.decisions.calling;
      return `${whole(waits.fleet)} vehicles on one feeder, both depots offered the same rides. In the recorded tests the plain rule serves ${percent(plain.rides_served_share)} here and holds the 99% floor in ${plain.fortnights_at_the_floor} of ${plain.fortnights} two-week windows; the waiting rule serves at least ${(100 * (waits.rides_served_share_lowest_run ?? 1)).toFixed(2)}% in every run. Watch the queue for a charger: the gap opens over days.`;
    },
  },
  power: {
    fleet: 1000,
    with: { siteKw: ONE_FEEDER_KW, powerRule: "in_order", recall: "threshold" },
    without: { siteKw: ONE_FEEDER_KW, powerRule: "emptiest_first", recall: "threshold" },
    other: ["with power to the emptiest vehicle first", "with power in the order vehicles plugged in"],
    name: "Feeding chargers in the order vehicles plugged in",
    why: "1,000 vehicles on a feeder planned for 600, as while a second feeder is on order. Rides are lost under either rule; feeding in order of arrival loses fewer.",
  },
  feeder: {
    fleet: 1000,
    with: { siteKw: TWO_FEEDERS_KW, powerRule: "in_order", recall: "threshold_waits" },
    without: { siteKw: ONE_FEEDER_KW, powerRule: "in_order", recall: "threshold_waits" },
    other: ["on one feeder", "on two feeders"],
    name: "A second feeder in service when the fleet needs it",
    why: "1,000 vehicles, past what one feeder carries. The same fleet on one feeder and on two: one cannot carry it and loses rides.",
  },
};

/** What the depot running alongside differs by: the watched decision the other way, or the other power rule. */
function otherChange(): Partial<Params> {
  const pair = watching ? WATCH[watching] : undefined;
  if (pair && watching) return taken[watching] ? pair.without : pair.with;
  return { powerRule: otherRule() };
}

function otherName(): string {
  const pair = watching ? WATCH[watching] : undefined;
  if (pair && watching) return pair.other[taken[watching] ? 0 : 1];
  return RULE_NAMES[otherRule()];
}

/** Set the depot to one decision's own case, taken or not, with the opposite running alongside. */
function watch(key: Decision): void {
  const pair = WATCH[key];
  if (!pair) return;
  watching = key;
  // Every setting goes back to its start, so the pair differs by the decision and by nothing a visitor left behind.
  Object.assign(params, DEFAULTS, { seed: params.seed });
  touched.clear();
  compare = false;
  const box = document.getElementById("compare-rules") as HTMLInputElement | null;
  if (box) box.checked = false;
  params.fleet = pair.fleet;
  params.staff = Math.max(4, Math.floor(params.fleet / 40));
  params.chargers = Math.min(240, Math.round((params.fleet * 0.132) / 2) * 2);
  Object.assign(params, taken[key] ? pair.with : pair.without);
  startAgain();
  syncControls();
}

let models: Forecasts | null = null;

function showImpact(): void {
  const box = element("impact");
  box.hidden = state.mode !== "outcome";
  if (!box.hidden) box.innerHTML = outcome ? impactMarkup(outcome, taken, watching, models) : outcomeSettled ? failed("The figures didn't load.", "outcome") : "";
  showWatching();
}

/** Above the depot, while a decision's pair is running: what is being watched, why, and the switch. */
function showWatching(): void {
  const box = element("watching");
  const pair = watching ? WATCH[watching] : undefined;
  box.hidden = !pair || state.mode !== "play";
  if (!pair || !watching || box.hidden) return;
  const on = taken[watching];
  box.innerHTML =
    `<div><p class="watching-name" tabindex="-1">${pair.name}</p><p>${typeof pair.why === "function" ? (outcome ? pair.why(outcome) : "") : pair.why}</p></div>` +
    `<div class="watching-acts"><div class="switch" role="radiogroup" aria-label="${pair.name}">` +
    `<button type="button" role="radio" aria-checked="${!on}" data-decision="${watching}" data-take="0">Without</button>` +
    `<button type="button" role="radio" aria-checked="${on}" data-decision="${watching}" data-take="1">With</button></div>` +
    `<button type="button" class="watch" data-back="1">Back to Decisions</button></div>`;
}

function onImpact(event: Event): void {
  const data = (event.target as HTMLElement).closest<HTMLElement>("button")?.dataset;
  if (!data) return;
  if (data.all !== undefined) {
    for (const key of DECISIONS) taken[key] = data.all === "1";
    if (watching) watch(watching);
  } else if (data.decision) {
    const key = data.decision as Decision;
    taken[key] = data.take === "1";
    if (watching === key) watch(key);
  } else if (data.back) {
    const from = watching;
    void setMode("outcome").then(() => document.querySelector<HTMLElement>(`[data-watch="${from ?? "calling"}"]`)?.focus());
    return;
  } else if (data.watch) {
    const key = data.watch as Decision;
    const glide: ScrollBehavior = still() ? "auto" : "smooth";
    if (key === "plan") {
      // The recording of the plan itself, whatever recording was open last.
      replayOf = { trace: "traces/sample.json", model: "", compare: "traces/threshold.json" };
      void setMode("hood", "replay").then(() => {
        element("floor").scrollIntoView({ behavior: glide, block: "start" });
        partBox("replay").querySelector<HTMLElement>("summary")?.focus({ preventScroll: true });
      });
      return;
    }
    void setMode("play").then(() => {
      watch(key);
      showWatching();
      const strip = element("watching");
      strip.scrollIntoView({ behavior: glide, block: "start" });
      // Focus goes with the view, so a keyboard or screen-reader user lands on what is now running.
      strip.querySelector<HTMLElement>(".watching-name")?.focus();
    });
    return;
  }
  showImpact();
}

/** Build the depot from the current settings and run it past its warm-up. */
function startAgain(): void {
  // A vehicle followed in a larger fleet may not exist in a smaller one.
  if (state.followed !== null && state.followed >= params.fleet) state.followed = null;
  sim = new DepotSim(params);
  otherSim = compare || watching ? new DepotSim({ ...params, ...otherChange() }) : null;
  state.steps = [];
  state.otherSteps = otherSim ? [] : null;
  for (let k = 0; k < WARM_UP; k++) advanceSim();
  since = { mine: 0, other: 0, steps: 0 };
  state.meta = sim.meta();
  state.head = state.steps.length - 2;
  markDirty();
  state.holds = "play";
}

/** Rides served by the depot and by the one alongside since the run began, past its warm-up: a gap that opens slowly still adds up. */
let since = { mine: 0, other: 0, steps: 0 };

function advanceSim(): void {
  state.steps.push(sim.step());
  since.mine += state.steps[state.steps.length - 1].served;
  since.steps += 1;
  if (otherSim && state.otherSteps) {
    state.otherSteps.push(otherSim.step());
    since.other += state.otherSteps[state.otherSteps.length - 1].served;
  }
  if (state.steps.length > KEEP) {
    state.steps.shift();
    state.otherSteps?.shift();
    state.head -= 1;
    // The step that was drawn has moved one place down too; without this the readouts stop once the buffer is full.
    state.drawnStep -= 1;
  }
}

/** Settings that can change while the depot runs are applied to it directly; the rest rebuild it. */
function applyLive(): void {
  Object.assign(sim.params, params);
  markDirty();
  if (otherSim) Object.assign(otherSim.params, params, otherChange());
  state.meta = sim.meta();
}

interface Slider {
  key: "fleet" | "siteKw" | "chargers" | "chargerKw" | "staff" | "callBelow" | "slotMin" | "ridesPerVehicleDay";
  label: string;
  min: number;
  max: number;
  step: number;
  show: (value: number) => string;
  /** Changing these means a different depot, so the run starts again. */
  rebuild?: boolean;
  /** Shown only under one way of calling vehicles in. */
  only?: Params["recall"];
  /** What the setting is, in one plain line. */
  hint: string;
}

/** Real charger classes. The depot's reference is the 60 kW fast charger reported at a working robotaxi depot;
 *  Level 2 is AC and the vehicle's own charger sets its rate at 11 kW. */
const CHARGER_CLASSES: [number, string, string][] = [
  [19, "Level 2, 19 kW", "AC; the vehicle takes 11 kW"],
  [60, "Fast, 60 kW", "the reference depot's charger"],
  [150, "Fast, 150 kW", "what one vehicle model can take at best"],
  [350, "High power, 350 kW", "more than either vehicle accepts"],
];

const SLIDERS: Slider[] = [
  { key: "fleet", label: "Vehicles in the fleet", min: 200, max: 2000, step: 50, show: whole, rebuild: true, hint: "How many vehicles the depot keeps charged and clean." },
  // The connection is bounded by the parcel: the weakest nearby feeder gives about 1 MW, the two strong ones together 5.5 MW (docs/METHOD.md).
  { key: "siteKw", label: "Power from the grid", min: 1000, max: 5500, step: 250, show: (v) => `${(v / 1000).toFixed(2)} MW`, hint: "The connection's size, if it isn't one or two whole feeders." },
  { key: "chargers", label: "Chargers", min: 10, max: 400, step: 2, show: whole, rebuild: true, hint: "" },
  { key: "staff", label: "People plugging in and cleaning", min: 4, max: 120, step: 1, show: whole, hint: "Too few people and vehicles wait to be plugged in." },
  { key: "callBelow", label: "Call a vehicle in when its battery is under", min: 0.1, max: 0.6, step: 0.05, show: (v) => `${Math.round(v * 100)}%`, only: "threshold", hint: "Lower means fewer, longer visits." },
  { key: "slotMin", label: "Length of a charging slot", min: 20, max: 90, step: 5, show: (v) => `${v} minutes`, only: "slots", hint: "A visit takes the energy a charger gives in this time." },
  { key: "ridesPerVehicleDay", label: "Rides offered per vehicle per day", min: 15, max: 35, step: 1, show: whole, hint: "How busy the riders keep each vehicle." },
];

/** What a vehicle uses on the road against my estimate: the same three cases the tests ran. */
const ENERGY_CASES: [number, string][] = [[0.9, "10% less"], [1, "As estimated"], [1.1, "10% more"]];

const slider = (key: Slider["key"]): Slider => SLIDERS.find((candidate) => candidate.key === key)!;

/** Four settings carry the answer and are always shown; the rest wait under "More settings". */
function buildControls(): void {
  const form = element<HTMLFormElement>("controls");
  const hint = (text: string): string => `<small class="slider-note">${text}</small>`;
  const choice = (id: string, label: string, options: [string, string][], says: string) =>
    `<label>${label}<select id="${id}">${options.map(([value, name]) => `<option value="${value}">${name}</option>`).join("")}</select>${hint(says)}</label>`;
  form.innerHTML =
    sliderMarkup(slider("fleet")) +
    `<div class="choice-block"><span id="feeders-name">Feeders</span><div class="presets" role="group" aria-labelledby="feeders-name"><button type="button" aria-pressed="false" data-kw="${ONE_FEEDER_KW}">One feeder, ${ONE_FEEDER_KW / 1000} MW</button><button type="button" aria-pressed="false" data-kw="${TWO_FEEDERS_KW}">Two feeders, ${TWO_FEEDERS_KW / 1000} MW</button></div>${hint("The grid connection. A second feeder takes years to add.")}</div>` +
    choice("recall", "Calling rule", [["threshold", "When the battery is low"], ["threshold_waits", "When the battery is low and a charger is free"], ["slots", "In slots, paced to the chargers"]], "When a vehicle is told to come in and charge.") +
    `<div class="choice-block"><span id="energy-name">Energy use</span><div class="presets" role="radiogroup" aria-labelledby="energy-name">${ENERGY_CASES.map(([share, name]) => `<button type="button" role="radio" aria-checked="false" data-energy="${share}">${name}</button>`).join("")}</div>${hint("What a vehicle uses on the road, against my estimate.")}</div>` +
    `<details class="fold small" id="more-settings"><summary>More settings</summary><div class="more-settings">` +
    sliderMarkup(slider("siteKw")) +
    sliderMarkup(slider("chargers")) +
    `<div class="choice-block"><span>Power of each charger <b id="chargerKw-value"></b></span><div class="presets" role="radiogroup" aria-label="Power of each charger">${CHARGER_CLASSES.map(([kw, name]) => `<button type="button" role="radio" aria-checked="false" data-charger-kw="${kw}">${name}</button>`).join("")}</div><small id="chargerKw-note" class="slider-note"></small></div>` +
    sliderMarkup(slider("staff")) +
    choice("powerRule", "When power is short, feed vehicles", [["in_order", "In the order they plugged in"], ["emptiest_first", "Emptiest vehicle first"]], "Who gets power first when the feeder is at its limit.") +
    sliderMarkup(slider("callBelow")) +
    sliderMarkup(slider("slotMin")) +
    sliderMarkup(slider("ridesPerVehicleDay")) +
    `<label class="check"><input type="checkbox" id="compare-rules" /> Run the other power rule alongside</label>${hint("A second depot on the same rides, differing only in the power rule.")}` +
    `</div></details>`;
  form.addEventListener("input", onControl);
  form.addEventListener("click", (event) => {
    const data = (event.target as HTMLElement).dataset ?? {};
    if (!data.chargerKw && !data.kw && !data.energy) return;
    if (data.chargerKw) {
      params.chargerKw = Number(data.chargerKw);
      touched.add("chargerKw");
    } else if (data.energy) {
      params.energyUse = Number(data.energy);
    } else {
      params.siteKw = Number(data.kw);
    }
    if (watching || data.energy) {
      // A watched pair the visitor has taken over is no longer what is running, and a vehicle's energy use
      // is set when the depot is built: either way the run starts again.
      if (watching) {
        watching = null;
        showImpact();
      }
      startAgain();
    } else {
      applyLive();
    }
    syncControls();
  });
  syncControls();
}

function sliderMarkup(slider: Slider): string {
  const note = slider.key === "chargers" ? `<small id="chargers-note" class="slider-note"></small>` : `<small class="slider-note">${slider.hint}</small>`;
  return `<label data-only="${slider.only ?? ""}"><span>${slider.label} <b id="${slider.key}-value"></b></span>` +
    `<input type="range" id="${slider.key}" min="${slider.min}" max="${slider.max}" step="${slider.step}" />${note}</label>`;
}

/** The fleet the tests carried on one feeder and the fleet to plan for, once demand.json is in; the fleet alert reads its level from them. */
function measured(): Measured | null {
  return demand ? { fleet: demand.capacity_one_feeder, planned: demand.planned_one_feeder, limit: demand.served_at_the_limit_one_feeder, rides: demand.rides_per_vehicle_day } : null;
}

/** What the running depot is doing about it: the last day's rides lost, and what bound them. */
function runAlerts(): Alert[] {
  const day = state.steps.slice(-DAY);
  if (day.length < DAY / 2) return [];
  const sum = (pick: (s: Step) => number) => day.reduce((a, s) => a + pick(s), 0);
  const served = sum((s) => s.served);
  const lost = sum((s) => s.lost);
  const offered = served + lost;
  if (offered === 0 || lost / offered < 0.01) return [];
  const limit = state.meta.usable_kw ?? state.meta.site_limit_kw;
  const atLimit = day.filter((s) => s.grid_kw >= 0.98 * limit).length / day.length;
  const queued = day.filter((s) => s.queued > 0).length / day.length;
  // More vehicles between stations than there are people means some of them are waiting for a person.
  // Twice as many vehicles between stations as there are people means a standing queue for a person. That
  // is asked before the charger queue, because chargers blocked by vehicles nobody has unplugged look like
  // a shortage of plugs.
  const people = params.staff || state.meta.cleaning_bays;
  const forStaff = day.filter((s) => s.handling > 2 * people).length / day.length;
  const why =
    atLimit > 0.5 ? `the grid was at its limit ${percent(atLimit)} of the time: energy binds`
    : forStaff > 0.3 ? `vehicles waited for a person ${percent(forStaff)} of the time: people bind`
    : queued > 0.3 ? `vehicles waited for a charger ${percent(queued)} of the time: plugs bind`
    : "every vehicle on the road was busy at the peak: the fleet binds";
  const level = lost / offered > 0.05 ? "stop" : "warn";
  // What a screen reader hears is the state, said once when it changes; the rolling figures are only shown.
  running = `Rides are being lost: ${why.slice(why.lastIndexOf(": ") + 2)}.`;
  return [{ level, text: `Last 24 hours: ${percent(lost / offered)} of rides lost (${whole(lost)}); ${why}.` }];
}

let shownAlerts = "";
let shownNow = "";
/** The running depot's state in words that do not change from step to step, for the announced box. */
let running = "";

function showAlerts(): void {
  if (state.mode !== "play" || bench !== "play") {
    element("alerts-said").innerHTML = shownAlerts = "";
    element("alerts-now").innerHTML = shownNow = "";
    return;
  }
  const sizing = designAlerts(params, measured());
  running = "";
  const now = runAlerts();
  // The first box is announced to screen readers when it changes, so it is written only when it does: the
  // design checks, which are sizing arithmetic, quick and approximate, and one line for the state of the
  // running depot. The last-24-hours line is the simulator itself and moves every step, so it is shown
  // in the second box, which is not announced.
  const said =
    sizing.map((a) => `<p class="alert ${a.level}"><span class="rule-of-thumb">Rule of thumb</span> ${a.text}</p>`).join("") +
    (running ? `<p class="heard">${running}</p>` : "");
  if (said !== shownAlerts) element("alerts-said").innerHTML = shownAlerts = said;
  const html = now.map((a) => `<p class="alert ${a.level}">${a.text}</p>`).join("");
  if (html !== shownNow) element("alerts-now").innerHTML = shownNow = html;
}

/** Make the controls show the current settings. */
function syncControls(): void {
  for (const slider of SLIDERS) {
    element<HTMLInputElement>(slider.key).value = String(params[slider.key]);
    element(`${slider.key}-value`).textContent = slider.show(params[slider.key]);
    const row = element(slider.key).closest("label") as HTMLElement;
    row.hidden = slider.only !== undefined && !params.recall.startsWith(slider.only);
  }
  const klass = CHARGER_CLASSES.find(([kw]) => kw === params.chargerKw) ?? CHARGER_CLASSES[1];
  element("chargerKw-value").textContent = `${params.chargerKw} kW`;
  element("chargerKw-note").textContent = klass[2];
  document.querySelectorAll<HTMLButtonElement>("[data-charger-kw]").forEach((button) => button.setAttribute("aria-checked", String(Number(button.dataset.chargerKw) === params.chargerKw)));
  document.querySelectorAll<HTMLButtonElement>("[data-energy]").forEach((button) => button.setAttribute("aria-checked", String(Number(button.dataset.energy) === params.energyUse)));
  document.querySelectorAll<HTMLButtonElement>("[data-kw]").forEach((button) => button.setAttribute("aria-pressed", String(Number(button.dataset.kw) === params.siteKw)));
  element("chargers-note").textContent = `Rule of thumb: the grid feeds ${whole(feedable(params))} at once at ${drawKw(params)} kW each; two plugs per fed one, ${whole(chargerCeiling(params))}, is the most that pays.`;
  showAlerts();
  element<HTMLSelectElement>("powerRule").value = params.powerRule;
  element<HTMLSelectElement>("recall").value = params.recall;
}

function onControl(event: Event): void {
  const input = event.target as HTMLInputElement | HTMLSelectElement;
  const slider = SLIDERS.find((candidate) => candidate.key === input.id);
  let rebuild = slider?.rebuild ?? false;
  if (watching) {
    // The visitor has taken the depot over: the pair being watched is no longer what is running.
    watching = null;
    rebuild = true;
    showImpact();
  }
  if (slider) {
    params[slider.key] = Number(input.value);
    touched.add(slider.key);
    if (slider.key === "fleet") {
      if (!touched.has("staff")) params.staff = Math.max(4, Math.floor(params.fleet / 40));
      if (!touched.has("chargers")) params.chargers = Math.min(240, Math.round((params.fleet * 0.132) / 2) * 2);
    }

  } else if (input.id === "powerRule") {
    params.powerRule = input.value as Params["powerRule"];
    // With the other rule running alongside, the two depots swap roles: start both again so that each
    // line's history is its own rule's.
    if (compare) rebuild = true;
  } else if (input.id === "recall") {
    params.recall = input.value as Params["recall"];
  } else if (input.id === "compare-rules") {
    compare = (input as HTMLInputElement).checked;
    rebuild = true;
  }
  if (rebuild) startAgain();
  else applyLive();
  syncControls();
}

// ---------------------------------------------------------------------------------------------------
// Replay mode: a run recorded from the Python simulator.

/** The recorded run to play: the reference by default, or the run of a model chosen in the workbench. */
let replayOf: { trace: string; model: string; compare: string | null } = { trace: "traces/sample.json", model: "", compare: "traces/threshold.json" };

interface RecordedRun {
  file: string;
  name: string;
  fleet: number;
  compare: string | null;
  note: string;
}

/** The recorded runs the page can play, from the list beside the traces. */
let recorded: RecordedRun[] = [];

async function loadRecordedList(): Promise<void> {
  try {
    recorded = ((await (await fetch("traces/index.json")).json()) as { runs: RecordedRun[] }).runs;
  } catch {
    recorded = [];
  }
  const pick = element<HTMLSelectElement>("replay-pick");
  pick.innerHTML = recorded.map((run) => `<option value="${run.file}">${run.name}</option>`).join("");
  pick.value = replayOf.trace;
  pick.hidden = recorded.length === 0;
  if (recorded.length > 0) element("hood-replay-says").textContent = `${["No", "One", "Two", "Three", "Four", "Five", "Six"][recorded.length] ?? recorded.length} runs of the full model on real San Francisco days, replayed step by step.`;
}

/** Counts mode changes and run choices. Anything that waited on the network checks it is still the latest before it writes. */
let turn = 0;

async function loadReplay(mine: number): Promise<void> {
  const note = element("replay-note");
  try {
    const file = (await (await fetch(replayOf.trace)).json()) as TraceFile;
    let other: TraceFile | null = null;
    if ((file.plans ?? []).length > 0 && replayOf.compare) {
      // The comparison is an extra: a recording without it still plays.
      try {
        other = (await (await fetch(replayOf.compare)).json()) as TraceFile;
      } catch {
        other = null;
      }
    }
    // The visitor may have left this mode, or picked another run, while the recording was on its way.
    if (mine !== turn) return;
    state.meta = file.meta;
    state.steps = unpack(file);
    state.followed = null;
    plans = file.plans ?? [];
    element("mpc").hidden = plans.length === 0;
    simple = other ? unpack(other) : null;
    for (const id of ["compare-head", "compare", "compare-note"]) element(id).hidden = !simple;
    if (plans.length > 0 && simple) {
      element("compare").innerHTML = compareRuns(state.steps, simple);
      element("compare-note").textContent =
        "Both runs replay the same real days with the same depot, fleet, chargers and power rule; only the way vehicles are called in differs. " +
        "The first day is left out as warm-up. Prices are PG&E's BEV-2-P sheet of March 2026.";
    }
    state.otherSteps = null;
    state.head = 0;
    markDirty();
    element<HTMLInputElement>("scrub").max = String(state.steps.length - 2);
    const [recall, power] = file.meta.label.split(" + ");
    const listed = recorded.find((run) => run.file === replayOf.trace);
    element<HTMLSelectElement>("replay-pick").value = replayOf.trace;
    note.textContent =
      (listed ? `${listed.note} ` : "") +
      `${file.meta.depot.replace(/\d{4,}/g, (count) => whole(Number(count)))}, ${file.meta.chargers} chargers of ${file.meta.charger_kw} kW, ` +
      `${whole(file.meta.site_limit_kw)} kW from the grid. Vehicles are ${RULE_NAMES[recall] ?? recall} and ${RULE_NAMES[power] ?? power}. Rides are replayed from real San Francisco days, from Monday 15 April 2024.` +
      (replayOf.model ? ` The plan is working from the forecast of ${replayOf.model}.` : "");
    state.holds = `replay:${replayOf.trace}`;
    showRunning("replay");
    element("mode-note").textContent = plans.length > 0
      ? `This run was recorded from the full model, with the day-ahead plan${state.steps.some((s) => s.promised !== null) ? " and its hourly promise" : ""}.`
      : "This run was recorded from the full model. Vehicles are called in by a fixed rule here: no plan ran.";
  } catch {
    if (mine !== turn) return;
    note.textContent = "The recorded run didn't load.";
    element("mode-note").textContent = "No recorded run is loaded.";
    state.steps = [];
    // Nothing of the live depot may stay on screen under this tab's name.
    for (const id of ["floor", "pulse"]) {
      const canvas = element<HTMLCanvasElement>(id);
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    }
    element("readouts").innerHTML = failed("The recorded run didn't load.", "replay");
  }
}

// What each part of the picture is made of, in each mode. The two modes differ, and the page should never
// leave a visitor thinking the browser is running something it is not.
const METHOD_LINK = `<a href="https://github.com/yannickYamo/depot-twin/blob/main/docs/METHOD.md">docs/METHOD.md</a>`;
const SITE =
  "A hypothetical depot on a 14.5-acre industrial parcel on San Leandro Street, East Oakland. Two 12 kV feeders nearby each offer about 2.75 MW on PG&E's public capacity map, so one connection is 2.75 MW and two are 5.5 MW";
const SITE_ROW =
  `${SITE}. The load manager draws at most 95% of it. Details in ${METHOD_LINK}.`;
/** The recordings have no dials: each was made with one fleet, one connection and one rule. */
const SITE_ROW_RECORDED =
  `${SITE}. The load manager draws at most 95% of it. Each recording has one fleet, one connection and one calling rule. Details in ${METHOD_LINK}.`;

const RUNNING: Record<"play" | "replay", [string, string][]> = {
  play: [
    ["Site", SITE_ROW],
    ["Depot and fleet", "A simulator in this page: every vehicle, charger, person and cleaning bay, stepped a minute at a time. A second implementation of the Python model, held to it by a test."],
    ["Rides", "Drawn at random around an average San Francisco week, built from the city's public taxi records, scaled to the fleet."],
    ["Who is called in", "A simple rule you choose: at a battery level, or in slots paced to the chargers. No optimizer runs here."],
    ["Forecast", "The week's usual pattern, with a fixed margin above it. No trained model runs here."],
    ["Vehicle energy use", "Fixed figures per vehicle type, with each vehicle a little different."],
    ["Grid", "Real: California ISO net demand and emissions, week of 15 April 2024, lined up with the depot's clock."],
  ],
  replay: [
    ["Site", SITE_ROW_RECORDED],
    ["Depot and fleet", "The Python model, recorded step by step at the East Oakland site."],
    ["Rides", "Real: San Francisco taxi trips from Monday 15 April 2024, five minutes at a time, scaled to the fleet. Days the forecast never trained on."],
    ["Who is called in", "Model predictive control. Every hour a linear program plans the next 24 hours against the forecast's upper bound, the first hour of the plan is carried out, and the plan is made again an hour later from where the fleet then stands."],
    ["Forecast", "Trained: gradient-boosted trees (XGBoost) for 1, 6 and 24 hours ahead, with an upper bound measured on days held back from training."],
    ["Vehicle energy use", "Estimated for each vehicle from its own telemetry as the run goes, and fed to the plan."],
    ["Grid", "Real: California ISO net demand and emissions for the same week."],
  ],
};

/** What is running, with the recording's own fleet, connection and rule where a recording is playing. */
function showRunning(mode: "play" | "replay"): void {
  let rows = RUNNING[mode];
  if (mode === "replay" && state.meta && state.steps.length > 0) {
    const meta = state.meta;
    const planned = plans.length > 0;
    rows = rows.map(([part, what]): [string, string] => {
      if (part === "Depot and fleet") return [part, `The Python model, recorded step by step: ${whole(meta.fleet)} vehicles on ${whole(meta.site_limit_kw)} kW at the East Oakland site.`];
      if (part === "Who is called in" && !planned) return [part, "A fixed rule: a vehicle is called in when its battery falls to a set level. No plan and no optimizer ran in this recording."];
      if (part === "Forecast" && !planned) return [part, "None is used: the rule in this recording does not look ahead. The forecast drawn on the charts is shown for reference."];
      if (part === "Vehicle energy use" && !planned) return [part, "Fixed figures per vehicle type, with each vehicle a little different."];
      return [part, what];
    });
  }
  element("running").innerHTML = rows.map(([part, what]) => `<tr><th scope="row">${part}</th><td>${what}</td></tr>`).join("");
}

/** What stands under the title: the short version says what it is, the twin states its one idea and its answer. */
const LEDES: Record<"short" | "full", string> = {
  short: "The short version: the decision, the answer and what to do first.",
  full: IDEA,
};

let lastFull: Exclude<Mode, "short"> = "play";
const unknowns: Unknowns = { ...OPENING };
let outcomeSettled = false;

function showBrief(): void {
  // Nothing is said until the figures have arrived or failed to.
  if (!outcome && !outcomeSettled) return;
  element("brief").innerHTML = outcome ? briefMarkup(outcome, unknowns, models) : failed("The figures didn't load.", "outcome");
}

/** The short version's one control moves the energy estimate between measured cases; one button opens the twin. */
function onBrief(event: Event): void {
  const target = event.target as HTMLElement;
  if (target.closest("[data-full]")) {
    void setMode("play").then(() => { window.scrollTo(0, 0); element("mode-play").focus(); });
    return;
  }
  const pick = target.closest<HTMLElement>("[data-road]");
  if (!pick || !outcome) return;
  const asked: Unknowns = { road: pick.dataset.road as Unknowns["road"], parked: pick.dataset.parked === "1" };
  if (!carried(outcome, asked)) return;
  Object.assign(unknowns, asked);
  showCase(element("bf-unknowns"), outcome, unknowns);
}

// Where a link lands. Each place has its name in the address, and an alias so that older links still open.
const ROUTES: Record<string, [Exclude<Mode, "short">, Part?]> = {
  depot: ["play"], play: ["play"],
  decisions: ["outcome"], outcome: ["outcome"],
  hood: ["hood"], story: ["hood"],
  forecasts: ["hood", "model"], model: ["hood", "model"],
  account: ["hood", "money"], money: ["hood", "money"],
  recorded: ["hood", "replay"], replay: ["hood", "replay"],
};
const PART_HASH: Record<Part, string> = { model: "forecasts", money: "account", replay: "recorded" };
const routed = (): [Exclude<Mode, "short">, Part?] | undefined => ROUTES[location.hash.slice(1)];

/** Where the link that opened the page points, read before anything rewrites the address. */
const firstRoute = routed();
const openFull = new URLSearchParams(location.search).get("view") === "full";
let resumeOnReturn = false;
/** A recording that reached its end stopped the player itself; the live depot should not come back stopped for that. */
let stoppedAtEnd = false;

const partBox = (part: Part): HTMLDetailsElement => element<HTMLDetailsElement>(`hood-${part}`);
/** The part opened last, which the address names. */
let lastPart: Part | null = null;

/** The address of what is on screen, so a copied link opens the same place. */
function address(): string {
  if (state.mode === "short") return location.pathname;
  const part = lastPart && partBox(lastPart).open ? lastPart : PARTS.find((key) => partBox(key).open);
  const hash = state.mode === "play" ? "" : state.mode === "outcome" ? "#decisions" : `#${part ? PART_HASH[part] : "hood"}`;
  return `${location.pathname}?view=full${hash}`;
}

/** Fill a part under the hood. Called when it is opened, so its charts are drawn at their real size. */
async function showPart(part: Part): Promise<void> {
  if (part === "model") {
    await workbench.show();
  } else if (part === "money") {
    await money.show();
  }
}

/** What the depot's floor should be showing for the page on screen, or null where it has no place. */
function benchWanted(): "play" | "replay" | null {
  if (state.mode === "play") return "play";
  return state.mode === "hood" && partBox("replay").open ? "replay" : null;
}

let benchShown: "play" | "replay" | null | undefined;

/**
 * Put the depot's floor where the page on screen wants it: under the Depot tab running live, inside the
 * recorded-run part playing a recording, or away. The floor, its charts and its figures are one set of
 * elements, moved between the two places.
 */
async function settleBench(): Promise<void> {
  const mine = ++turn;
  const want = benchWanted();
  benchShown = want;
  const floorBox = document.querySelector<HTMLElement>(".bench")!;
  const colophon = document.querySelector<HTMLElement>(".colophon")!;
  floorBox.hidden = colophon.hidden = want === null;
  if (want === null) {
    element("demand-box").hidden = true;
    // The depot waits while another page is open, and carries on when the visitor comes back to it.
    if (state.playing) resumeOnReturn = true;
    setPlaying(false);
    return;
  }
  const home = element(want === "play" ? "depot-home" : "replay-home");
  if (floorBox.parentElement !== home) home.append(floorBox, colophon);
  bench = want;
  element("mpc").hidden = want !== "replay" || plans.length === 0;
  if (resumeOnReturn || (want === "play" && stoppedAtEnd && !still())) setPlaying(true);
  resumeOnReturn = false;
  stoppedAtEnd = false;
  element("controls").hidden = want !== "play";
  element("demand-box").hidden = want !== "play";
  if (want === "play") void showDemand();
  element("replay-box").hidden = want !== "replay";
  element("scrub-box").hidden = want !== "replay";
  element("mode-note").textContent =
    want === "play"
      ? "Runs in your browser on an average San Francisco week. A test holds it to the full model: within half a point of rides served where every ride is served, and a point and a half where some are lost. The day-ahead plan and the trained forecasts are in the recorded run."
      : "Loading the recorded run.";
  showRunning(want);
  showAlerts();
  showWatching();
  // Coming back to the depot, it is as it was left: only a change of what is running starts it again.
  if (want === "play") {
    if (state.holds !== "play") startAgain();
    else markDirty();
  } else if (state.holds !== `replay:${replayOf.trace}`) {
    state.steps = [];
    state.holds = "";
    await loadReplay(mine);
  } else {
    markDirty();
    showRunning("replay");
    element("mode-note").textContent = plans.length > 0
      ? `This run was recorded from the full model, with the day-ahead plan${state.steps.some((s) => s.promised !== null) ? " and its hourly promise" : ""}.`
      : "This run was recorded from the full model. Vehicles are called in by a fixed rule here: no plan ran.";
  }
}

async function setMode(mode: Mode, part?: Part): Promise<void> {
  state.mode = mode;
  element("mode-play").setAttribute("aria-selected", String(mode === "play"));
  element("mode-outcome").setAttribute("aria-selected", String(mode === "outcome"));
  element("mode-hood").setAttribute("aria-selected", String(mode === "hood"));
  // The short version stands in front of the three tabs; the full twin is everything else.
  if (mode !== "short") lastFull = mode;
  element("view-short").setAttribute("aria-checked", String(mode === "short"));
  element("view-full").setAttribute("aria-checked", String(mode !== "short"));
  document.querySelector<HTMLElement>(".modes")!.hidden = mode === "short";
  element("brief").hidden = mode !== "short";
  element("hood").hidden = mode !== "hood";
  if (part) {
    lastPart = part;
    partBox(part).open = true;
  }
  history.replaceState(null, "", address());
  element("lede-text").textContent = LEDES[mode === "short" ? "short" : "full"];
  element("answer").hidden = mode === "short" || !outcome;
  showImpact();
  if (mode === "short") showBrief();
  const settled = settleBench();
  if (mode === "hood") await Promise.all(PARTS.filter((key) => partBox(key).open).map(showPart));
  await settled;
}

// ---------------------------------------------------------------------------------------------------
// Drawing.

function readout(label: string, value: string, note: string, wide = false): string {
  return `<div${wide ? ' class="wide"' : ""}><dt>${label}</dt><dd>${value}<small>${note}</small></dd></div>`;
}

function servedShare(steps: Step[]): number {
  const served = steps.reduce((sum, s) => sum + s.served, 0);
  const lost = steps.reduce((sum, s) => sum + s.lost, 0);
  return served + lost > 0 ? served / (served + lost) : 1;
}

function drawNumbers(index: number): void {
  const step = state.steps[index];
  const from = Math.max(0, index - DAY + 1);
  const day = state.steps.slice(from, index + 1);
  const lost = day.reduce((sum, s) => sum + s.lost, 0);
  const span = index + 1 >= DAY ? "last 24 hours" : "since the run began";
  let html =
    readout(`Rides served, ${span}`, percent(servedShare(day)), `${whole(lost)} lost`) +
    (outcome ? readout(`Fares, ${span}`, dollars(day.reduce((sum, s) => sum + s.served, 0) * outcome.fare_per_ride), lost > 0 ? `${dollars(lost * outcome.fare_per_ride)} not earned on rides lost` : "no ride lost") : "") +
    readout("On the road", whole(step.on_road), `of ${whole(state.meta.fleet)}`) +
    readout("Waiting for a charger", whole(step.queued), `${step.charging} charging`) +
    readout("Visits a vehicle-day", visitsPerVehicleDay(day).toFixed(1), "the filings' fleet charges about three times a day") +
    readout("Power from the grid", `${whole(step.grid_kw)} kW`, `of ${whole(state.meta.usable_kw ?? state.meta.site_limit_kw)} kW usable`);
  if (state.otherSteps) {
    const share = servedShare(state.otherSteps.slice(from, index + 1));
    html += readout(`Same depot, ${otherName()}`, percent(share), `of rides served over the same ${span === "last 24 hours" ? "24 hours" : "run"}`, true);
    if (outcome) {
      const other = state.otherSteps.slice(from, index + 1);
      const more = day.reduce((sum, s) => sum + s.served, 0) - other.reduce((sum, s) => sum + s.served, 0);
      html += readout(`Against that depot, ${span}`, `${more < 0 ? "−" : "+"}${dollars(Math.abs(more) * outcome.fare_per_ride)}`, `in fares: ${whole(Math.abs(more))} rides ${more < 0 ? "fewer" : "more"}`, true);
      const run = since.mine - since.other;
      const days = (since.steps * STEP_MIN) / 1440;
      if (days >= 1) html += readout(`Against that depot, over the ${days.toFixed(0)} days of this run`, `${run < 0 ? "−" : "+"}${dollars(Math.abs(run) * outcome.fare_per_ride)}`, `in fares: ${whole(Math.abs(run))} rides ${run < 0 ? "fewer" : "more"}. A gap that is small in a day adds up`, true);
    }
  }
  if (grid) {
    const strain = grid.strain(step.minute);
    const word = strain < 0.33 ? "easy" : strain < 0.66 ? "moderate" : "strained";
    html += readout(
      "California grid, net demand",
      `${(Math.max(0, grid.netDemand(step.minute)) / 1000).toFixed(1)} GW`,
      `${word}; ${whole(grid.carbon(step.minute))} g of CO2 per kWh`,
      true,
    );
  }
  element("readouts").innerHTML = html;
  element("clock").textContent = `${clock(step.minute)}${step.tariff === "peak" ? ", peak price" : ""}`;
}

function drawCharts(index: number): void {
  const live = bench === "play";
  const shown = live ? state.steps.slice(0, index + 1) : state.steps;
  hours = hourly(shown);
  const other = state.otherSteps ? hourly(state.otherSteps.slice(0, index + 1)) : null;
  const now = live ? null : state.steps[index].minute;
  drawRides(rides, hours, other, otherName(), now);
  drawRoad(road, hours, state.meta.fleet, now);
  const day = state.steps.slice(Math.max(0, index - DAY + 1), index + 1);
  drawPulse(pulse, state.meta, day);
  drawForecast(shown, live);
  if (grid) drawStrain(shown, day);
}

/** The forecast chart and the line under it that scores the forecast over what is shown. */
function drawForecast(shown: Step[], live: boolean): void {
  const pairs = outlook(shown, live ? STEP_MIN : 0);
  drawOutlook(outlookCanvas, pairs);
  const score = outlookScore(pairs);
  if (pairs.length < 2) return;
  element("outlook-probe").textContent =
    `One hour ahead: ${percent(score.error)} error, upper bound held ${percent(score.held)} of hours. ` +
    (live ? "Forecast here: the week's usual pattern, not the trained model."
      : replayOf.model ? `Forecast here: ${replayOf.model}, on days it never trained on.`
      : "Forecast here: the trained model, on days it never trained on.");
}

/** The grid chart and the line under it: what the depot's last day of charging meant for the grid. */
function drawStrain(shown: Step[], day: Step[]): void {
  if (!grid) return;
  drawGridStrain(strainCanvas, grid, shown, state.meta.site_limit_kw);
  const mark = grid.footprint(day);
  element("strain-probe").textContent =
    `Last 24 hours: ${percent(mark.hardShare)} of the depot's energy drawn in the grid's hardest hours; ` +
    `${whole(mark.carbon)} g CO2/kWh against the grid's ${whole(mark.gridCarbon)}. California ISO, week of ${grid.week.week_of}.`;
}

/** The plan as it stands at a step: its figures and its two charts. */
function drawPlan(index: number): void {
  if (plans.length === 0 || bench !== "replay") return;
  const { current } = plansAt(plans, index);
  if (!current) return;
  const made = plans.filter((plan) => plan.step <= index).length;
  const step = state.steps[index];
  element("plan-figures").innerHTML =
    readout("Plan in force", clock(current.minute), `the ${made}${made % 10 === 1 && made !== 11 ? "st" : made % 10 === 2 && made !== 12 ? "nd" : made % 10 === 3 && made !== 13 ? "rd" : "th"} plan of this run`) +
    readout("Call in this hour", whole(current.quota), `${whole(current.visits.reduce((a, b) => a + b, 0))} visits planned over the day`) +
    readout("Promised on the road", whole(current.committed), `${whole(step.on_road)} there now`) +
    readout("Energy in hand by tomorrow", `${whole(current.energy_kwh[23] / 1000)} MWh`, "across the fleet's batteries, as the plan expects");
  drawPlannedVisits(element<HTMLCanvasElement>("plan-visits"), state.steps, plans, index);
  drawPlannedRoad(element<HTMLCanvasElement>("plan-road"), state.steps, plans, index, state.meta.fleet);
}

/** Depot visits per vehicle per day over the steps shown, from arrivals. */
function visitsPerVehicleDay(steps: Step[]): number {
  if (steps.length === 0) return 0;
  const arrivals = steps.reduce((sum, s) => sum + s.arrivals, 0);
  return (arrivals / state.meta.fleet) * (DAY / steps.length);
}

function drawVehicles(index: number): void {
  const step = state.steps[index];
  // The list is drawn only while it is open; opening it draws the current step at once.
  if (chainOpen.open) renderChain(element("chain"), step, state.followed);
  const stall = step.stalls.find((entry) => entry[1] === state.followed);
  const history = state.steps.slice(Math.max(0, index - DAY + 1), index + 1);
  renderFollowed(element("followed"), history, state.followed, stall ? stall[0] : null, stall ? stall[3] : null);
}

function draw(): void {
  if (state.steps.length < 2) return;
  const index = Math.min(state.steps.length - 2, Math.max(0, Math.floor(state.head)));
  const mix = still() ? 0 : Math.min(1, Math.max(0, state.head - index));
  const minutes = (index + mix) * STEP_MIN;
  drawn = drawFloor(floor, {
    meta: state.meta,
    step: state.steps[index],
    next: state.steps[index + 1],
    mix,
    flow: still() ? 0.5 : minutes / 15,
    followed: state.followed,
  });
  if (index === state.drawnStep) return;
  state.drawnStep = index;
  drawNumbers(index);
  drawCharts(index);
  drawVehicles(index);
  drawPlan(index);
  showAlerts();
  if (bench === "replay") element<HTMLInputElement>("scrub").value = String(index);
}

function setPlaying(playing: boolean): void {
  state.playing = playing;
  element("play").textContent = playing ? "Pause" : "Play";
  wake();
}

/** Mark the picture as out of date and make sure it gets drawn. */
function markDirty(): void {
  state.drawnStep = -1;
  wake();
}

/** The drawing loop runs while there is something to draw: a depot playing, or a picture that has changed. */
let looping = false;
function wake(): void {
  if (looping) return;
  looping = true;
  lastFrame = performance.now();
  requestAnimationFrame(frame);
}

let lastFrame = performance.now();

function frame(time: number): void {
  // A hidden tab can leave a long gap between frames; never jump more than a tenth of a second.
  const elapsed = Math.min(0.1, (time - lastFrame) / 1000);
  lastFrame = time;
  heedMotion();
  if (state.playing && state.steps.length >= 2) {
    state.head += (elapsed * state.speed * MINUTES_PER_SECOND) / STEP_MIN;
    if (bench === "play") {
      while (state.head > state.steps.length - 2) advanceSim();
    } else if (state.head >= state.steps.length - 2) {
      state.head = state.steps.length - 2;
      setPlaying(false);
      stoppedAtEnd = true;
    }
  }
  const before = state.drawnStep;
  draw();
  // Paused with the picture up to date: stop, and start again when something asks (`wake`).
  if (!state.playing && (state.steps.length < 2 || (before !== -1 && state.drawnStep === before))) {
    looping = false;
    return;
  }
  requestAnimationFrame(frame);
}

function probe(canvas: HTMLCanvasElement, target: string, describe: (hour: Hour) => string): void {
  canvas.addEventListener("pointermove", (event) => {
    const hour = hourAt(canvas, hours, event.clientX);
    if (hour) element(target).textContent = `${clock(hour.minute)}: ${describe(hour)}`;
  });
}

const AT: Record<number, string> = {
  0: "on the road",
  [PLACE.inbound]: "driving in",
  [PLACE.queued]: "waiting for a charger",
  [PLACE.pluggingIn]: "waiting for staff to plug it in",
  [PLACE.charging]: "charging",
  [PLACE.afterCharging]: "done charging, waiting for staff to unplug it",
  [PLACE.cleaning]: "being cleaned",
  [PLACE.outbound]: "driving out",
};

interface DemandArea {
  radius_km: number; tracts: number; population: number; density: number; rides_per_day: number; vehicles_at_25_rides: number;
  feeders_needed: number; months_until_second_feeder: number | null; months_until_second_feeder_at_half_the_growth: number | null;
  months_until_second_feeder_range?: [number, number] | null;
  months_on_the_growth_since_the_footprint_settled?: [number, number] | null;
}
interface Demand {
  penetration_trips_per_resident_month: number; growth_per_month: number; growth_since_the_footprint_settled?: number; capacity_one_feeder: number; planned_one_feeder: number; served_at_the_limit_one_feeder: number; rides_per_vehicle_day: number;
  growth_per_month_by_estimate?: Record<string, number>;
  areas: Record<string, DemandArea>; run: string;
}
let demand: Demand | null = null;
let demandArea = "east_bay_20km";
const AREA_NAMES: Record<string, string> = { oakland_8km: "8 km: East Oakland, San Leandro, Alameda", east_bay_15km: "15 km: Oakland, Emeryville, Hayward", east_bay_20km: "20 km: Alameda County's East Bay" };

/** Months until one feeder is outgrown, as the span over the readings of growth. */
function growthSpan(area: DemandArea, soon: number | null): string {
  // The months on the growth since the service area was last enlarged, where the file has them.
  const span = area.months_on_the_growth_since_the_footprint_settled ?? area.months_until_second_feeder_range;
  if (soon === 0 || span?.[1] === 0) return "now";
  if (!span && soon === null) return "not at this growth";
  if (!span || span[0] === span[1]) return `${whole(soon ?? span?.[0] ?? 0)} months`;
  return `${whole(span[0])} to ${whole(span[1])} months`;
}


/** Where the rides come from: the service area around the parcel, what it produces today, and when it outgrows a feeder. */
async function showDemand(): Promise<void> {
  const box = element("demand-box");
  if (!demand) {
    try {
      const loaded = (await (await fetch("demand.json")).json()) as Partial<Demand>;
      if (!loaded.areas || typeof loaded.capacity_one_feeder !== "number" || typeof loaded.planned_one_feeder !== "number") throw new Error("demand.json is not the file this page reads");
      demand = loaded as Demand;
    } catch {
      box.hidden = true;
      return;
    }
    // The fleet alert sets the measured capacity beside its arithmetic, so it is written again with the figures in.
    showAlerts();
  }
  // The figures may arrive after the visitor has gone to another mode; the box belongs to the live depot only.
  if (state.mode !== "play") return;
  const area = demand.areas[demandArea];
  const chips = Object.keys(demand.areas).map((k) => `<button type="button" role="radio" aria-checked="${k === demandArea}" data-area="${k}">${AREA_NAMES[k] ?? k}</button>`).join("");
  const soon = area.months_until_second_feeder;
  box.innerHTML =
    `<h3 class="aside-title">Where the rides come from</h3>` +
    `<div class="presets" role="radiogroup" aria-label="Service area">${chips}</div>` +
    `<dl class="readouts demand-figures">` +
    `<div><dt>Residents</dt><dd>${whole(area.population)}<small>${whole(area.tracts)} census tracts</small></dd></div>` +
    `<div><dt>Rides a day today</dt><dd>${whole(area.rides_per_day)}<small>at ${demand.penetration_trips_per_resident_month.toFixed(2)} trips a resident a month, the filings' penetration</small></dd></div>` +
    `<div><dt>Vehicles that is</dt><dd>${whole(area.vehicles_at_25_rides)}<small>at ${demand.rides_per_vehicle_day} rides a vehicle-day; one feeder is planned for ${whole(demand.planned_one_feeder)}${area.vehicles_at_25_rides < SLIDERS[0].min ? `; the smallest fleet this page runs is ${whole(SLIDERS[0].min)}` : ""}</small></dd></div>` +
    `<div><dt>Growth scenario</dt><dd>${growthSpan(area, soon)}<small>${soon === 0 ? "the area already outgrows one feeder" : `until the planned fleet is outgrown, at the ${percent(demand.growth_since_the_footprint_settled ?? 0)} a month in the filings since the service area last changed. A scenario, not a forecast`}</small></dd></div>` +
    `</dl>` +
    `<button type="button" id="size-to-area" class="solid">Size the fleet to this area</button>` +
    `<p class="quiet">From public filings and census populations, within straight-line distance in Alameda County. No density adjustment: a sparser area likely produces less.</p>`;
  box.hidden = false;
  box.querySelectorAll<HTMLElement>("[data-area]").forEach((chip) => chip.addEventListener("click", () => { demandArea = chip.dataset.area!; void showDemand(); }));
  box.querySelector("#size-to-area")?.addEventListener("click", () => {
    params.fleet = Math.max(SLIDERS[0].min, Math.min(SLIDERS[0].max, Math.round(area.vehicles_at_25_rides / 50) * 50));
    params.ridesPerVehicleDay = demand!.rides_per_vehicle_day; // the figure the vehicle count was worked out at
    touched.add("fleet");
    if (!touched.has("staff")) params.staff = Math.max(4, Math.floor(params.fleet / 40));
    if (!touched.has("chargers")) params.chargers = Math.min(240, Math.round((params.fleet * 0.132) / 2) * 2);
    startAgain();
    syncControls();
  });
}

/** The vehicle mark under the pointer, if any. */
function hitAt(event: PointerEvent | MouseEvent): Hit | null {
  if (!drawn) return null;
  const box = floor.getBoundingClientRect();
  const scale = drawn.width / box.width;
  const x = (event.clientX - box.left) * scale;
  const y = (event.clientY - box.top) * scale;
  let best: Hit | null = null;
  let nearest = Infinity;
  for (const hit of drawn.hits) {
    const distance = Math.hypot(hit.x - x, hit.y - y);
    if (distance <= hit.r + 3 && distance < nearest) [best, nearest] = [hit, distance];
  }
  return best;
}

function follow(vehicle: number | null): void {
  state.followed = vehicle === state.followed ? null : vehicle;
  markDirty();
}

/** Hovering names a vehicle; clicking one, on the floor or in the lists, follows it. */
function wireVehicles(): void {
  const tip = element("tip");
  floor.addEventListener("pointermove", (event) => {
    const hit = hitAt(event);
    floor.style.cursor = hit ? "pointer" : "default";
    tip.hidden = !hit;
    if (!hit) return;
    const parts = [vehicleName(hit.vehicle), AT[hit.place]];
    if (hit.place !== 0) parts.push(`${hit.soc}%`);
    if (hit.kw !== undefined) parts.push(hit.kw >= 1 ? `${hit.kw} kW` : "no power yet");
    tip.textContent = parts.join(", ");
    const stage = floor.parentElement!.getBoundingClientRect();
    tip.style.left = `${Math.min(stage.width - 220, Math.max(8, event.clientX - stage.left + 12))}px`;
    tip.style.top = `${event.clientY - stage.top + 14}px`;
  });
  floor.addEventListener("pointerleave", () => (tip.hidden = true));
  floor.addEventListener("click", (event) => {
    const hit = hitAt(event);
    if (hit) follow(hit.vehicle);
  });
  element("chain").addEventListener("click", (event) => {
    const chosen = (event.target as HTMLElement).closest<HTMLElement>("[data-vehicle]");
    if (chosen) follow(Number(chosen.dataset.vehicle));
  });
  chainOpen.addEventListener("toggle", () => {
    if (chainOpen.open && state.steps.length > 1) renderChain(element("chain"), state.steps[Math.min(state.steps.length - 2, Math.max(0, Math.floor(state.head)))], state.followed);
  });
  // Escape lets go of the vehicle being followed, wherever the focus is.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.followed !== null) follow(state.followed);
  });
  element("followed").addEventListener("click", (event) => {
    if ((event.target as HTMLElement).id === "unfollow") follow(state.followed);
  });
}

const ML_LINK = "https://github.com/yannickYamo/depot-twin/blob/main/docs/ML.md";

interface Facts {
  forecast: { hours_ahead: number; error: number; same_hour_last_week: number; upper_bound_held: number; no_history_error_against_last_week: number[] }[];
}

/** Under the forecast chart: how the trained forecast scored in its registered tests. Figures come from the result files. */
async function showFacts(): Promise<void> {
  try {
    const facts = (await (await fetch("facts.json")).json()) as Facts;
    // The number of held-out days is the forecast record's own; the caption does without it if that file is missing.
    const days = await fetch("trust.json").then((got) => got.json()).then((trust: { card?: { holdout_days?: number } }) => trust.card?.holdout_days ?? null).catch(() => null);
    const rows = facts.forecast.map((row) =>
      `<tr><th scope="row">${row.hours_ahead} h ahead</th><td>${percent(row.error)}</td><td>${percent(row.same_hour_last_week)}</td>` +
      `<td>${percent(row.upper_bound_held)}</td><td>${Math.round(row.no_history_error_against_last_week[0] * 100)} to ` +
      `${Math.round(row.no_history_error_against_last_week[1] * 100)}%</td></tr>`);
    element("facts").innerHTML =
      `<h2>One, six and 24 hours ahead</h2><table><caption>The trained forecast on San Francisco taxi rides, ${days ? `${whole(days)} held-out days` : "held-out days"}. ` +
      `The 26-week comparison in three cities is in <a href="${ML_LINK}">docs/ML.md</a>.</caption><thead><tr><td></td><th scope="col">Error</th>` +
      `<th scope="col">Same hour last week</th><th scope="col">Upper bound held</th>` +
      `<th scope="col">With no local history, against last week</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
  } catch {
    element("facts").textContent = "";
  }
}

const workbench = new WorkbenchView(element("workbench"), (trace, model) => {
  replayOf = { trace, model, compare: null };
  void setMode("hood", "replay").then(() => {
    // A visitor who asked for less motion starts the recording themselves.
    setPlaying(!still());
    document.querySelector(".stage")?.scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "start" });
  });
});

const money = new MoneyView(element("money"), () => grid);

/** The width under which the page is one column (the same figure as the stylesheet's). */
const onePage = window.matchMedia("(max-width: 1020px)");

let wasStill = still();

/**
 * A visitor who turns reduced motion on while the depot runs gets a still page at once: the depot pauses and
 * is drawn where it stands. Turning it off again leaves the depot paused until they press Play. Asked on every
 * frame as well as on the browser's own notice, because a browser that has just been asked whether the
 * setting holds may not send the notice.
 */
function heedMotion(): void {
  if (still() === wasStill) return;
  wasStill = still();
  if (wasStill) {
    resumeOnReturn = false;
    stoppedAtEnd = false;
    setPlaying(false);
  }
  markDirty();
}

/**
 * In one column the settings, the alerts and the figures sit straight under the depot they change, so a
 * visitor can move a slider and watch the floor. Side by side they stay in the rail. The elements are moved,
 * not reordered by the stylesheet, so the order a keyboard or a screen reader meets them in is the order shown.
 */
function placeSettings(narrow: boolean): void {
  const parts = ["controls", "replay-box", "alerts", "readouts"].map((id) => element(id));
  if (narrow) {
    document.querySelector(".stage")!.after(...parts);
  } else {
    const side = document.querySelector(".side")!;
    side.prepend(element("readouts"), element("alerts"));
    // The settings come before the service area: they are what a visitor changes first.
    side.append(element("controls"), element("replay-box"), element("demand-box"));
  }
}

function wire(): void {
  element("play").addEventListener("click", () => {
    if (!state.playing && bench === "replay" && state.head >= state.steps.length - 2) state.head = 0;
    stoppedAtEnd = false;
    setPlaying(!state.playing);
  });
  element("reset").addEventListener("click", () => {
    if (bench === "play") startAgain();
    else state.head = 0;
    markDirty();
  });
  element("speed").addEventListener("click", (event) => {
    const chosen = (event.target as HTMLElement).closest<HTMLElement>("[data-speed]");
    if (!chosen) return;
    state.speed = Number(chosen.dataset.speed);
    element("speed").querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-checked", String(button === chosen));
    });
  });
  wireVehicles();
  element<HTMLInputElement>("scrub").addEventListener("input", (event) => {
    state.head = Number((event.target as HTMLInputElement).value);
    wake();
  });
  element("view-short").addEventListener("click", () => void setMode("short"));
  element("view-full").addEventListener("click", () => void setMode(lastFull));
  element("brief").addEventListener("click", onBrief);
  element("mode-play").addEventListener("click", () => void setMode("play"));
  element("mode-outcome").addEventListener("click", () => void setMode("outcome"));
  element("mode-hood").addEventListener("click", () => void setMode("hood"));
  for (const part of PARTS) {
    partBox(part).addEventListener("toggle", () => {
      const open = partBox(part).open;
      if (open) lastPart = part;
      if (state.mode !== "short") history.replaceState(null, "", address());
      if (part === "replay") {
        if (benchWanted() !== benchShown) void settleBench();
      } else if (open && state.mode === "hood") {
        void showPart(part);
      }
    });
  }
  element<HTMLSelectElement>("replay-pick").addEventListener("change", (event) => {
    const chosen = recorded.find((run) => run.file === (event.target as HTMLSelectElement).value);
    if (!chosen) return;
    replayOf = { trace: chosen.file, model: "", compare: chosen.compare };
    void settleBench();
  });
  element("watching").addEventListener("click", onImpact);
  element("impact").addEventListener("click", onImpact);
  element("impact").addEventListener("click", (event) => {
    if (!(event.target as HTMLElement).closest('[data-goto="model"]')) return;
    void setMode("hood", "model").then(() => {
      const summary = partBox("model").querySelector<HTMLElement>("summary");
      summary?.scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "start" });
      summary?.focus({ preventScroll: true });
    });
  });
  // A file that didn't arrive is asked for again where the page says so.
  document.addEventListener("click", (event) => {
    const what = (event.target as HTMLElement).closest<HTMLElement>("[data-retry]")?.dataset.retry;
    if (what === "outcome") void loadOutcome();
    else if (what === "model" || what === "money") void showPart(what);
    else if (what === "replay") {
      state.holds = "";
      void settleBench();
    }
  });
  window.addEventListener("resize", () => (markDirty()));
  lessMotion.addEventListener("change", heedMotion);
  onePage.addEventListener("change", () => placeSettings(onePage.matches));
  placeSettings(onePage.matches);
  probe(rides, "rides-probe", (hour) =>
    `${whole(hour.offered)} rides offered, ${whole(hour.served)} served, ${whole(hour.lost)} given up on`);
  probe(road, "road-probe", (hour) =>
    `${whole(hour.onRoad)} vehicles on the road` + (hour.promised === null ? "" : `, ${whole(hour.promised)} promised`));
}

buildControls();
wire();
setPlaying(state.playing);
void showFacts();
void loadRecordedList();
/** The figures every view states. Asked for at the start, and again if the visitor asks after a failure. */
async function loadOutcome(): Promise<void> {
  try {
    const loaded: unknown = await (await fetch("outcome.json")).json();
    // A file of the wrong shape is treated like a file that did not arrive: the view says so.
    outcome = isOutcome(loaded) ? loaded : null;
  } catch {
    outcome = null;
  }
  outcomeSettled = true;
  if (state.mode === "short") showBrief();
  if (outcome) {
    const answer = element("answer");
    answer.textContent = answerMarkup(outcome);
    answer.hidden = state.mode === "short";
    element("worth").innerHTML = worthMarkup(outcome);
    money.planned = outcome.one_feeder.planned.fleet;
    // The forecast results arrive after the plan; the page reads without them until they do.
    const read = (file: string): Promise<unknown> => fetch(file).then((got) => got.json());
    void Promise.all([read("trust.json"), read("models.json"), read("backtest.json")]).then(([trust, bench, backtest]) => {
      models = forecasts(trust, bench, backtest);
      element("hood-model-says").textContent = forecastLine(models);
      if (state.mode === "short") showBrief();
      showImpact();
    }).catch(() => undefined);
  }
  showImpact();
  markDirty();
}
void loadOutcome();
void loadGrid().then((loaded) => {
  grid = loaded;
  markDirty();
});
void setMode("play").then(() => {
  // Draw once the typefaces are in, so the first frame's labels are measured correctly.
  void document.fonts.ready.then(() => (markDirty()));
  wake();
});
// A first visit opens on the short version; a link with ?view=full or a tab's name opens the twin there.
if (firstRoute) {
  void setMode(...firstRoute).then(() => {
    if (firstRoute[1]) partBox(firstRoute[1]).scrollIntoView({ block: "start" });
  });
} else if (!openFull) {
  void setMode("short");
}
window.addEventListener("hashchange", () => {
  const to = routed();
  if (!to) return;
  const [mode, part] = to;
  if (mode !== state.mode || (part && !partBox(part).open)) void setMode(mode, part).then(() => part && partBox(part).scrollIntoView({ block: "start" }));
});

// ---------------------------------------------------------------------------------------------------
// Keyboard: tabs and groups of choices work the way those patterns are expected to. One member of a group
// is in the tab order, the arrow keys move within it and choose, and focus stays on the choice after the
// view has redrawn itself around it.

const GROUPS = '[role="tablist"], [role="radiogroup"]';
const MEMBERS = '[role="tab"], [role="radio"]';

function members(group: Element): HTMLElement[] {
  return Array.from(group.querySelectorAll<HTMLElement>(MEMBERS)).filter((m) => m.closest(GROUPS) === group && !m.hidden);
}

function chosen(member: HTMLElement): boolean {
  return member.getAttribute("aria-selected") === "true" || member.getAttribute("aria-checked") === "true";
}

/** Put the chosen member of every group in the tab order and take the others out of it. */
function rove(): void {
  for (const group of Array.from(document.querySelectorAll(GROUPS))) {
    const all = members(group);
    const current = all.find(chosen) ?? all[0];
    for (const member of all) member.tabIndex = member === current ? 0 : -1;
  }
}

/** After a choice redraws its view, focus goes back to the chosen member of the same group. */
function refocus(groupIndex: number): void {
  requestAnimationFrame(() => {
    rove();
    const group = document.querySelectorAll(GROUPS)[groupIndex];
    if (group && !group.contains(document.activeElement)) members(group).find(chosen)?.focus();
  });
}

document.addEventListener("keydown", (event) => {
  const member = (event.target as HTMLElement).closest<HTMLElement>(MEMBERS);
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
  const end = { Home: 0, End: -1 }[event.key];
  if (!member || (step === undefined && end === undefined)) return;
  const group = member.closest(GROUPS);
  if (!group) return;
  const all = members(group);
  const next = end !== undefined ? all.at(end)! : all[(all.indexOf(member) + step! + all.length) % all.length];
  event.preventDefault();
  const index = Array.from(document.querySelectorAll(GROUPS)).indexOf(group);
  next.focus();
  next.click();
  refocus(index);
});

// In the capture phase: a view may replace its own markup when it handles the click, and the group has to be
// found while the element clicked is still in the page.
document.addEventListener("click", (event) => {
  const member = (event.target as HTMLElement).closest<HTMLElement>(MEMBERS);
  const group = member?.closest(GROUPS);
  if (group) refocus(Array.from(document.querySelectorAll(GROUPS)).indexOf(group));
}, true);

new MutationObserver(() => rove()).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-selected", "aria-checked"] });
rove();
