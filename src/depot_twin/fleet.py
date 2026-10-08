"""A driverless fleet working out of one depot.

The fleet has no shifts. Vehicles serve rides until the depot calls them in, charge and get cleaned, and go
straight back out. That makes the depot a control problem: every vehicle pulled in at the wrong hour is a
ride nobody serves, and every vehicle pulled in too late arrives nearly empty with the rest of the fleet.

Service on the road is modelled in aggregate, in fixed steps. Rides offered in a step are served up to what
the vehicles on the road can carry; a ride nobody can take waits a few minutes for the next free vehicle and
is lost after that, so the count of lost rides does not depend on how fine the step is. Each vehicle's share of the work, and so its energy
use, varies around the mean, which keeps the fleet from draining in lockstep.
"""

from __future__ import annotations

import json
import tomllib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
import simpy

from depot_twin.control import Policy
from depot_twin.interfaces import DemandSource, FleetObserver, TelemetrySink
from depot_twin.resources import DAY_MIN, DepotConfig, VehicleModel, Visit, depot_from, model_from
from depot_twin.sim import DepotSim, Result, Session

ON_ROAD, INBOUND, AT_DEPOT, OUTBOUND = 0, 1, 2, 3
WEEK_HOURS = 168


@dataclass(frozen=True)
class FleetConfig:
    """The fleet and how it works. Figures marked "filed" come from public filings; the rest are assumed."""

    size: int
    models: tuple[VehicleModel, ...]
    mix: tuple[float, ...] = (1.0,)  # share of the fleet per model
    rides_per_vehicle_day: float = 25.0  # rides offered, per vehicle in the fleet
    ride_minutes: float = 23.0  # drive to the pickup, pick up, carry, drop off
    miles_to_pickup: float = 0.99  # filed
    miles_with_passenger: float = 3.93  # filed
    idle_mph: float = 2.4  # average speed with no ride assigned, parked time included; set by calibration
    kwh_per_mile: float = 0.40
    idle_kw: float = 1.5  # computers and climate control while switched on
    depot_leg_minutes: float = 15.0
    depot_leg_miles: float = 4.0
    floor_soc: float = 0.08  # a vehicle this low is sent in whatever the rule says
    # How long a rider waits for a vehicle to come free before giving up. Assumed: public wait times for
    # the service run from a few minutes to about ten. A ride waits whole steps, so with steps longer than
    # the wait a ride is served in the step it is offered in or not at all.
    max_wait_minutes: float = 10.0
    step_min: float = 15.0
    # How much individual vehicles differ from their type, as a standard deviation. No two vehicles use
    # exactly the same energy: tyres, alignment, battery age and software load all move it.
    vehicle_spread: float = 0.0


@dataclass
class FleetState:
    """What a recall rule can see when it decides."""

    now: float
    soc: np.ndarray
    status: np.ndarray
    demand_next_hours: np.ndarray  # expected rides per hour for the coming hours, this hour first
    demand_upper_hours: np.ndarray  # the level rides should stay under 95% of the time, same hours
    rides_per_vehicle_hour: float  # what one vehicle on the road can carry
    depot: DepotSim
    fleet: FleetConfig
    capacity_kwh: np.ndarray
    offered_last_hour: float = 0.0  # rides actually offered over the last 60 minutes

    @property
    def free_chargers(self) -> int:
        """Return chargers that are free and not already spoken for by a vehicle on its way in or waiting."""
        spoken_for = int((self.status == INBOUND).sum()) + len(self.depot.waiting)
        return max(0, sum(self.depot.free.values()) - spoken_for)

    @property
    def vehicles_needed(self) -> np.ndarray:
        """Return the vehicles on the road needed to serve the expected rides, for each coming hour."""
        return self.demand_next_hours / self.rides_per_vehicle_hour

    @property
    def on_road(self) -> np.ndarray:
        """Return the indices of vehicles in service."""
        return np.flatnonzero(self.status == ON_ROAD)


