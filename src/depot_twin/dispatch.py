"""Recall rules: when the depot calls a vehicle in, and how full it sends it back out.

Three rules beyond the fixed threshold in fleet.py, in order of sophistication:

- HeadroomRecall charges the vehicles that need it most, but only when the road can spare them and a charger
  is free. It is the hand-written rule an operations team would arrive at.
- RollingPlan solves a small linear program every hour: over the next day, how many vehicles to pull in
  each hour so that the fewest rides are lost, given the power the site can deliver.
- ParamRecall exposes two dials, the recall level and the release level, for a learned policy to turn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from ortools.linear_solver import pywraplp

from depot_twin.fleet import INBOUND, FleetState

HARD_FLOOR_SOC = 0.12  # below this a vehicle comes in whatever the plan says


def lowest(state: FleetState, count: int, below: float = 1.0) -> list[int]:
    """Return up to count vehicles on the road with the emptiest batteries, all under the given level."""
    on_road = state.on_road
    eligible = on_road[state.soc[on_road] < below]
    order = eligible[np.argsort(state.soc[eligible])]
    return order[: max(0, count)].tolist()


def must_come_in(state: FleetState) -> list[int]:
    """Return the vehicles on the road that are too low to leave out."""
    on_road = state.on_road
    return on_road[state.soc[on_road] <= HARD_FLOOR_SOC].tolist()


class HeadroomRecall:
    """Charge the emptiest vehicles, when the road can spare them and a charger is free.

    A vehicle is pulled in early, well above the point where it must stop, if demand right now leaves
    vehicles idle. Near a peak, vehicles are released part-charged so they are on the road when needed.
    """

    name = "headroom"

    def __init__(self, top_up_below: float = 0.60, full: float = 0.85, quick: float = 0.65, margin: float = 1.10):
        self.top_up_below = top_up_below
        self.full = full
        self.quick = quick
        self.margin = margin

    def recall(self, state: FleetState) -> list[int]:
        """Recall as many low vehicles as the road can spare and the chargers can take."""
        needed_soon = float(state.vehicles_needed[:2].max()) * self.margin
        spare = int(len(state.on_road) - needed_soon)
        take = min(spare, state.free_chargers)
        return sorted(set(must_come_in(state)) | set(lowest(state, take, below=self.top_up_below)))

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Release part-charged when the next two hours need more vehicles than are on the road."""
        peak_ahead = float(state.vehicles_needed[1:3].max()) > len(state.on_road)
        return self.quick if peak_ahead else self.full


class SteeredThreshold:
    """A threshold that knows the clock: charge more before the evening price peak, less during it.

    It uses no forecast and no plan. Before the peak it calls vehicles in at a higher charge level, so they
    do not run down in the expensive hours; during the peak it calls only those that cannot wait. It is the
    simplest rule that can move energy purchases in time, and so the one a price-aware plan has to beat.
    """

    name = "steered_threshold"

    def __init__(
        self,
        recall_soc: float = 0.20,
        before_peak_soc: float = 0.40,
        peak_soc: float = 0.15,
        target: float = 0.85,
        pre_peak_hours: float = 4.0,
        peak_hours: tuple[float, float] = (16.0, 21.0),
    ):
        self.recall_soc = recall_soc
        self.before_peak_soc = before_peak_soc
        self.peak_soc = peak_soc
        self.target = target
        self.pre_peak_hours = pre_peak_hours
        self.peak_hours = peak_hours

    def level(self, minute: float) -> float:
        """Return the charge level under which vehicles are called in at this time of day."""
        hour = (minute / 60.0) % 24.0
        start, end = self.peak_hours
        if start <= hour < end:
            return self.peak_soc
        if start - self.pre_peak_hours <= hour < start:
            return self.before_peak_soc
        return self.recall_soc

    def recall(self, state: FleetState) -> list[int]:
        """Recall every vehicle on the road at or below the level for this time of day."""
        on_road = state.on_road
        return on_road[state.soc[on_road] <= self.level(state.now)].tolist()

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Charge every vehicle to the same level."""
        return self.target


class ParamRecall:
    """A threshold rule whose two levels are set from outside, hour by hour."""

    name = "learned"

    def __init__(self, recall_soc: float = 0.20, target: float = 0.85):
        self.recall_soc = recall_soc
        self.target = target

    def recall(self, state: FleetState) -> list[int]:
        """Recall vehicles under the current level, emptiest first, no more than the free chargers."""
        return sorted(set(must_come_in(state)) | set(lowest(state, state.free_chargers, below=self.recall_soc)))

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Release at the current target level."""
        return self.target


