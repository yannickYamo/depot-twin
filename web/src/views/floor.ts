// The depot floor: a plan view of where every vehicle is. It is drawn as a site at night: vehicles on the
// road are blue, vehicles in the depot are pale, and energy is mint wherever it flows.
//
// Every vehicle off the road is a named one. Each mark drawn for it is also returned as a place the
// pointer can hit, so the page can say which vehicle is under the pointer and follow one through its visit.

import { PLACE, vehicleName, type Step, type TraceMeta } from "../trace";
import { DISPLAY, FIGURE, LABEL, STAGE as T, narrow, surface, text, whole } from "./canvas";

export interface FloorScene {
  meta: TraceMeta;
  step: Step;
  next: Step;
  /** How far between `step` and `next` the picture is, from 0 to 1. */
  mix: number;
  /** Simulated minutes, as a fraction, used to move vehicles along the lanes. Fixed when motion is reduced. */
  flow: number;
  /** The vehicle being followed, or null. */
  followed: number | null;
}

/** A vehicle's mark on the floor, in layout units. */
export interface Hit {
  vehicle: number;
  x: number;
  y: number;
  r: number;
  place: number;
  soc: number;
  kw?: number;
  stall?: number;
}

/** What one drawing of the floor leaves behind: the marks, and the size of the layout they are measured in. */
export interface Drawn {
  hits: Hit[];
  width: number;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Named {
  vehicle: number;
  soc: number;
  place: number;
}

/** Split a step's off-road vehicles by where they are. A trace without names gives nameless stand-ins. */
function byPlace(step: Step): Map<number, Named[]> {
  const places = new Map<number, Named[]>();
  const add = (place: number, vehicle: number, soc: number) => {
    if (!places.has(place)) places.set(place, []);
    places.get(place)!.push({ vehicle, soc, place });
  };
  if (step.chain.length === 0) {
    const counts: [number, number][] = [
      [PLACE.inbound, step.inbound], [PLACE.queued, step.queued], [PLACE.afterCharging, step.handling],
      [PLACE.cleaning, step.cleaning], [PLACE.outbound, step.outbound],
    ];
    for (const [place, count] of counts) for (let k = 0; k < count; k++) add(place, -1, 0);
    return places;
  }
  for (let k = 0; k < step.chain.length; k += 3) add(step.chain[k + 1], step.chain[k], step.chain[k + 2]);
  // A recorded run does not tell cleaning apart from the rest of "after charging"; the bays take the first of them.
  if (!places.has(PLACE.cleaning) && step.cleaning > 0) {
    const after = places.get(PLACE.afterCharging) ?? [];
    places.set(PLACE.cleaning, after.splice(0, step.cleaning).map((v) => ({ ...v, place: PLACE.cleaning })));
  }
  return places;
}

/** Fill a box with one dot per vehicle, shrinking the dots as the count grows: the road, where vehicles are not told apart. */
function dots(ctx: CanvasRenderingContext2D, box: Box, list: Named[], color: string, hits: Hit[], largest = 10): void {
  if (list.length === 0) return;
  const cell = Math.max(2.5, Math.min(largest, Math.sqrt((box.w * box.h) / list.length) * 0.96));
  const columns = Math.max(1, Math.floor(box.w / cell));
  const rows = Math.max(1, Math.floor(box.h / cell));
  ctx.fillStyle = color;
  ctx.beginPath();
  for (let k = 0; k < Math.min(list.length, columns * rows); k++) {
    const x = box.x + (k % columns) * cell + cell / 2;
    const y = box.y + Math.floor(k / columns) * cell + cell / 2;
    ctx.moveTo(x + cell * 0.34, y);
    ctx.arc(x, y, cell * 0.34, 0, Math.PI * 2);
    if (list[k].vehicle >= 0) hits.push({ ...list[k], x, y, r: cell * 0.5 });
  }
  ctx.fill();
}

/** A lane between the road and the depot, with its vehicles moving along it. */
function lane(ctx: CanvasRenderingContext2D, from: number, to: number, y: number, list: Named[], flow: number, hits: Hit[]): void {
  ctx.strokeStyle = T.rule;
  ctx.lineWidth = 1;
  for (const offset of [-9, 9]) {
    ctx.beginPath();
    ctx.moveTo(from, y + offset);
    ctx.lineTo(to, y + offset);
    ctx.stroke();
  }
  const direction = Math.sign(to - from);
  ctx.fillStyle = T.label;
  ctx.beginPath();
  ctx.moveTo(to, y);
  ctx.lineTo(to - direction * 8, y - 5);
  ctx.lineTo(to - direction * 8, y + 5);
  ctx.fill();
  const length = Math.abs(to - from) - 14;
  const perRow = Math.max(1, Math.floor(length / 9));
  const shown = Math.min(list.length, perRow * 2);
  const rows = Math.min(2, Math.ceil(shown / perRow));
  const inRow = Math.ceil(shown / Math.max(1, rows));
  ctx.fillStyle = T.vehicle;
  for (let k = 0; k < shown; k++) {
    const along = (((k % inRow) + flow) / inRow) % 1;
    const x = from + direction * along * length;
    const at = y + (rows === 1 ? 0 : Math.floor(k / inRow) * 8 - 4);
    ctx.beginPath();
    ctx.arc(x, at, 3, 0, Math.PI * 2);
    ctx.fill();
    if (list[k].vehicle >= 0) hits.push({ ...list[k], x, y: at, r: 5 });
  }
}

/** Every charger as a stall: empty, plugged in and waiting for power, or filling. */
function stalls(ctx: CanvasRenderingContext2D, box: Box, scene: FloorScene, hits: Hit[]): void {
  const total = scene.meta.chargers;
  const columns = Math.max(1, Math.ceil(Math.sqrt((total * 1.5 * box.w) / box.h)));
  const rows = Math.ceil(total / columns);
  const cellW = Math.min(30, box.w / columns);
  const cellH = Math.min(44, box.h / rows);
  const later = new Map(scene.next.stalls.map((entry) => [`${entry[0]}:${entry[1]}`, entry[2]]));
  const used = new Map(scene.step.stalls.map((entry) => [entry[0], entry]));
  for (let k = 0; k < total; k++) {
    const x = box.x + (k % columns) * cellW + 2;
    const y = box.y + Math.floor(k / columns) * cellH + 2;
    const w = cellW - 4;
    const h = cellH - 4;
    const entry = used.get(k);
    if (entry) {
      const [, vehicle, charge, kw] = entry;
      const ahead = later.get(`${k}:${vehicle}`) ?? charge;
      const level = (charge + (ahead - charge) * scene.mix) / 100;
      ctx.save();
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, 3);
      ctx.clip();
      ctx.globalAlpha = kw >= 1 ? 1 : 0.28;
      ctx.fillStyle = T.energy;
      ctx.fillRect(x, y + h * (1 - level), w, h * level);
      ctx.restore();
      hits.push({ vehicle, x: x + w / 2, y: y + h / 2, r: Math.max(w, h) / 2, place: PLACE.charging, soc: charge, kw, stall: k });
    }
    ctx.strokeStyle = entry ? T.label : T.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 3);
    ctx.stroke();
  }
}