class RecallRule(Protocol):
    """Decides which vehicles to pull in, and how full to charge them."""

    def recall(self, state: FleetState) -> list[int]:
        """Return the vehicles to send to the depot now."""
        ...

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Return the state of charge at which this vehicle is released."""
        ...


class ThresholdRecall:
    """Send a vehicle in when its battery falls to a fixed level. The rule a fleet starts with."""

    name = "threshold"

    def __init__(self, recall_soc: float = 0.20, target: float = 0.85):
        self.recall_soc = recall_soc
        self.target = target

    def recall(self, state: FleetState) -> list[int]:
        """Recall every vehicle on the road at or below the threshold."""
        on_road = state.on_road
        return on_road[state.soc[on_road] <= self.recall_soc].tolist()

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Charge every vehicle to the same level."""
        return self.target


@dataclass
class FleetResult:
    """What the fleet and its depot did over the run."""

    config: FleetConfig
    depot: Result
    steps: np.ndarray  # one row per step: minute, offered, served, on_road, at_depot, lost
    miles: dict[str, float]
    energy_kwh: float
    days: float
    stranded: int

    def summary(self) -> dict[str, float]:
        """Return the headline numbers."""
        offered, on_road = self.steps[:, 1], self.steps[:, 3]
        peak = offered >= np.quantile(offered, 0.9)
        total_miles = sum(self.miles.values())
        visits = len(self.depot.sessions)
        return {
            "fleet": self.config.size,
            "days": self.days,
            "rides_served_share": served_share(self.steps),
            "rides_lost_per_day": float(self.steps[:, 5].sum() / self.days),
            "available_at_peak_share": float(on_road[peak].mean() / self.config.size),
            "available_mean_share": float(on_road.mean() / self.config.size),
            "miles_per_vehicle_day": total_miles / self.config.size / self.days,
            "idle_share": self.miles["idle"] / total_miles,
            "to_pickup_share": self.miles["to_pickup"] / total_miles,
            "with_passenger_share": self.miles["with_passenger"] / total_miles,
            "kwh_per_vehicle_day": self.energy_kwh / self.config.size / self.days,
            "depot_visits_per_vehicle_day": visits / self.config.size / self.days,
            "stranded": self.stranded,
            **{f"depot_{key}": value for key, value in self.depot.summary().items() if key != "vehicles"},
        }


def served_share(steps: np.ndarray) -> float:
    """Share of rides served over the steps: served against served plus given up on.

    A ride can be served a step or two after it was offered, so offered and served are not compared step
    by step; a ride is lost at the moment its rider gives up, and that is what is counted.
    """
    served, lost = float(steps[:, 2].sum()), float(steps[:, 5].sum())
    return served / (served + lost) if served + lost > 0 else 1.0


def busy_shares(total: float, weights: np.ndarray) -> np.ndarray:
    """Split `total` vehicle-steps of work across vehicles in proportion to their weights, none above one whole step.

    A vehicle that would be given more than a full step is capped there and the excess is shared out again
    among the others, until nothing is left or every vehicle is full. The shares sum to `total` whenever
    that is at most the number of vehicles, and to the number of vehicles otherwise.
    """
    n = len(weights)
    if n == 0:
        return np.zeros(0)
    busy = np.zeros(n)
    open_slots = np.ones(n, dtype=bool)
    left = min(float(total), float(n))
    for _ in range(n):
        if left <= 1e-12 or not open_slots.any():
            break
        share = left * weights[open_slots] / weights[open_slots].sum()
        room = 1.0 - busy[open_slots]
        given = np.minimum(share, room)
        busy[open_slots] += given
        left -= float(given.sum())
        open_slots &= busy < 1.0 - 1e-12
    return busy


