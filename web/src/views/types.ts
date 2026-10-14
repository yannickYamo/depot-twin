// The fleet by vehicle type: how often each type comes in, at what hours, and how long it charges. The
// running depot's figures are counted live by the browser simulator; the tests' figures beside them are the
// Python model's, at the planned fleet and the assumed mix (E30, in outcome.json).

import type { TypeFigures } from "../sim";
import { percent, whole } from "./canvas";

/** One vehicle type as the tests measured it: the median over forty runs. */
export interface RecordedType {
  name: string;
  visits_per_vehicle_day: number;
  arrival_chance_by_hour: number[];
  minutes_on_charger: number | null;
  kwh_per_visit: number;
  arrived_at_floor_share: number;
}

export interface RecordedTypes {
  fleet: number;
  share_ojai: number;
  by_type: RecordedType[];
}

/** Twenty-four bars, one an hour, scaled to the busiest hour of either type so the two can be compared. */
function hours(chances: number[], top: number, label: string): string {
  const width = 4;
  const gap = 1;
  const height = 28;
  const bars = chances
    .map((chance, hour) => {
      const tall = top > 0 ? Math.max(1, (chance / top) * height) : 1;
      return `<rect x="${hour * (width + gap)}" y="${height - tall}" width="${width}" height="${tall}"><title>${String(hour).padStart(2, "0")}:00, ${percent(chance)}</title></rect>`;
    })
    .join("");
  return `<svg class="type-hours" preserveAspectRatio="none" viewBox="0 0 ${24 * (width + gap) - gap} ${height}" role="img" aria-label="${label}">${bars}</svg>`;
}

function minutes(value: number | null, spread?: [number, number] | null): string {
  if (value === null) return "none yet";
  return spread ? `${whole(value)} min <small>(${whole(spread[0])} to ${whole(spread[1])})</small>` : `${whole(value)} min`;
}

/** The running depot's figures by type, with the tests' figures for the same type when the mix matches. */
export function typesMarkup(live: TypeFigures[], recorded: RecordedTypes | null, share: number): string {
  const shown = live.filter((type) => type.vehicles > 0);
  if (shown.every((type) => type.visitsPerVehicleDay === 0)) return `<p class="wb-note">Counted from the end of the first day.</p>`;
  const top = Math.max(...shown.flatMap((type) => type.arrivalChanceByHour));
  const tested = recorded && Math.abs(recorded.share_ojai - share) < 1e-9 ? recorded : null;
  const rows = shown
    .map((type) => {
      const peak = type.arrivalChanceByHour.indexOf(Math.max(...type.arrivalChanceByHour));
      const theirs = tested?.by_type.find((other) => other.name === type.name);
      return (
        `<tr><th scope="row">${type.name}<small>${whole(type.vehicles)} vehicles</small></th>` +
        `<td data-label="Visits a vehicle-day">${type.visitsPerVehicleDay.toFixed(1)}${theirs ? `<small>tests: ${theirs.visits_per_vehicle_day.toFixed(1)}</small>` : ""}</td>` +
        `<td data-label="Arriving low">${percent(type.arrivedLowShare)}${theirs ? `<small>tests: ${percent(theirs.arrived_at_floor_share)}</small>` : ""}</td>` +
        `<td data-label="On the charger">${minutes(type.minutesOnCharger, type.minutesOnCharger10to90)}${theirs?.minutes_on_charger != null ? `<small>tests: ${whole(theirs.minutes_on_charger)} min</small>` : ""}</td>` +
        `<td data-label="Energy a visit">${whole(type.kwhPerVisit)} kWh${theirs ? `<small>tests: ${whole(theirs.kwh_per_visit)} kWh</small>` : ""}</td>` +
        `<td data-label="Chance of coming in">${hours(type.arrivalChanceByHour, top, `Chance an ${type.name} comes in, hour by hour; busiest at ${String(peak).padStart(2, "0")}:00`)}<small>busiest ${String(peak).padStart(2, "0")}:00, ${percent(type.arrivalChanceByHour[peak])} an hour</small></td></tr>`
      );
    })
    .join("");
  const note = tested
    ? `"Tests" is the Python model at ${whole(tested.fleet)} vehicles and this mix, the median of forty runs (E30).`
    : recorded
      ? `The tests' figures by type are at the assumed mix, ${Math.round(100 * (1 - recorded.share_ojai))}/${Math.round(100 * recorded.share_ojai)}.`
      : "";
  return (
    `<table class="types"><thead><tr><th scope="col">Type</th><th scope="col">Visits a vehicle-day</th><th scope="col">Arriving low</th><th scope="col">On the charger</th><th scope="col">Energy a visit</th><th scope="col">Chance of coming in, by hour</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<p class="wb-note">Counted from the end of the first day; time on the charger to the nearest five minutes. ${note}</p>`
  );
}

/** One charger design as the tests ran it at the assumed mix (E33). */
export interface ChargerDesign {
  name: string;
  label: string;
  carried_on_1: number | null;
  carried_on_2: number | null;
  charger_cost_per_day_on_1: number;
  charger_cost_per_day_on_2: number;
  minutes_on_charger: Record<string, number | null>;
  on_150_kw_share: Record<string, number>;
}

export interface RecordedChargers {
  fleet_read_at: Record<string, number>;
  designs: ChargerDesign[];
  planned_on_two_feeders: number | null;
}

/** Minutes as the record has them: whole, or to the half minute a median of an even count gives. */
const tenth = (value: number): string => (Number.isInteger(value) ? whole(value) : value.toFixed(1));

/** The charger designs the tests ran: what each carries on one feeder and two, what it costs, and how long each type charges. */
export function chargersMarkup(chargers: RecordedChargers | null): string {
  if (!chargers) return "";
  const one = chargers.fleet_read_at["1"]!;
  const two = chargers.fleet_read_at["2"]!;
  const carried = (value: number | null, floor: number): string => (value === null ? `below ${whole(floor)}` : whole(value));
  const rows = chargers.designs
    .map((d) => {
      const ojai = d.minutes_on_charger["Ojai"];
      const ipace = d.minutes_on_charger["I-PACE"];
      return (
        `<tr><th scope="row">${d.label}</th>` +
        `<td data-label="One feeder">${carried(d.carried_on_1, 600)}<small>$${whole(d.charger_cost_per_day_on_1)} a day</small></td>` +
        `<td data-label="Two feeders">${carried(d.carried_on_2, 1200)}<small>$${whole(d.charger_cost_per_day_on_2)} a day</small></td>` +
        `<td data-label="On the charger at ${whole(one)}">${ipace != null ? `I-PACE ${tenth(ipace)} min` : ""}${ojai != null ? `<small>Ojai ${tenth(ojai)} min</small>` : ""}</td></tr>`
      );
    })
    .join("");
  const margin =
    chargers.planned_on_two_feeders !== null
      ? ` With 10% more energy, two feeders carry ${whole(chargers.planned_on_two_feeders)} (E34).`
      : "";
  return (
    `<h4 class="types-head">Chargers, from the tests</h4>` +
    `<table class="types chargers"><thead><tr><th scope="col">Design</th><th scope="col">One feeder</th><th scope="col">Two feeders</th><th scope="col">On the charger at ${whole(one)}</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<p class="wb-note">Vehicles carried in all four two-week windows at my energy estimate and the 60/40 mix, three runs a window (E33). Chargers a day at ${whole(one)} and ${whole(two)} vehicles, their installed cost over ten years.${margin}</p>`
  );
}