/** A station's name with its count beside it. */
function titled(ctx: CanvasRenderingContext2D, label: string, figure: string, x: number, y: number): void {
  text(ctx, label, x, y, LABEL, T.label);
  const after = x + ctx.measureText(label).width + 8;
  text(ctx, figure, after, y, FIGURE, T.ink);
}

function gauge(ctx: CanvasRenderingContext2D, box: Box, scene: FloorScene): void {
  const limit = scene.meta.usable_kw ?? scene.meta.site_limit_kw;
  const draw = scene.step.grid_kw + (scene.next.grid_kw - scene.step.grid_kw) * scene.mix;
  ctx.fillStyle = T.rule;
  ctx.beginPath();
  ctx.roundRect(box.x, box.y, box.w, box.h, box.h / 2);
  ctx.fill();
  ctx.fillStyle = T.energy;
  ctx.beginPath();
  ctx.roundRect(box.x, box.y, Math.max(box.h, box.w * Math.min(1, draw / limit)), box.h, box.h / 2);
  ctx.fill();
  text(ctx, `From the grid ${whole(draw)} of ${whole(limit)} kW usable`, box.x + box.w, box.y - 6, LABEL, T.label, "right");
}

function legend(ctx: CanvasRenderingContext2D, x: number, y: number, small: boolean): void {
  const entries: [string, number][] = [["taking power", 1], [small ? "waiting for power" : "plugged in, waiting for power", 0.3]];
  for (const [label, alpha] of entries) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = T.energy;
    ctx.beginPath();
    ctx.roundRect(x, y - 9, 10, 10, 3);
    ctx.fill();
    ctx.globalAlpha = 1;
    text(ctx, label, x + 15, y, LABEL, T.label);
    x += 22 + ctx.measureText(label).width + 14;
  }
}

