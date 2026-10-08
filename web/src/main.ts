// The page: a depot the visitor can run and change, or a recorded run they can move through.
//
// Both modes fill the same list of steps (see trace.ts) and one set of views draws it. In "play" the steps
// come from the browser simulator as the clock advances; in "replay" they come from a file recorded by
// the Python simulator.

import "./style.css";
import { DEFAULTS, DepotSim, type Params } from "./sim";
import { loadGrid, type Grid } from "./grid";
import { PLACE, unpack, vehicleName, type Plan, type Step, type TraceFile, type TraceMeta } from "./trace";
import { compareRuns, drawPlannedRoad, drawPlannedVisits, plansAt } from "./views/plan";
import { renderChain, renderFollowed } from "./views/board";
import { AC_LIMIT_KW, USABLE } from "./sim";
import { clock, percent, whole } from "./views/canvas";
import {
  drawGridStrain, drawOutlook, drawPulse, drawRides, drawRoad, hourAt, hourly, outlook, outlookScore, type Hour,
} from "./views/charts";
import { drawFloor, type Drawn, type Hit } from "./views/floor";
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
  slots: "called in to fill energy slots",
  heartbeat: "called in by the day-ahead plan",
  headroom: "called in to fill every charger",
  in_order: "fed in the order they plugged in",
  slot_power: "fed in the order they plugged in",
  emptiest_first: "emptiest vehicle fed first",
  need_first: "emptiest vehicle fed first",
};

function element<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

const floor = element<HTMLCanvasElement>("floor");
const chainOpen = element<HTMLDetailsElement>("chain-open");
const pulse = element<HTMLCanvasElement>("pulse");
const rides = element<HTMLCanvasElement>("rides");
const road = element<HTMLCanvasElement>("road");
const outlookCanvas = element<HTMLCanvasElement>("outlook");
const strainCanvas = element<HTMLCanvasElement>("strain");
const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