class RollingPlan:
    """Plan the next day every hour with a linear program, and carry out its first hour.

    The program treats the fleet as a fluid: so many vehicles on the road, so much energy in their
    batteries, so much energy owed to the vehicles in the depot. It is coarse on purpose. Its purpose is to see
    the evening peak coming at noon, which no threshold can.
    """

    name = "plan"

    def __init__(self, target: float = 0.85, horizon: int = 24, charger_avg_kw: float = 50.0):
        self.target = target
        self.horizon = horizon
        self.charger_avg_kw = charger_avg_kw
        self._hour = -1
        self._quota = 0.0  # vehicles the plan still wants pulled in during the current hour
        self._steps_left = 0

    def recall(self, state: FleetState) -> list[int]:
        """Re-plan on the hour, then pull in this step's share of the hour's quota."""
        hour = int(state.now // 60)
        if hour != self._hour:
            self._hour = hour
            self._quota = self._plan(state)
            self._steps_left = max(1, round(60.0 / state.fleet.step_min))
        # Never send more than the free chargers can take: a vehicle queueing at the depot serves no one.
        take = min(math.ceil(self._quota / self._steps_left), state.free_chargers) if self._quota > 0 else 0
        self._steps_left = max(1, self._steps_left - 1)
        chosen = lowest(state, take, below=self.target - 0.05)
        self._quota -= len(chosen)
        return sorted(set(must_come_in(state)) | set(chosen))

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Release at the planned level."""
        return self.target

    def _plan(self, state: FleetState) -> float:
        """Return the number of vehicles to recall in the coming hour."""
        return _solve(_inputs(state, self.target, self.charger_avg_kw), self.horizon, self.target)


@dataclass(frozen=True)
class PlanInputs:
    """The fleet, reduced to the handful of totals the program works with."""

    size: int
    cap: float  # mean battery size, kWh
    away: float  # vehicles not on the road now
    soc_in: float  # charge level recalled vehicles arrive with
    per_visit: float  # kWh one visit puts into a vehicle
    chargers: int
    power: float  # kWh the site can put into vehicles per hour
    owed: float  # kWh still owed to vehicles already in or heading to the depot
    road_energy: float  # kWh in the batteries of vehicles on the road
    ride_kwh: float
    idle_kwh: float  # kWh per hour a vehicle on the road uses with no ride
    rate: float  # rides one vehicle can carry per hour
    demand: np.ndarray


def _inputs(state: FleetState, target: float, charger_avg_kw: float) -> PlanInputs:
    fleet, depot = state.fleet, state.depot.depot
    cap = float(state.capacity_kwh.mean())
    on_road = state.on_road
    # The plan recalls the emptiest vehicles, so that is the charge level they arrive with.
    tail = max(1, fleet.size // 10)
    soc_in = float(np.sort(state.soc[on_road])[:tail].mean()) if len(on_road) else 0.2
    chargers = sum(bank.count for bank in depot.chargers)
    owed = sum(s.energy_left_kwh for s in state.depot.waiting + state.depot.charging)
    owed += float(((target - state.soc) * state.capacity_kwh)[state.status == INBOUND].clip(min=0).sum())
    return PlanInputs(
        size=fleet.size,
        cap=cap,
        away=float(fleet.size - len(on_road)),
        soc_in=soc_in,
        per_visit=max(5.0, (target - soc_in) * cap),
        chargers=chargers,
        power=min(depot.usable_kw * depot.charger_efficiency, chargers * charger_avg_kw),
        owed=owed,
        road_energy=float((state.soc[on_road] * state.capacity_kwh[on_road]).sum()),
        ride_kwh=(fleet.miles_to_pickup + fleet.miles_with_passenger) * fleet.kwh_per_mile,
        idle_kwh=fleet.idle_kw + fleet.idle_mph * fleet.kwh_per_mile,
        rate=state.rides_per_vehicle_hour,
        demand=state.demand_next_hours,
    )


def _solve(p: PlanInputs, horizon: int, target: float) -> float:
    return solve_plan(p, horizon, target)[0]


def solve_plan(
    p: PlanInputs, horizon: int, target: float, reserve_soc: float = 0.15, stored_value: float = 0.0
) -> tuple[float, list[float]]:
    """Solve the day plan. Returns vehicles to recall this hour and the planned vehicles on the road per hour.

    reserve_soc is the charge the road fleet should keep in hand; the plan pays for every kWh it is short.
    stored_value is what a ride's worth of energy held on the road is worth per hour, in rides. At zero the
    plan charges just in time, which leaves nothing for a forecast that turns out low; a small positive
    value makes it charge whenever vehicles and chargers are spare, and never at the cost of a ride.
    """
    solver = pywraplp.Solver.CreateSolver("GLOP")
    inf = solver.infinity()
    hours = range(horizon)
    x = [solver.NumVar(0, p.size, f"recall{t}") for t in hours]
    y = [solver.NumVar(0, p.size, f"return{t}") for t in hours]
    charge = [solver.NumVar(0, p.power, f"charge{t}") for t in hours]
    served = [solver.NumVar(0, float(p.demand[t % 24]), f"served{t}") for t in hours]
    # The depot may already hold more vehicles than the plan would choose; that must not make it infeasible.
    inside = [solver.NumVar(0, max(p.chargers * 1.1, p.away + 1.0), f"inside{t}") for t in hours]
    backlog = [solver.NumVar(0, inf, f"backlog{t}") for t in hours]
    energy = [solver.NumVar(-inf, inf, f"energy{t}") for t in hours]
    short = [solver.NumVar(0, inf, f"short{t}") for t in hours]

    prev_inside, prev_backlog, prev_energy, prev_charge = p.away, p.owed, p.road_energy, min(p.power, p.owed)
    for t in hours:
        on = p.size - inside[t]
        solver.Add(inside[t] == prev_inside + x[t] - y[t])
        solver.Add(backlog[t] == prev_backlog + p.per_visit * x[t] - charge[t])
        # Vehicles come back as their energy is delivered, an hour later for the drive and the cleaning.
        solver.Add(y[t] * p.per_visit <= prev_charge)
        solver.Add(served[t] <= p.rate * on)
        used = p.ride_kwh * served[t] + p.idle_kwh * on
        solver.Add(energy[t] == prev_energy - used - p.soc_in * p.cap * x[t] + target * p.cap * y[t])
        # Soft floor: the road fleet should keep 15% in hand, and the plan pays for every kWh it is short.
        solver.Add(short[t] >= reserve_soc * p.cap * on - energy[t])
        prev_inside, prev_backlog, prev_energy, prev_charge = inside[t], backlog[t], energy[t], charge[t]

    # Rides served; a small cost per recall to avoid churn; a value on energy left at the end so the plan
    # does not finish the day with a drained fleet.
    kwh_per_ride = p.ride_kwh + p.idle_kwh / p.rate
    end_value = 0.3 / kwh_per_ride
    held = stored_value / kwh_per_ride * sum(energy)
    solver.Maximize(sum(served) - 0.01 * sum(x) - 0.5 * sum(short) + end_value * energy[-1] + held)
    if solver.Solve() not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return 0.0, [p.size - p.away] * horizon
    return float(x[0].solution_value()), [p.size - float(v.solution_value()) for v in inside]


__all__ = ["HeadroomRecall", "ParamRecall", "RollingPlan", "SteeredThreshold", "lowest", "must_come_in"]