/** Ring the followed vehicle and put its name beside it. */
function mark(ctx: CanvasRenderingContext2D, hit: Hit, width: number): void {
  ctx.strokeStyle = T.ink;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(hit.x, hit.y, hit.r + 4, 0, Math.PI * 2);
  ctx.stroke();
  const label = hit.place === 0 ? vehicleName(hit.vehicle) : `${vehicleName(hit.vehicle)}  ${hit.soc}%`;
  ctx.font = FIGURE;
  const w = ctx.measureText(label).width + 16;
  const x = Math.min(width - w - 6, Math.max(6, hit.x - w / 2));
  const y = hit.y - hit.r - 32 < 4 ? hit.y + hit.r + 10 : hit.y - hit.r - 32;
  ctx.fillStyle = T.ink;
  ctx.beginPath();
  ctx.roundRect(x, y, w, 22, 11);
  ctx.fill();
  text(ctx, label, x + 8, y + 16, FIGURE, "#050f1e");
}

export function drawFloor(canvas: HTMLCanvasElement, scene: FloorScene): Drawn {
  const small = narrow(canvas);
  const { ctx, w, h } = small ? surface(canvas, 0.8, 470) : surface(canvas, 0.54, 620);
  const { step, next, mix, meta } = scene;
  const hits: Hit[] = [];
  const places = byPlace(step);
  const list = (place: number) => places.get(place) ?? [];
  const onRoad = Math.round(step.on_road + (next.on_road - step.on_road) * mix);
  const pad = 16;
  const road: Box = { x: pad, y: pad, w: w * 0.26, h: h - 2 * pad };
  const yard: Box = { x: w * 0.41, y: pad, w: w - pad - w * 0.41, h: h - 2 * pad };

  // The road: one dot per vehicle out serving rides. They are not told apart here; a followed vehicle
  // that is on the road takes a dot of its own so that it can be seen leaving and coming back.
  text(ctx, "On the road", road.x, road.y + 14, LABEL, T.label);
  text(ctx, whole(onRoad), road.x, road.y + 54, DISPLAY, T.ink);
  const nameless = Array.from({ length: onRoad }, () => ({ vehicle: -1, soc: 0, place: 0 }));
  const offRoad = scene.followed !== null && isNamed(step, scene.followed);
  if (scene.followed !== null && !offRoad && onRoad > 0) nameless[scene.followed % onRoad] = { vehicle: scene.followed, soc: 0, place: 0 };
  dots(ctx, { x: road.x, y: road.y + 70, w: road.w, h: road.h - 70 }, nameless, T.road, hits);

  // The two lanes between the road and the depot: in along the top, out along the bottom, right to left.
  const laneIn = yard.y + 44;
  const laneOut = yard.y + yard.h - 40;
  lane(ctx, road.x + road.w + 10, yard.x - 2, laneIn, list(PLACE.inbound), scene.flow, hits);
  lane(ctx, yard.x - 2, road.x + road.w + 10, laneOut, list(PLACE.outbound), scene.flow, hits);
  text(ctx, `${small ? "In" : "Driving in"} ${list(PLACE.inbound).length}`, road.x + road.w + 10, laneIn - 18, LABEL, T.label);
  text(ctx, `${small ? "Out" : "Driving out"} ${list(PLACE.outbound).length}`, road.x + road.w + 10, laneOut + 30, LABEL, T.label);

  // The depot yard, top to bottom in the order a vehicle goes through it.
  ctx.strokeStyle = T.rule;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(yard.x, yard.y, yard.w, yard.h, 16);
  ctx.stroke();
  const inner = { x: yard.x + 14, w: yard.w - 28 };
  const queueTop = yard.y + 12;
  const queueH = yard.h * 0.2;
  titled(ctx, "Waiting for a charger", whole(list(PLACE.queued).length), inner.x, queueTop + 12);
  dots(ctx, { x: inner.x, y: queueTop + 22, w: inner.w, h: queueH - 22 }, list(PLACE.queued), T.vehicle, hits, 9);

  const bankTop = queueTop + queueH + 14;
  const bankH = yard.h * 0.42;
  titled(ctx, "Chargers", `${step.charging} of ${meta.chargers} charging`, inner.x, bankTop + 12);
  const gaugeW = Math.min(220, inner.w * 0.4);
  // At phone width the figure beside the floor carries the grid draw; there is no room for the gauge.
  if (!small) gauge(ctx, { x: inner.x + inner.w - gaugeW, y: bankTop + 4, w: gaugeW, h: 9 }, scene);
  stalls(ctx, { x: inner.x, y: bankTop + 22, w: inner.w, h: bankH - 44 }, scene, hits);
  legend(ctx, inner.x, bankTop + bankH - 4, small);

  // The last stretch: vehicles waiting for a member of staff to plug them in or unplug them, and the bays.
  const lastTop = bankTop + bankH + 14;
  const lastH = yard.y + yard.h - lastTop - 10;
  const half = inner.w / 2 - 10;
  const withStaff = [...list(PLACE.pluggingIn), ...list(PLACE.afterCharging)];
  titled(ctx, small ? "For staff" : "Waiting for staff", whole(withStaff.length), inner.x, lastTop + 12);
  dots(ctx, { x: inner.x, y: lastTop + 22, w: half, h: lastH - 22 }, withStaff, T.vehicle, hits, 9);
  const bays = inner.x + half + 20;
  const cleaning = list(PLACE.cleaning);
  titled(ctx, "Cleaning", `${cleaning.length} of ${meta.cleaning_bays}${small ? "" : " bays"}`, bays, lastTop + 12);
  const bay = Math.min(22, half / meta.cleaning_bays);
  const bayH = Math.min(30, lastH - 26);
  for (let k = 0; k < meta.cleaning_bays; k++) {
    ctx.strokeStyle = k < cleaning.length ? T.label : T.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(bays + k * bay + 1, lastTop + 24, bay - 3, bayH, 3);
    ctx.stroke();
    if (k >= cleaning.length) continue;
    const x = bays + k * bay + bay / 2 - 0.5;
    const y = lastTop + 24 + bayH / 2;
    ctx.fillStyle = T.vehicle;
    ctx.beginPath();
    ctx.arc(x, y, Math.min(5, bay * 0.28), 0, Math.PI * 2);
    ctx.fill();
    if (cleaning[k].vehicle >= 0) hits.push({ ...cleaning[k], x, y, r: bay / 2 });
  }

  const followed = hits.find((hit) => hit.vehicle === scene.followed);
  if (followed) mark(ctx, followed, w);
  return { hits, width: w };
}

/** Whether a vehicle is among those a step names as off the road. */
function isNamed(step: Step, vehicle: number): boolean {
  for (let k = 0; k < step.chain.length; k += 3) if (step.chain[k] === vehicle) return true;
  return false;
}