interface State {
  mode: "play" | "replay" | "model" | "money" | "story";
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

const params: Params = { ...DEFAULTS, staff: 12 };
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
const state: State = {
  mode: "play",
  meta: {} as TraceMeta,
  steps: [],
  otherSteps: null,
  head: 0,
  playing: !still,
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

/** Build the depot from the current settings and run it past its warm-up. */
function startAgain(): void {
  // A vehicle followed in a larger fleet may not exist in a smaller one.
  if (state.followed !== null && state.followed >= params.fleet) state.followed = null;
  sim = new DepotSim(params);
  otherSim = compare ? new DepotSim({ ...params, powerRule: otherRule() }) : null;
  state.steps = [];
  state.otherSteps = otherSim ? [] : null;
  for (let k = 0; k < WARM_UP; k++) advanceSim();
  state.meta = sim.meta();
  state.head = state.steps.length - 2;
  state.drawnStep = -1;
  state.holds = "play";
}

function advanceSim(): void {
  state.steps.push(sim.step());
  if (otherSim && state.otherSteps) state.otherSteps.push(otherSim.step());
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
  if (otherSim) Object.assign(otherSim.params, params, { powerRule: otherRule() });
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
  { key: "fleet", label: "Vehicles in the fleet", min: 200, max: 2000, step: 50, show: whole, rebuild: true },
  // The connection is bounded by the parcel: the weakest nearby feeder gives about 1 MW, the two strong ones together 5.5 MW (docs/SITE.md).
  { key: "siteKw", label: "Power from the grid", min: 1000, max: 5500, step: 250, show: (v) => `${(v / 1000).toFixed(2)} MW` },
  { key: "chargers", label: "Chargers", min: 10, max: 400, step: 2, show: whole, rebuild: true },
  { key: "staff", label: "People plugging in and cleaning", min: 4, max: 120, step: 1, show: whole },
  { key: "callBelow", label: "Call a vehicle in when its battery is under", min: 0.1, max: 0.6, step: 0.05, show: (v) => `${Math.round(v * 100)}%`, only: "threshold" },
  { key: "slotMin", label: "Length of a charging slot", min: 20, max: 90, step: 5, show: (v) => `${v} minutes`, only: "slots" },
  { key: "ridesPerVehicleDay", label: "Rides offered per vehicle per day", min: 15, max: 35, step: 1, show: whole },
];

function buildControls(): void {
  const form = element<HTMLFormElement>("controls");
  const choice = (id: string, label: string, options: [string, string][]) =>
    `<label>${label}<select id="${id}">${options.map(([value, name]) => `<option value="${value}">${name}</option>`).join("")}</select></label>`;
  form.innerHTML =
    SLIDERS.slice(0, 2).map(sliderMarkup).join("") +
    `<div class="presets"><button type="button" data-kw="2750">One feeder, 2.75 MW</button><button type="button" data-kw="5500">Two feeders, 5.5 MW</button></div>` +
    SLIDERS.slice(2, 3).map(sliderMarkup).join("") +
    `<div class="choice-block"><span>Power of each charger <b id="chargerKw-value"></b></span><div class="presets" role="radiogroup" aria-label="Power of each charger">${CHARGER_CLASSES.map(([kw, name]) => `<button type="button" role="radio" aria-checked="false" data-charger-kw="${kw}">${name}</button>`).join("")}</div><small id="chargerKw-note" class="slider-note"></small></div>` +
    SLIDERS.slice(3, 4).map(sliderMarkup).join("") +
    choice("powerRule", "When power is short, feed vehicles", [["in_order", "In the order they plugged in"], ["emptiest_first", "Emptiest vehicle first"]]) +
    choice("recall", "Calling vehicles in", [["threshold", "When the battery is low"], ["slots", "In slots, paced to the chargers"]]) +
    SLIDERS.slice(4).map(sliderMarkup).join("") +
    `<label class="check"><input type="checkbox" id="compare-rules" /> Run the other power rule alongside</label>`;
  form.addEventListener("input", onControl);
  form.addEventListener("click", (event) => {
    const chargerKw = (event.target as HTMLElement).dataset?.chargerKw;
    if (chargerKw) {
      params.chargerKw = Number(chargerKw);
      touched.add("chargerKw");
      applyLive();
      syncControls();
      return;
    }
    const kw = (event.target as HTMLElement).dataset?.kw;
    if (!kw) return;
    params.siteKw = Number(kw);
    applyLive();
    syncControls();
  });
  syncControls();
}

function sliderMarkup(slider: Slider): string {
  const note = slider.key === "chargers" ? `<small id="chargers-note" class="slider-note"></small>` : "";
  return `<label data-only="${slider.only ?? ""}"><span>${slider.label} <b id="${slider.key}-value"></b></span>` +
    `<input type="range" id="${slider.key}" min="${slider.min}" max="${slider.max}" step="${slider.step}" />${note}</label>`;
}

/** Make the controls show the current settings. */
/** Plugs the usable connection feeds at once at the chosen charger power. */
function feedable(): number {
  return Math.max(1, Math.floor((params.siteKw * USABLE * 0.93) / drawKw()));
}

/** What a vehicle actually takes from a charger of the chosen power: 11 kW on AC whatever the post is rated, and
 *  on a fast charger no more than the batteries accept (100 kW and 150 kW on the two models, 120 kW across the mix). */
function drawKw(): number {
  return params.chargerKw <= AC_LIMIT_KW ? Math.min(params.chargerKw, 11) : Math.min(params.chargerKw, 120);
}

/** Past this many plugs the grid cannot use them: two for every one it feeds at once, the way paired dispensers
 *  share one power cabinet. The slider is not stopped there; the page says so instead (E19: half as many again bought nothing). */
function chargerCeiling(): number {
  return (2 * feedable()) & ~1;
}

/** What a vehicle draws in a day, from the calibrated fleet: a fixed part for computers, climate and idle
 *  driving, and a part per ride, into the battery: about 88 kWh at 25 rides a day and 78 at 15, as this
 *  simulator measures them. At 25 rides that is 95 kWh from the grid, the figure the Python sizing rule uses. */
function energyPerVehicleDay(rides: number): number {
  return 61.6 + 1.07 * rides;
}

/** The fleet whose daily energy equals what the usable connection delivers all day. */
function sustainableFleet(): number {
  return Math.floor((params.siteKw * USABLE * 0.93 * 24) / energyPerVehicleDay(params.ridesPerVehicleDay));
}

/** Chargers the fleet's energy asks for: the sizing rule, a charger averaging five sixths of its rating, busy 60% of the day. */
function chargersNeeded(): number {
  return Math.ceil((params.fleet * energyPerVehicleDay(params.ridesPerVehicleDay)) / 0.93 / (drawKw() * (5 / 6) * 24 * 0.6));
}

interface Alert {
  level: "stop" | "warn";
  text: string;
}

/** What the chosen design cannot do, from the site's figures: fleet against grid, plugs against grid, plugs against fleet, people against fleet. */
function designAlerts(): Alert[] {
  const out: Alert[] = [];
  const fleetCap = sustainableFleet();
  const mw = (kw: number) => `${(kw / 1000).toFixed(2)} MW`;
  if (params.fleet > fleetCap) {
    const need = (params.fleet * energyPerVehicleDay(params.ridesPerVehicleDay)) / (USABLE * 0.93 * 24);
    out.push({
      level: "stop",
      text: `This site cannot sustain ${whole(params.fleet)} vehicles. A day of ${mw(params.siteKw)} at 95% holds the energy for about ${whole(fleetCap)} at ${params.ridesPerVehicleDay} rides a day, and rides are lost before that as the queue builds; ${whole(params.fleet)} need about ${mw(need)}${need > 5500 ? ", more than the two feeders at this parcel give. The rest is another site or a substation upgrade" : ", a second service connection"}. Expect rides to be lost once the batteries run down.`,
    });
  } else if (params.fleet > 0.9 * fleetCap) {
    out.push({ level: "warn", text: `Near the site's limit: a day of ${mw(params.siteKw)} holds the energy for about ${whole(fleetCap)} vehicles at ${params.ridesPerVehicleDay} rides a day, and rides are lost before that as the queue builds.` });
  }
  const fed = feedable();
  const ceiling = chargerCeiling();
  if (params.chargers > ceiling) {
    out.push({ level: "warn", text: `More plugs than the grid can use. ${mw(params.siteKw)} feeds ${whole(fed)} vehicles at once at the ${drawKw()} kW a vehicle takes at most from a ${params.chargerKw} kW charger; with power sharing two plugs per fed one, ${whole(ceiling)}, is the most that pays. The ${whole(params.chargers - ceiling)} beyond that wait for power.` });
  }
  const needed = chargersNeeded();
  if (params.chargers < 0.75 * needed) {
    out.push({ level: "warn", text: `Too few chargers for this fleet: ${whole(params.fleet)} vehicles want about ${whole(needed)} at ${params.chargerKw} kW. Vehicles will queue for a plug.` });
  } else if (params.chargers > 2 * needed && params.chargers <= ceiling) {
    out.push({ level: "warn", text: `More chargers than this fleet can use: about ${whole(needed)} would do at ${params.chargerKw} kW. The rest is capital standing still.` });
  }
  if (params.chargers * drawKw() < params.siteKw * USABLE * 0.93 * 0.9) {
    out.push({ level: "warn", text: `Power left on the table: the grid could feed ${whole(fed)} vehicles at once at ${drawKw()} kW each and only ${whole(params.chargers)} chargers are installed.` });
  }
  if (params.staff < params.fleet / 100) {
    out.push({ level: "warn", text: `Too few people: ${whole(params.staff)} for ${whole(params.fleet)} vehicles. Vehicles will sit full on chargers waiting to be unplugged.` });
  }
  return out;
}

/** What the running depot is doing about it: the last day's rides lost, and what bound them. */
function runAlerts(): Alert[] {
  const day = state.steps.slice(-DAY);
  if (day.length < DAY / 2) return [];
  const sum = (pick: (s: Step) => number) => day.reduce((a, s) => a + pick(s), 0);
  const offered = sum((s) => s.offered);
  const served = sum((s) => s.served);
  // A ride can be served a step or two after it was offered, so the day's two sums are compared, never a step's.
  const lost = Math.max(0, offered - served);
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
  return [{ level: lost / offered > 0.05 ? "stop" : "warn", text: `Last 24 hours: ${percent(lost / offered)} of rides lost (${whole(lost)}); ${why}.` }];
}

let shownAlerts = "";

function showAlerts(): void {
  if (state.mode !== "play") {
    element("alerts").innerHTML = shownAlerts = "";
    return;
  }
  const all = [...designAlerts(), ...runAlerts()];
  // The region is announced to screen readers when it changes, so it is written only when it does.
  const html = all.map((a) => `<p class="alert ${a.level}">${a.text}</p>`).join("");
  if (html !== shownAlerts) element("alerts").innerHTML = shownAlerts = html;
}

function syncControls(): void {
  for (const slider of SLIDERS) {
    element<HTMLInputElement>(slider.key).value = String(params[slider.key]);
    element(`${slider.key}-value`).textContent = slider.show(params[slider.key]);
    const row = element(slider.key).closest("label") as HTMLElement;
    row.hidden = slider.only !== undefined && slider.only !== params.recall;
  }
  const klass = CHARGER_CLASSES.find(([kw]) => kw === params.chargerKw) ?? CHARGER_CLASSES[1];
  element("chargerKw-value").textContent = `${params.chargerKw} kW`;
  element("chargerKw-note").textContent = klass[2];
  document.querySelectorAll<HTMLButtonElement>("[data-charger-kw]").forEach((button) => button.setAttribute("aria-checked", String(Number(button.dataset.chargerKw) === params.chargerKw)));
  element("chargers-note").textContent = `The grid feeds ${whole(feedable())} at once at ${drawKw()} kW each; two plugs per fed one, ${whole(chargerCeiling())}, is the most that pays.`;
  showAlerts();
  element<HTMLSelectElement>("powerRule").value = params.powerRule;
  element<HTMLSelectElement>("recall").value = params.recall;
}

function onControl(event: Event): void {
  const input = event.target as HTMLInputElement | HTMLSelectElement;
  const slider = SLIDERS.find((candidate) => candidate.key === input.id);
  let rebuild = slider?.rebuild ?? false;
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
    state.drawnStep = -1;
    element<HTMLInputElement>("scrub").max = String(state.steps.length - 2);
    const [recall, power] = file.meta.label.split(" + ");
    const listed = recorded.find((run) => run.file === replayOf.trace);
    element<HTMLSelectElement>("replay-pick").value = replayOf.trace;
    note.textContent =
      (listed ? `${listed.note} ` : "") +
      `${file.meta.depot}, ${file.meta.chargers} chargers of ${file.meta.charger_kw} kW, ` +
      `${whole(file.meta.site_limit_kw)} kW from the grid. Vehicles are ${RULE_NAMES[recall] ?? recall} and ${RULE_NAMES[power] ?? power}. Rides are replayed from real San Francisco days, from Monday 15 April 2024.` +
      (replayOf.model ? ` The plan is working from the forecast of ${replayOf.model}.` : "");
    state.holds = `replay:${replayOf.trace}`;
    showRunning("replay");
    element("mode-note").textContent = plans.length > 0
      ? `This run was recorded from the full model, with the day-ahead plan${state.steps.some((s) => s.promised !== null) ? " and its hourly promise" : ""}.`
      : "This run was recorded from the full model. Vehicles are called in by a fixed rule here: no plan ran.";
  } catch {
    if (mine !== turn) return;
    note.textContent = "The recorded run could not be loaded. Check the connection and choose this mode again.";
    element("mode-note").textContent = "No recorded run is loaded.";
    state.steps = [];
  }
}

// What each part of the picture is made of, in each mode. The two modes differ, and the page should never
// leave a visitor thinking the browser is running something it is not.
const SITE_ROW =
  "A hypothetical depot on a 14.5-acre industrial parcel on San Leandro Street, East Oakland. Its physical limits come from that place: the two strong 12 kV feeders nearby each offer about 2.75 MW of new load on PG&E's public capacity map, so one connection is 2.75 MW and two are 5.5 MW, and the power slider stops there. The site's load manager draws at most 95% of the connection. The other dials run free, and the page says what the site cannot do: a fleet it cannot sustain, plugs the grid cannot feed, chargers the fleet cannot use, too few people; and what the running depot lost and why. Details in docs/SITE.md.";

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
    ["Site", SITE_ROW],
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

/** The owner's one-page account of the decisions, rendered from docs/STORY.md at build time. */
async function showStory(): Promise<void> {
  const story = element("story");
  if (story.childElementCount > 0) return;
  try {
    story.innerHTML = `<article class="prose">${await (await fetch("story-body.html")).text()}</article>`;
  } catch {
    story.innerHTML = `<p class="quiet">The story could not be loaded.</p>`;
  }
}

let resumeOnReturn = false;

async function setMode(mode: State["mode"]): Promise<void> {
  const mine = ++turn;
  state.mode = mode;
  element("mode-play").setAttribute("aria-selected", String(mode === "play"));
  element("mode-replay").setAttribute("aria-selected", String(mode === "replay"));
  element("mode-model").setAttribute("aria-selected", String(mode === "model"));
  element("mode-money").setAttribute("aria-selected", String(mode === "money"));
  element("mode-story").setAttribute("aria-selected", String(mode === "story"));
  // The workbench and the account replace the depot: they are about the model and the money, and the
  // depot comes back with "play" or "replay".
  const aside = mode === "model" || mode === "money" || mode === "story";
  element("workbench").hidden = mode !== "model";
  element("money").hidden = mode !== "money";
  element("story").hidden = mode !== "story";
  if (aside) element("demand-box").hidden = true;
  element("mpc").hidden = mode !== "replay" || plans.length === 0;
  document.querySelector<HTMLElement>(".bench")!.hidden = aside;
  document.querySelector<HTMLElement>(".colophon")!.hidden = aside;
  if (aside) {
    // The depot waits while another page is open, and carries on when the visitor comes back to it.
    if (state.playing) resumeOnReturn = true;
    setPlaying(false);
    if (mode === "story") await showStory();
    else await (mode === "model" ? workbench.show() : money.show());
    return;
  }
  if (resumeOnReturn) setPlaying(true);
  resumeOnReturn = false;
  element("controls").hidden = mode !== "play";
  element("demand-box").hidden = mode !== "play";
  if (mode === "play") void showDemand();
  element("replay-box").hidden = mode !== "replay";
  element("scrub-box").hidden = mode !== "replay";
  element("mode-note").textContent =
    mode === "play"
      ? "This depot runs in your browser on an average San Francisco week. It models the fleet, the chargers, the people and both power rules, and a test holds it to the full model: within half a point of rides served at 500 vehicles and a point and a half at 1,000. It leaves out the day-ahead plan and the ride forecasts; the recorded run has them."
      : "Loading the recorded run.";
  showRunning(mode);
  showAlerts();
  // Coming back from the forecast, the money or the story, the depot is as it was left: only a change of
  // what is running starts it again.
  if (mode === "play") {
    if (state.holds !== "play") startAgain();
  } else if (state.holds !== `replay:${replayOf.trace}`) {
    state.steps = [];
    state.holds = "";
    await loadReplay(mine);
  } else {
    showRunning("replay");
    element("mode-note").textContent = plans.length > 0
      ? `This run was recorded from the full model, with the day-ahead plan${state.steps.some((s) => s.promised !== null) ? " and its hourly promise" : ""}.`
      : "This run was recorded from the full model. Vehicles are called in by a fixed rule here: no plan ran.";
  }
}

// ---------------------------------------------------------------------------------------------------
// Drawing.

function readout(label: string, value: string, note: string, wide = false): string {
  return `<div${wide ? ' class="wide"' : ""}><dt>${label}</dt><dd>${value}<small>${note}</small></dd></div>`;
}

function servedShare(steps: Step[]): number {
  return Math.min(1, steps.reduce((sum, s) => sum + s.served, 0) / Math.max(1, steps.reduce((sum, s) => sum + s.offered, 0)));
}

function drawNumbers(index: number): void {
  const step = state.steps[index];
  const from = Math.max(0, index - DAY + 1);
  const day = state.steps.slice(from, index + 1);
  const lost = Math.max(0, day.reduce((sum, s) => sum + s.offered - s.served, 0));
  let html =
    readout("Rides served, last 24 hours", percent(servedShare(day)), `${whole(lost)} lost`) +
    readout("On the road", whole(step.on_road), `of ${whole(state.meta.fleet)}`) +
    readout("Waiting for a charger", whole(step.queued), `${step.charging} charging`) +
    readout("Visits a vehicle-day", visitsPerVehicleDay(day).toFixed(1), "the filings' fleet charges about three times a day") +
    readout("Power from the grid", `${whole(step.grid_kw)} kW`, `of ${whole(state.meta.usable_kw ?? state.meta.site_limit_kw)} kW usable`);
  if (state.otherSteps) {
    const share = servedShare(state.otherSteps.slice(from, index + 1));
    html += readout(`Same depot, ${RULE_NAMES[otherRule()]}`, percent(share), "of rides served over the same 24 hours", true);
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
  const live = state.mode === "play";
  const shown = live ? state.steps.slice(0, index + 1) : state.steps;
  hours = hourly(shown);
  const other = state.otherSteps ? hourly(state.otherSteps.slice(0, index + 1)) : null;
  const now = live ? null : state.steps[index].minute;
  drawRides(rides, hours, other, RULE_NAMES[otherRule()], now);
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
  if (plans.length === 0 || state.mode !== "replay") return;
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
  const mix = still ? 0 : Math.min(1, Math.max(0, state.head - index));
  const minutes = (index + mix) * STEP_MIN;
  drawn = drawFloor(floor, {
    meta: state.meta,
    step: state.steps[index],
    next: state.steps[index + 1],
    mix,
    flow: still ? 0.5 : minutes / 15,
    followed: state.followed,
  });
  if (index === state.drawnStep) return;
  state.drawnStep = index;
  drawNumbers(index);
  drawCharts(index);
  drawVehicles(index);
  drawPlan(index);
  showAlerts();
  if (state.mode === "replay") element<HTMLInputElement>("scrub").value = String(index);
}

function setPlaying(playing: boolean): void {
  state.playing = playing;
  element("play").textContent = playing ? "Pause" : "Play";
}

let lastFrame = performance.now();

function frame(time: number): void {
  // A hidden tab can leave a long gap between frames; never jump more than a tenth of a second.
  const elapsed = Math.min(0.1, (time - lastFrame) / 1000);
  lastFrame = time;
  if (state.playing && state.steps.length >= 2) {
    state.head += (elapsed * state.speed * MINUTES_PER_SECOND) / STEP_MIN;
    if (state.mode === "play") {
      while (state.head > state.steps.length - 2) advanceSim();
    } else if (state.head >= state.steps.length - 2) {
      state.head = state.steps.length - 2;
      setPlaying(false);
    }
  }
  draw();
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
}
interface Demand {
  penetration_trips_per_resident_month: number; growth_per_month: number; capacity_one_feeder: number; rides_per_vehicle_day: number;
  areas: Record<string, DemandArea>; run: string;
}
let demand: Demand | null = null;
let demandArea = "east_bay_20km";
const AREA_NAMES: Record<string, string> = { oakland_8km: "8 km: East Oakland, San Leandro, Alameda", east_bay_15km: "15 km: Oakland, Emeryville, Hayward", east_bay_20km: "20 km: Alameda County's East Bay" };

/** Where the rides come from: the service area around the parcel, what it produces today, and when it outgrows a feeder. */
async function showDemand(): Promise<void> {
  const box = element("demand-box");
  if (!demand) {
    try {
      demand = (await (await fetch("demand.json")).json()) as Demand;
    } catch {
      box.hidden = true;
      return;
    }
  }
  // The figures may arrive after the visitor has gone to another mode; the box belongs to the live depot only.
  if (state.mode !== "play") return;
  const area = demand.areas[demandArea];
  const chips = Object.keys(demand.areas).map((k) => `<button type="button" role="radio" aria-checked="${k === demandArea}" data-area="${k}">${AREA_NAMES[k] ?? k}</button>`).join("");
  const soon = area.months_until_second_feeder;
  const slow = area.months_until_second_feeder_at_half_the_growth;
  box.innerHTML =
    `<h3 class="aside-title">Where the rides come from</h3>` +
    `<div class="presets" role="radiogroup" aria-label="Service area">${chips}</div>` +
    `<dl class="readouts demand-figures">` +
    `<div><dt>Residents</dt><dd>${whole(area.population)}<small>${whole(area.tracts)} census tracts</small></dd></div>` +
    `<div><dt>Rides a day today</dt><dd>${whole(area.rides_per_day)}<small>at ${demand.penetration_trips_per_resident_month.toFixed(2)} trips a resident a month, the filings' penetration</small></dd></div>` +
    `<div><dt>Vehicles that is</dt><dd>${whole(area.vehicles_at_25_rides)}<small>at ${demand.rides_per_vehicle_day} rides a vehicle-day; one feeder carries ${whole(demand.capacity_one_feeder)}${area.vehicles_at_25_rides < SLIDERS[0].min ? `; the smallest fleet this page runs is ${whole(SLIDERS[0].min)}` : ""}</small></dd></div>` +
    `<div><dt>Growth scenario</dt><dd>${soon === null ? "now" : `${whole(soon)} months`}<small>${soon === null ? "the area already outgrows one feeder" : `until one feeder is outgrown, if the measured ${(100 * demand.growth_per_month).toFixed(1)}% a month continued; ${whole(slow ?? 0)} months at half of it. A scenario, not a forecast`}</small></dd></div>` +
    `</dl>` +
    `<button type="button" id="size-to-area" class="solid">Size the fleet to this area</button>` +
    `<p class="quiet">From the service's public filings: the tracts it serves and its trips, over census populations. Circles of straight-line distance over Alameda County tracts; San Francisco across the bay is left out. No density adjustment: a sparser area than the served footprint likely produces less than this.</p>`;
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
  state.drawnStep = -1;
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
  element("followed").addEventListener("click", (event) => {
    if ((event.target as HTMLElement).id === "unfollow") follow(state.followed);
  });
}

interface Facts {
  forecast: { hours_ahead: number; error: number; same_hour_last_week: number; upper_bound_held: number; no_history_error_against_last_week: number[] }[];
}

/** Under the forecast chart: how the trained forecast scored in its registered tests. Figures come from the result files. */
async function showFacts(): Promise<void> {
  try {
    const facts = (await (await fetch("facts.json")).json()) as Facts;
    const rows = facts.forecast.map((row) =>
      `<tr><th scope="row">${row.hours_ahead} h ahead</th><td>${percent(row.error)}</td><td>${percent(row.same_hour_last_week)}</td>` +
      `<td>${percent(row.upper_bound_held)}</td><td>${Math.round(row.no_history_error_against_last_week[0] * 100)} to ` +
      `${Math.round(row.no_history_error_against_last_week[1] * 100)}%</td></tr>`);
    element("facts").innerHTML =
      `<table><caption>The trained forecast, as tested on held-out days</caption><thead><tr><td></td><th scope="col">Error</th>` +
      `<th scope="col">Same hour last week</th><th scope="col">Upper bound held</th>` +
      `<th scope="col">With no local history, error against last week's, across three cities</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
  } catch {
    element("facts").textContent = "";
  }
}

const workbench = new WorkbenchView(element("workbench"), (trace, model) => {
  replayOf = { trace, model, compare: null };
  void setMode("replay").then(() => {
    // A visitor who asked for less motion starts the recording themselves.
    setPlaying(!still);
    document.querySelector(".stage")?.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
  });
});

const money = new MoneyView(element("money"), () => grid);

function wire(): void {
  element("play").addEventListener("click", () => {
    if (!state.playing && state.mode === "replay" && state.head >= state.steps.length - 2) state.head = 0;
    setPlaying(!state.playing);
  });
  element("reset").addEventListener("click", () => {
    if (state.mode === "play") startAgain();
    else state.head = 0;
    state.drawnStep = -1;
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
  });
  element("mode-play").addEventListener("click", () => void setMode("play"));
  element("mode-replay").addEventListener("click", () => {
    if (replayOf.model) replayOf = { trace: "traces/sample.json", model: "", compare: "traces/threshold.json" };
    void setMode("replay");
  });
  element<HTMLSelectElement>("replay-pick").addEventListener("change", (event) => {
    const chosen = recorded.find((run) => run.file === (event.target as HTMLSelectElement).value);
    if (!chosen) return;
    replayOf = { trace: chosen.file, model: "", compare: chosen.compare };
    void setMode("replay");
  });
  element("mode-model").addEventListener("click", () => void setMode("model"));
  element("mode-money").addEventListener("click", () => void setMode("money"));
  element("mode-story").addEventListener("click", () => void setMode("story"));
  window.addEventListener("resize", () => (state.drawnStep = -1));
  probe(rides, "rides-probe", (hour) =>
    `${whole(hour.offered)} rides offered, ${whole(hour.served)} served, ${whole(Math.max(0, hour.offered - hour.served))} lost`);
  probe(road, "road-probe", (hour) =>
    `${whole(hour.onRoad)} vehicles on the road` + (hour.promised === null ? "" : `, ${whole(hour.promised)} promised`));
}

buildControls();
wire();
setPlaying(state.playing);
void showFacts();
void loadRecordedList();
void loadGrid().then((loaded) => {
  grid = loaded;
  state.drawnStep = -1;
});
void setMode("play").then(() => {
  // Draw once the typefaces are in, so the first frame's labels are measured correctly.
  void document.fonts.ready.then(() => (state.drawnStep = -1));
  requestAnimationFrame(frame);
});