@dataclass
class FleetSim:
    """Runs a fleet against a depot for a number of days."""

    config: FleetConfig
    depot_config: DepotConfig
    weekly_shape: np.ndarray  # 168 hourly shares of weekly demand, Monday 00:00 first
    recall_rule: RecallRule = field(default_factory=ThresholdRecall)
    depot_policy: Policy | str = "need_first"
    seed: int = 0
    depot_step_min: float = 1.0  # power integration step; training uses a coarser one for speed
    telemetry: TelemetrySink | None = None  # receives each step's miles, hours and energy per vehicle on the road
    # Replayed demand: an object with offered(minute, step_min) and ahead(minute). When absent, demand is
    # drawn from the weekly shape.
    demand: DemandSource | None = None
    observer: FleetObserver | None = None  # its tick(sim) is called once per step, after the step's decisions

    def __post_init__(self):
        cfg = self.config
        self.rng = np.random.default_rng(self.seed)
        # Demand and the split of work between vehicles each draw from their own stream, so that two arms
        # run with the same seed are offered the same rides whatever their vehicles are doing.
        self._demand_rng = np.random.default_rng([self.seed, 1])
        self._work_rng = np.random.default_rng([self.seed, 2])
        self._riders: deque[list[float]] = deque()  # rides waiting for a vehicle: [minute they give up, rides]
        self.env = simpy.Environment()
        self.depot = DepotSim(
            self.depot_config, [], self.depot_policy, self.depot_step_min, env=self.env, on_ready=self._released
        )
        self.model_of = self.rng.choice(len(cfg.models), size=cfg.size, p=np.array(cfg.mix) / sum(cfg.mix))
        self.capacity = np.array([cfg.models[m].capacity_kwh for m in self.model_of])
        self.drive_kwh, self.always_on_kw = self._energy_parameters()
        self.soc = self.rng.uniform(0.35, 0.9, size=cfg.size)
        self.status = np.full(cfg.size, ON_ROAD)
        self.miles = {"idle": 0.0, "to_pickup": 0.0, "with_passenger": 0.0}
        self.energy_kwh = 0.0
        self.stranded = 0
        self._visits = 0
        self._started = False
        self._steps: list[tuple[float, ...]] = []

    def rides_per_hour(self, minute: float) -> float:
        """Return the rides offered per hour at a given time."""
        hour_of_week = int(minute // 60) % WEEK_HOURS
        weekly_rides = self.config.rides_per_vehicle_day * 7 * self.config.size
        return float(self.weekly_shape[hour_of_week] * weekly_rides)

    def run(self, days: float = 7.0) -> FleetResult:
        """Run the fleet and return what happened."""
        self.advance(days * DAY_MIN)
        return self.result()

    def advance(self, minutes: float) -> None:
        """Move the clock forward. Lets a caller interleave its own decisions with the simulation."""
        if not self._started:
            self._started = True
            self.depot.start()
            self.env.process(self._loop())
        if minutes > 0:
            self.env.run(until=self.env.now + minutes)

    def result(self) -> FleetResult:
        """Return what has happened so far."""
        return FleetResult(
            config=self.config,
            depot=self.depot.result(),
            steps=np.array(self._steps),
            miles=dict(self.miles),
            energy_kwh=self.energy_kwh,
            days=self.env.now / DAY_MIN,
            stranded=self.stranded,
        )

    def _loop(self):
        while True:
            self._serve()
            self._recall()
            if self.observer is not None:
                self.observer.tick(self)
            yield self.env.timeout(self.config.step_min)

    def _serve(self) -> None:
        """Serve one step of rides with the vehicles on the road, and drain their batteries."""
        cfg = self.config
        on_road = np.flatnonzero(self.status == ON_ROAD)
        # A vehicle with nothing left in its battery is on the road but carries nobody.
        able = on_road[self.soc[on_road] > 0.0]
        hours = cfg.step_min / 60.0
        offered = self._offered(hours)
        can_carry = len(able) * cfg.step_min / cfg.ride_minutes
        served, lost = self._take_rides(float(offered), can_carry)
        self._steps.append((self.env.now, offered, served, len(on_road), int((self.status == AT_DEPOT).sum()), lost))
        if len(on_road) == 0:
            return
        # Each vehicle's busy share of the step varies around the fleet mean and cannot exceed the whole step,
        # and the shares add up to exactly the minutes the rides served took: what a vehicle cannot absorb
        # goes to the others, so the batteries are drained for every ride that was counted.
        busy = np.zeros(len(on_road))
        working = self.soc[on_road] > 0.0
        busy[working] = busy_shares(
            served * cfg.ride_minutes / cfg.step_min, self._work_rng.gamma(4.0, 0.25, size=int(working.sum()))
        )
        ride_miles = cfg.miles_to_pickup + cfg.miles_with_passenger
        service_miles = busy * hours * ride_miles / (cfg.ride_minutes / 60.0)
        idle_miles = (1.0 - busy) * hours * cfg.idle_mph
        self.miles["to_pickup"] += float(service_miles.sum() * cfg.miles_to_pickup / ride_miles)
        self.miles["with_passenger"] += float(service_miles.sum() * cfg.miles_with_passenger / ride_miles)
        self.miles["idle"] += float(idle_miles.sum())
        miles = service_miles + idle_miles
        energy = miles * self.drive_kwh[on_road] + self.always_on_kw[on_road] * hours
        if self.telemetry is not None:
            self.telemetry.record(on_road, miles, hours, energy)
        self._drain(on_road, energy)

    def _take_rides(self, offered: float, can_carry: float) -> tuple[float, float]:
        """Serve the riders who have waited longest first; return the rides served and those given up on."""
        now, cfg = self.env.now, self.config
        lost = 0.0
        while self._riders and self._riders[0][0] <= now:
            lost += self._riders.popleft()[1]
        if offered > 0:
            self._riders.append([now + max(cfg.max_wait_minutes, cfg.step_min), offered])
        served = 0.0
        while self._riders and can_carry - served > 1e-12:
            taken = min(self._riders[0][1], can_carry - served)
            served += taken
            self._riders[0][1] -= taken
            if self._riders[0][1] <= 1e-12:
                self._riders.popleft()
        return served, lost

    def _offered(self, hours: float) -> int:
        """Return the rides offered in this step: drawn from the weekly shape, or replayed from real days."""
        if self.demand is None:
            return int(self._demand_rng.poisson(self.rides_per_hour(self.env.now) * hours))
        # Replayed counts already carry real noise; a fractional ride is rounded up or down at random.
        rides = self.demand.offered(self.env.now, self.config.step_min)
        return int(rides) + int(self._demand_rng.random() < rides - int(rides))

    def _energy_parameters(self) -> tuple[np.ndarray, np.ndarray]:
        """Return each vehicle's true driving energy (kWh per mile) and always-on load (kW)."""
        cfg = self.config
        by_model_drive = [
            m.drive_kwh_per_mile if m.drive_kwh_per_mile is not None else cfg.kwh_per_mile for m in cfg.models
        ]
        by_model_load = [m.always_on_kw if m.always_on_kw is not None else cfg.idle_kw for m in cfg.models]
        drive = np.array(by_model_drive)[self.model_of]
        load = np.array(by_model_load)[self.model_of]
        if cfg.vehicle_spread > 0:
            # Drawn only when asked for, so scenarios without a spread keep their random sequence.
            drive = drive * np.clip(self.rng.normal(1.0, cfg.vehicle_spread, cfg.size), 0.7, 1.3)
            load = load * np.clip(self.rng.normal(1.0, cfg.vehicle_spread, cfg.size), 0.7, 1.3)
        return drive, load

    def _drain(self, vehicles: np.ndarray, energy_kwh: np.ndarray | float) -> None:
        # A battery gives only what it holds: energy asked of an empty one is not counted as used.
        held = self.soc[vehicles] * self.capacity[vehicles]
        used = np.minimum(energy_kwh, held)
        self.energy_kwh += float(np.sum(used))
        self.soc[vehicles] = (held - used) / self.capacity[vehicles]

    def state(self) -> FleetState:
        """Return the view of the fleet a recall rule decides on."""
        if self.demand is None:
            hour = int(self.env.now // 60)
            ahead = np.array([self.rides_per_hour((hour + h) * 60.0) for h in range(24)])
            upper = ahead
        else:
            ahead, upper = self.demand.ahead(self.env.now)
        return FleetState(
            now=self.env.now,
            soc=self.soc,
            status=self.status,
            demand_next_hours=ahead,
            demand_upper_hours=upper,
            offered_last_hour=self._offered_last_hour(),
            rides_per_vehicle_hour=60.0 / self.config.ride_minutes,
            depot=self.depot,
            fleet=self.config,
            capacity_kwh=self.capacity,
        )

    def _offered_last_hour(self) -> float:
        steps = max(1, round(60.0 / self.config.step_min))
        return float(sum(row[1] for row in self._steps[-steps:]))

    def _recall(self) -> None:
        cfg = self.config
        state = self.state()
        chosen = set(self.recall_rule.recall(state))
        slot = getattr(self.recall_rule, "slot_minutes", None)  # only time-boxing rules have one
        # Safety net: a vehicle near empty comes in regardless of the rule.
        forced = np.flatnonzero((self.status == ON_ROAD) & (self.soc <= cfg.floor_soc))
        for vehicle in sorted(chosen | set(forced.tolist())):
            if self.status[vehicle] != ON_ROAD:
                continue
            self.status[vehicle] = INBOUND
            self.miles["idle"] += cfg.depot_leg_miles
            self._drain(np.array([vehicle]), self._leg_kwh(vehicle))
            if self.soc[vehicle] <= 0.0:
                self.stranded += 1
            self._visits += 1
            self.depot.add_visit(
                Visit(
                    vehicle_id=str(vehicle),
                    visit_id=f"{vehicle}:{self._visits}",
                    model=cfg.models[self.model_of[vehicle]],
                    arrive_min=self.env.now + cfg.depot_leg_minutes,
                    soc_in=float(self.soc[vehicle]),
                    target_soc=self.recall_rule.target_soc(vehicle, state),
                    max_minutes=slot(vehicle, state) if slot else None,
                )
            )
            self.env.process(self._arrive(vehicle))

    def _leg_kwh(self, vehicle: int) -> float:
        """Energy for one drive between the road and the depot: the miles, and the always-on load for its minutes."""
        cfg = self.config
        return float(
            cfg.depot_leg_miles * self.drive_kwh[vehicle] + self.always_on_kw[vehicle] * cfg.depot_leg_minutes / 60.0
        )

    def _arrive(self, vehicle: int):
        yield self.env.timeout(self.config.depot_leg_minutes)
        self.status[vehicle] = AT_DEPOT

    def _released(self, session: Session) -> None:
        """Take a vehicle the depot has finished and send it back into service."""
        vehicle = int(session.visit.vehicle_id)
        self.soc[vehicle] = session.soc
        self.status[vehicle] = OUTBOUND
        self.env.process(self._return_to_service(vehicle))

    def _return_to_service(self, vehicle: int):
        cfg = self.config
        yield self.env.timeout(cfg.depot_leg_minutes)
        self.miles["idle"] += cfg.depot_leg_miles
        self._drain(np.array([vehicle]), self._leg_kwh(vehicle))
        self.status[vehicle] = ON_ROAD


def load_fleet_scenario(path: str | Path) -> tuple[FleetConfig, DepotConfig]:
    """Read a fleet scenario: a depot, the vehicle models, and the fleet that works out of it."""
    data = tomllib.loads(Path(path).read_text())
    fleet = dict(data["fleet"])
    mix = fleet.pop("mix")
    models = tuple(model_from(name, data["models"][name]) for name in mix)
    return FleetConfig(models=models, mix=tuple(mix.values()), **fleet), depot_from(data["depot"])


def load_weekly_shape(path: str | Path) -> np.ndarray:
    """Read the weekly demand shape written by the demand evaluation."""
    shares = np.array(json.loads(Path(path).read_text())["shares"], dtype=float)
    if shares.shape != (WEEK_HOURS,):
        raise ValueError(f"expected {WEEK_HOURS} hourly shares, got {shares.shape}")
    return shares / shares.sum()
