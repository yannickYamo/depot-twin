"""A trace: everything a viewer needs to replay a run, one record per step.

The simulator keeps totals. A viewer needs the picture at every moment: how many vehicles are where, which
charger holds which vehicle and how full it is, what the grid is delivering, what was promised. A recorder
rides along with a run and writes that picture down each step. The file it produces is the contract between
the simulator and any front end, so its shape is versioned and checked by a test.

Chargers are not individual objects in the simulator, only a count. The recorder gives each charging
session a stall when it first sees it and frees the stall when the session ends, which is enough to draw a
depot floor that behaves like one.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from depot_twin.economics import tariff_period
from depot_twin.fleet import AT_DEPOT, INBOUND, ON_ROAD, OUTBOUND, FleetSim

TRACE_VERSION = 1
STEP_COLUMNS = (
    "minute",
    "on_road",
    "inbound",
    "queued",
    "charging",
    "cleaning",
    "handling",  # at the depot between stations: being plugged in or unplugged, or waiting for a bay
    "outbound",
    "arrivals",
    "departures",
    "offered",
    "served",
    "grid_kw",
    "buffer_kwh",
    "forecast",
    "forecast_upper",
    "promised",
    "tariff",
)


# Where a vehicle that is off the road can be, numbered in the order a visit runs. Shared with the browser
# simulator (web/src/trace.ts), which also tells cleaning (6) apart from the rest of "after charging".
PLACE_ON_THE_WAY = {
    "inbound": 1,
    "queued": 2,
    "plugging_in": 3,
    "charging": 4,
    "after_charging": 5,
    "cleaning": 6,
    "outbound": 7,
}


class TraceRecorder:
    """Attach to a fleet simulation before it runs; call export afterwards."""

    def __init__(self, sim: FleetSim, label: str = ""):
        self.sim = sim
        self.label = label
        self.steps: dict[str, list] = {name: [] for name in STEP_COLUMNS}
        self.stalls: list[list[list[int]]] = []
        self.chains: list[list[int]] = []
        self.plans: list[dict] = []  # the day plan each time it was redrawn, for rules that make one
        self._plans_seen = -1
        self._stall_of: dict[str, int] = {}
        self._power: dict[str, list[float]] = {}
        self._series_seen = 0
        self._sessions_seen = 0
        self._ready_seen = 0
        sim.observer = self
        sim.depot.on_power = self._on_power

    def _on_power(self, session, kw: float, could_take_kw: float) -> None:
        self._power.setdefault(session.sid, []).append(kw)

    def tick(self, sim: FleetSim) -> None:
        """Record one step."""
        depot = sim.depot
        status = sim.status
        queued, charging, cleaning = len(depot.waiting), len(depot.charging), depot.bays.count
        at_depot = int((status == AT_DEPOT).sum())
        offered, served = sim._steps[-1][1], sim._steps[-1][2]
        window = depot._series[self._series_seen :]
        self._series_seen = len(depot._series)
        ready = sum(1 for s in depot.sessions if s.ready_min is not None)
        state = sim.state()
        open_promise = getattr(sim.recall_rule, "_open", None)
        row = {
            "minute": round(sim.env.now),
            "on_road": int((status == ON_ROAD).sum()),
            "inbound": int((status == INBOUND).sum()),
            "queued": queued,
            "charging": charging,
            "cleaning": cleaning,
            # Not clamped: a negative count here means a vehicle was counted at two stations, and the contract says so.
            "handling": at_depot - queued - charging - cleaning,
            "outbound": int((status == OUTBOUND).sum()),
            "arrivals": len(depot.sessions) - self._sessions_seen,
            "departures": ready - self._ready_seen,
            "offered": int(offered),
            "served": round(float(served), 1),
            "grid_kw": round(float(np.mean([r[1] for r in window])) if window else 0.0),
            "buffer_kwh": round(depot.power.buffer_kwh),
            # The forecast for the hour that starts one hour from now: the one-hour horizon the forecasts are
            # tested at. The entry before it, for the hour already under way, is a cruder interpolation.
            "forecast": round(float(state.demand_next_hours[1])),
            "forecast_upper": round(float(state.demand_upper_hours[1])),
            "promised": round(open_promise["committed"]) if open_promise else None,
            "tariff": tariff_period(sim.env.now),
        }
        self._sessions_seen, self._ready_seen = len(depot.sessions), ready
        for name, value in row.items():
            self.steps[name].append(value)
        self.stalls.append(self._stall_snapshot())
        self.chains.append(self._chain_snapshot())
        self._note_plan(sim, row["minute"])

    def _note_plan(self, sim: FleetSim, minute: int) -> None:
        """Keep the plan once each time it is redrawn, with the hour's quota and promise."""
        rule = getattr(sim.recall_rule, "primary", sim.recall_rule)
        schedule, open_promise = getattr(rule, "schedule", None), getattr(rule, "_open", None)
        if not schedule or open_promise is None or open_promise["hour"] == self._plans_seen:
            return
        self._plans_seen = open_promise["hour"]
        self.plans.append(
            {
                "step": len(self.steps["minute"]) - 1,
                "minute": minute,
                "quota": round(float(getattr(rule, "_quota", 0.0)), 2),
                "committed": round(open_promise["committed"]),
                **schedule,
            }
        )

    def _chain_snapshot(self) -> list[int]:
        """Return vehicle, place and charge in percent, three numbers each, for every vehicle off the road.

        This is what lets a viewer follow one vehicle through the depot. Places are numbered in the order
        a visit runs: see PLACE_ON_THE_WAY.
        """
        sim, depot = self.sim, self.sim.depot
        place = {}
        for session in depot.sessions:
            if session.ready_min is not None:
                continue
            vehicle = int(session.visit.vehicle_id)
            if session.charged_min is not None:
                place[vehicle] = PLACE_ON_THE_WAY["after_charging"]
            elif session.connected_min is not None:
                place[vehicle] = PLACE_ON_THE_WAY["charging"]
            elif session.assigned_min is not None:
                place[vehicle] = PLACE_ON_THE_WAY["plugging_in"]
            else:
                place[vehicle] = PLACE_ON_THE_WAY["queued"]
        out: list[int] = []
        for vehicle in np.flatnonzero(sim.status != ON_ROAD):
            status = sim.status[vehicle]
            code = {INBOUND: PLACE_ON_THE_WAY["inbound"], OUTBOUND: PLACE_ON_THE_WAY["outbound"]}.get(status)
            code = code or place.get(int(vehicle), PLACE_ON_THE_WAY["after_charging"])
            out += [int(vehicle), code, round(float(sim.soc[vehicle]) * 100)]
        return out

    def _stall_snapshot(self) -> list[list[int]]:
        """Return [stall, vehicle, charge in percent, kW] for every vehicle on a charger now."""
        charging = self.sim.depot.charging
        live = {s.sid for s in charging}
        for sid in [sid for sid in self._stall_of if sid not in live]:
            del self._stall_of[sid]
        taken = set(self._stall_of.values())
        snapshot = []
        for session in charging:
            if session.sid not in self._stall_of:
                stall = next(n for n in range(len(taken) + 1) if n not in taken)
                self._stall_of[session.sid] = stall
                taken.add(stall)
            readings = self._power.pop(session.sid, [])
            vehicle = int(session.visit.vehicle_id)
            kw = round(float(np.mean(readings))) if readings else 0
            snapshot.append([self._stall_of[session.sid], vehicle, round(session.soc * 100), kw])
        return sorted(snapshot)

    def meta(self) -> dict:
        """Return what the run was: the site, the fleet and the rules."""
        sim = self.sim
        site = sim.depot.depot
        return {
            "label": self.label,
            "depot": site.name,
            "fleet": sim.config.size,
            "site_limit_kw": site.site_limit_kw,
            "usable_kw": site.usable_kw,
            "chargers": sum(bank.count for bank in site.chargers),
            "charger_kw": max(bank.kw for bank in site.chargers),
            "buffer_kwh": site.buffer.energy_kwh if site.buffer else 0.0,
            "cleaning_bays": site.cleaning_bays,
            "step_min": sim.config.step_min,
            "recall": getattr(sim.recall_rule, "name", "custom"),
            "power_rule": getattr(sim.depot.policy, "name", "custom"),
            "seed": sim.seed,
        }

    def to_dict(self) -> dict:
        """Return the whole trace."""
        return {
            "version": TRACE_VERSION,
            "meta": self.meta(),
            "steps": self.steps,
            "stalls": self.stalls,
            "chains": self.chains,
            "plans": self.plans,
        }

    def export(self, path: str | Path) -> Path:
        """Write the trace as compact JSON and return its path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), separators=(",", ":")))
        return path


def problems(trace: dict) -> list[str]:
    """Return everything wrong with a trace's shape or its physics. An empty list means it is sound.

    This is the contract a front end can rely on, written as checks: the columns that exist, that they are
    the same length, that vehicles are conserved, and that nothing exceeds what the site has.
    """
    found: list[str] = []
    if trace.get("version") != TRACE_VERSION:
        return [f"version is {trace.get('version')}, expected {TRACE_VERSION}"]
    meta, steps, stalls = trace["meta"], trace["steps"], trace["stalls"]
    if set(steps) != set(STEP_COLUMNS):
        found.append(f"columns differ: {sorted(set(steps) ^ set(STEP_COLUMNS))}")
        return found
    length = len(steps["minute"])
    found += [
        f"column {name} has {len(column)} rows, expected {length}"
        for name, column in steps.items()
        if len(column) != length
    ]
    if len(stalls) != length:
        found.append(f"stalls has {len(stalls)} rows, expected {length}")
    chains = trace.get("chains")
    if chains is not None and len(chains) != length:
        found.append(f"chains has {len(chains)} rows, expected {length}")
    if found:
        return found
    for k in range(length):
        found += _step_problems(k, meta, steps, stalls[k])
        if chains is not None and len(chains[k]) != 3 * (meta["fleet"] - steps["on_road"][k]):
            found.append(f"step {k}: the vehicles named off the road do not match the count")
    found += _ride_problems(steps)
    return found[:20]


PLACES = ("on_road", "inbound", "queued", "charging", "cleaning", "handling", "outbound")


def _step_problems(k: int, meta: dict, steps: dict, stalls: list[list[int]]) -> list[str]:
    """Return what is wrong with one step: vehicles conserved, limits respected, stalls consistent."""
    found = []
    if sum(steps[name][k] for name in PLACES) != meta["fleet"]:
        found.append(f"step {k}: vehicles do not add up to the fleet")
    if steps["grid_kw"][k] > meta.get("usable_kw", meta["site_limit_kw"]) + 1:
        found.append(f"step {k}: grid draw over the site limit")
    if len(stalls) != steps["charging"][k]:
        found.append(f"step {k}: stalls listed do not match vehicles charging")
    numbers = [entry[0] for entry in stalls]
    if len(set(numbers)) != len(numbers) or any(not 0 <= n < meta["chargers"] for n in numbers):
        found.append(f"step {k}: a stall is used twice or does not exist")
    if any(not 0 <= entry[2] <= 100 or entry[3] < 0 or entry[3] > meta["charger_kw"] + 1 for entry in stalls):
        found.append(f"step {k}: a charge level or power is out of range")
    if any(steps[name][k] < 0 for name in PLACES):
        found.append(f"step {k}: a negative count of vehicles at a station")
    return found


def _ride_problems(steps: dict) -> list[str]:
    """A ride can be served a step or two after it was offered, never before: served so far never passes offered so far."""
    served = offered = 0.0
    for k in range(len(steps["minute"])):
        served, offered = served + steps["served"][k], offered + steps["offered"][k]
        # Served is stored to a tenth of a ride a step.
        if served > offered + 0.05 * (k + 1):
            return [f"step {k}: more rides served than had been offered by then"]
    return []
