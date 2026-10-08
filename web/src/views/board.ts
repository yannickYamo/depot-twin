// The chain a vehicle goes through, station by station, with the vehicles at each one named.
// And one vehicle followed: where it is now and what its latest visit looked like.

import { PLACE, vehicleName, type Step } from "../trace";
import { clock } from "./canvas";
import { caption, vehicleArt, type Shown } from "./vehicle";

const STATIONS: { name: string; places: number[] }[] = [
  { name: "Driving in", places: [PLACE.inbound] },
  { name: "Waiting for a charger", places: [PLACE.queued] },
  { name: "Waiting for staff to plug in", places: [PLACE.pluggingIn] },
  { name: "Charging", places: [PLACE.charging] },
  { name: "Unplugging and cleaning", places: [PLACE.afterCharging, PLACE.cleaning] },
  { name: "Driving out", places: [PLACE.outbound] },
];
const SHOWN = 6;

const EVENT: Record<number, string> = {
  0: "back on the road",
  [PLACE.inbound]: "called in",
  [PLACE.queued]: "reached the depot",
  [PLACE.pluggingIn]: "given a charger",
  [PLACE.charging]: "started charging",
  [PLACE.afterCharging]: "finished charging",
  [PLACE.cleaning]: "into a cleaning bay",
  [PLACE.outbound]: "left the depot",
};

/** Where a vehicle is at a step, and its charge there. Place 0 is the road, where charge is not recorded. */
export function whereabouts(step: Step, vehicle: number): { place: number; soc: number | null } {
  for (let k = 0; k < step.chain.length; k += 3) {
    if (step.chain[k] === vehicle) return { place: step.chain[k + 1], soc: step.chain[k + 2] };
  }
  return { place: 0, soc: null };
}

export interface Leg {
  minute: number;
  place: number;
  soc: number | null;
}

/** The changes of place a vehicle went through over the steps given, oldest first. */
export function journey(steps: Step[], vehicle: number): Leg[] {
  const legs: Leg[] = [];
  let last = -1;
  for (const step of steps) {
    const now = whereabouts(step, vehicle);
    if (now.place !== last) legs.push({ minute: step.minute, ...now });
    last = now.place;
  }
  // The first entry is only where the vehicle was when the record begins, not something that happened then.
  return legs.slice(1);
}

function chip(vehicle: number, soc: number, followed: number | null): string {
  const pressed = vehicle === followed ? ' aria-pressed="true"' : "";
  return `<button type="button" class="chip" data-vehicle="${vehicle}"${pressed}>${vehicleName(vehicle)}<span>${soc}%</span></button>`;
}

/** Draw the chain: for each station, how many vehicles are there and which ones. */
export function renderChain(root: HTMLElement, step: Step, followed: number | null): void {
  if (step.chain.length === 0) {
    root.innerHTML = `<p class="quiet">This recording does not name its vehicles.</p>`;
    return;
  }
  const html = STATIONS.map((station) => {
    const here: [number, number][] = [];
    for (let k = 0; k < step.chain.length; k += 3) {
      if (station.places.includes(step.chain[k + 1])) here.push([step.chain[k], step.chain[k + 2]]);
    }
    // The followed vehicle is always among those shown at its station.
    here.sort((a, b) => Number(b[0] === followed) - Number(a[0] === followed));
    const chips = here.slice(0, SHOWN).map(([vehicle, soc]) => chip(vehicle, soc, followed)).join("");
    const more = here.length > SHOWN ? `<span class="more">and ${here.length - SHOWN} more</span>` : "";
    return `<li><h3>${station.name}<b>${here.length}</b></h3><div class="chips">${chips}${more}</div></li>`;
  });
  root.innerHTML = `<ol>${html.join("")}</ol>`;
}

/** Describe the followed vehicle: the drawing of what it is doing, one line in the depot's words, and its latest visit. */
export function renderFollowed(root: HTMLElement, steps: Step[], vehicle: number | null, stall: number | null, kw: number | null): void {
  if (vehicle === null) {
    root.innerHTML = `<p class="quiet">Pick a vehicle on the floor or in the list to follow it through the depot.</p>`;
    return;
  }
  const last = steps[steps.length - 1];
  const now = whereabouts(last, vehicle);
  let ahead = 0;
  if (now.place === PLACE.queued) {
    for (let k = 0; k < last.chain.length; k += 3) {
      if (last.chain[k] === vehicle) break;
      if (last.chain[k + 1] === PLACE.queued) ahead += 1;
    }
  }
  const shown: Shown = { place: now.place, soc: now.soc === null ? null : now.soc / 100, kw, stall, ahead };
  const legs = journey(steps, vehicle).slice(-7);
  const rows = legs.map((leg) => `<li><time>${clock(leg.minute)}</time>${EVENT[leg.place]}${leg.soc === null ? "" : ` at ${leg.soc}%`}</li>`);
  const log = rows.length > 0 ? `<ol class="legs">${rows.join("")}</ol>` : `<p class="quiet">It has stayed on the road for as long as this record runs.</p>`;
  root.innerHTML =
    `<h3>${vehicleName(vehicle)}<button type="button" id="unfollow">Stop following</button></h3>` +
    vehicleArt(shown) +
    `<p class="caption">${caption(shown)}</p>${log}`;
}
