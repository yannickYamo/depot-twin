"""The depot simulator.

A vehicle arrives, waits for a charger, is plugged in by a person, charges under the site's power limit, is
unplugged, cleaned, and is then ready for service. Events (arrivals, staff, bays) are discrete; power is
integrated in fixed steps because every charging vehicle shares one grid connection and one buffer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import simpy

from depot_twin.control import Policy, make_policy
from depot_twin.grid import PowerManager
from depot_twin.resources import DAY_MIN, DepotConfig, Scenario, Visit

EPS_KWH = 1e-6


@dataclass
class Session:
    """One visit as it moves through the depot."""

    visit: Visit
    soc: float
    kind: str | None = None
    charger_kw: float = 0.0
    energy_kwh: float = 0.0
    assigned_min: float | None = None
    connected_min: float | None = None
    charged_min: float | None = None
    ready_min: float | None = None
    cleaned: bool = False  # whether this visit was cleaned
    inspected: bool = False  # whether this visit was inspected
    assigned: simpy.Event | None = field(default=None, repr=False)
    done: simpy.Event | None = field(default=None, repr=False)

    @property
    def sid(self) -> str:
        """Return the session's identifier."""
        return self.visit.key

    @property
    def charger_kind(self) -> str:
        """The kind of charger this session is on. Only asked once it has been given one."""
        assert self.kind is not None
        return self.kind

    @property
    def energy_left_kwh(self) -> float:
        """Return the energy still missing to reach the target."""
        return max(0.0, self.visit.target_soc - self.soc) * self.visit.model.capacity_kwh

    def want_kw(self, dt_hours: float) -> float:
        """Return the power this session can use in the coming step."""
        accept = self.visit.model.accept_kw(self.soc, self.kind or "dc")
        return min(self.charger_kw, accept, self.energy_left_kwh / dt_hours)


# Columns of Result.series, one row per power step.
SERIES_COLUMNS = ("minute", "grid_kw", "buffer_kw", "charging", "waiting", "buffer_kwh")


@dataclass
class Result:
    """Everything a run produced."""

    depot: DepotConfig
    sessions: list[Session]
    series: np.ndarray
    policy: str

    def summary(self) -> dict[str, float]:
        """Return the headline numbers for the run."""
        finished = [(s, s.ready_min) for s in self.sessions if s.ready_min is not None]
        done = [s for s, _ in finished]
        turnaround = np.array([ready - s.visit.arrive_min for s, ready in finished])
        wait = np.array([s.assigned_min - s.visit.arrive_min for s in done if s.assigned_min is not None])
        due = [s for s in self.sessions if s.visit.due_min is not None]
        on_time = [s for s, ready in finished if s.visit.due_min is not None and ready <= s.visit.due_min]
        step_hours = (self.series[1, 0] - self.series[0, 0]) / 60.0 if len(self.series) > 1 else 0.0
        last_ready = max(ready for _, ready in finished) if finished else 0.0
        span_hours = (last_ready - min(s.visit.arrive_min for s in done)) / 60.0 if done else 0.0
        return {
            "vehicles": len(self.sessions),
            "finished": len(done),
            "on_time_share": len(on_time) / len(due) if due else 1.0,
            "turnaround_mean_min": float(turnaround.mean()) if len(turnaround) else 0.0,
            "turnaround_p95_min": float(np.percentile(turnaround, 95)) if len(turnaround) else 0.0,
            "queue_wait_mean_min": float(wait.mean()) if len(wait) else 0.0,
            "energy_delivered_kwh": float(sum(s.energy_kwh for s in self.sessions)),
            "grid_energy_kwh": float(self.series[:, 1].sum() * step_hours) if len(self.series) else 0.0,
            "peak_grid_kw": float(self.series[:, 1].max()) if len(self.series) else 0.0,
            "vehicles_per_hour": len(done) / span_hours if span_hours > 0 else 0.0,
        }


class DepotSim:
    """Runs one scenario under one control rule."""

    def __init__(
        self,
        depot: DepotConfig,
        visits: list[Visit],
        policy: Policy | str = "need_first",
        step_min: float = 1.0,
        env: simpy.Environment | None = None,
        on_ready: Callable[[Session], None] | None = None,
    ):
        self.depot = depot
        self.visits = list(visits)
        self.policy = make_policy(policy) if isinstance(policy, str) else policy
        self.step_min = step_min
        # A fleet simulation shares its clock with the depot, so the environment can be passed in.
        self.env = env or simpy.Environment()
        self.on_ready = on_ready
        self.staff = simpy.Resource(self.env, capacity=depot.staff)
        self._visits_by_vehicle: dict[str, int] = {}
        self.bays = simpy.Resource(self.env, capacity=depot.cleaning_bays)
        self.free = {bank.kind: bank.count for bank in depot.chargers}
        self.power = PowerManager(depot)
        self.waiting: list[Session] = []
        self.charging: list[Session] = []
        self.sessions: list[Session] = []
        self._series: list[tuple[float, ...]] = []
        # Called with (session, kW delivered, kW the vehicle and charger could have taken) each power step.
        self.on_power: Callable[[Session, float, float], None] | None = None
        self._ready = 0
        self._started = False
        self._all_ready = self.env.event()

    @classmethod
    def from_scenario(cls, scenario: Scenario, policy: Policy | str | None = None, step_min: float = 1.0) -> DepotSim:
        """Build a simulator from a loaded scenario, optionally overriding its control rule."""
        return cls(scenario.depot, scenario.visits, policy or scenario.policy, step_min)

    def run(self) -> Result:
        """Run until every vehicle is ready, or give up three days after the last arrival."""
        self.start()
        if self.visits:
            # A depot that can never finish (no power, no chargers) must still return a result.
            horizon = max(v.arrive_min for v in self.visits) + 3 * DAY_MIN
            self.env.run(until=self._all_ready | self.env.timeout(horizon))
        return self.result()

    def start(self) -> None:
        """Schedule the known visits and start the power loop, without advancing the clock."""
        if self._started:
            return
        self._started = True
        for visit in self.visits:
            self._schedule(visit)
        self.env.process(self._power_loop())

    def add_visit(self, visit: Visit) -> None:
        """Add a visit while the simulation is running."""
        self.visits.append(visit)
        self._schedule(visit)

    def result(self) -> Result:
        """Return what has happened so far."""
        series = np.array(self._series) if self._series else np.zeros((0, len(SERIES_COLUMNS)))
        return Result(
            depot=self.depot, sessions=self.sessions, series=series, policy=getattr(self.policy, "name", "custom")
        )

    def _schedule(self, visit: Visit) -> None:
        self.env.process(self._visit(visit))

    def _visit(self, visit: Visit):
        yield self.env.timeout(max(0.0, visit.arrive_min - self.env.now))
        session = Session(visit=visit, soc=visit.soc_in)
        self.sessions.append(session)
        if session.energy_left_kwh > EPS_KWH:
            yield from self._charge(session)
        # A vehicle is cleaned on every Nth of its own visits, and inspected on every Mth; a short top-up
        # between the two skips the bay. Both are counted per vehicle: an inspection is due whether or not
        # that visit is also a cleaning one.
        count = self._visits_by_vehicle.get(visit.vehicle_id, 0) + 1
        self._visits_by_vehicle[visit.vehicle_id] = count
        clean = count % max(1, self.depot.clean_every) == 0
        inspect = bool(self.depot.inspect_every) and count % self.depot.inspect_every == 0
        if clean or inspect:
            session.cleaned = clean
            session.inspected = inspect
            minutes = (self.depot.clean_minutes if clean else 0.0) + (self.depot.inspect_minutes if inspect else 0.0)
            yield from self._bay(minutes)
        session.ready_min = self.env.now
        self._ready += 1
        if self.on_ready:
            self.on_ready(session)
        if self._ready == len(self.visits) and not self._all_ready.triggered:
            self._all_ready.succeed()

    def _charge(self, session: Session):
        session.assigned = self.env.event()
        self.waiting.append(session)
        self._match()
        yield session.assigned
        yield from self._with_staff(self.depot.plug_minutes)
        session.connected_min = self.env.now
        session.done = self.env.event()
        self.charging.append(session)
        yield session.done
        session.charged_min = self.env.now
        yield from self._with_staff(self.depot.plug_minutes)
        # The charger is free only once a person has unplugged the vehicle.
        self.free[session.charger_kind] += 1
        self._match()

    def _bay(self, minutes: float):
        with self.bays.request() as bay:
            yield bay
            yield from self._with_staff(minutes)

    def _with_staff(self, minutes: float):
        with self.staff.request() as person:
            yield person
            yield self.env.timeout(minutes)

    def _match(self) -> None:
        """Hand free chargers to waiting sessions, in the order the control rule sets."""
        for session in self.policy.queue_order(list(self.waiting), self.env.now):
            for kind in self.policy.bank_order(session, self.env.now):
                if self.free.get(kind, 0) > 0:
                    self.free[kind] -= 1
                    session.kind = kind
                    bank = self.depot.bank(kind)
                    assert (
                        bank is not None and session.assigned is not None
                    )  # a free charger has a bank; a waiting session has its event
                    session.charger_kw = bank.kw
                    session.assigned_min = self.env.now
                    self.waiting.remove(session)
                    session.assigned.succeed()
                    break

    def _power_loop(self):
        dt_hours = self.step_min / 60.0
        while True:
            delivered = self._deliver(dt_hours)
            step = self.power.settle(delivered, dt_hours)
            self._series.append(
                (
                    self.env.now,
                    step.grid_kw,
                    step.buffer_kw,
                    len(self.charging),
                    len(self.waiting),
                    self.power.buffer_kwh,
                )
            )
            yield self.env.timeout(self.step_min)
            for session in list(self.charging):
                if session.energy_left_kwh <= EPS_KWH or self._slot_over(session):
                    self.charging.remove(session)
                    assert session.done is not None  # set when the session was plugged in
                    session.done.succeed()

    def _slot_over(self, session: Session) -> bool:
        """Return whether a time-boxed session has used up its slot."""
        limit = session.visit.max_minutes
        return limit is not None and session.connected_min is not None and self.env.now - session.connected_min >= limit

    def _deliver(self, dt_hours: float) -> float:
        """Split this step's power between charging sessions and return the total delivered, in kW."""
        if not self.charging:
            return 0.0
        wants = {s.sid: s.want_kw(dt_hours) for s in self.charging}
        available = self.power.available_kw(dt_hours)
        grants = self.policy.allocate(self.charging, wants, available, self.env.now)
        total = 0.0
        for session in self.charging:
            # A control rule can be wrong; the site limit and the battery's limit cannot be exceeded.
            kw = max(0.0, min(grants.get(session.sid, 0.0), wants[session.sid], available - total))
            total += kw
            if self.on_power is not None:
                self.on_power(
                    session,
                    kw,
                    min(session.charger_kw, session.visit.model.accept_kw(session.soc, session.charger_kind)),
                )
            energy = kw * dt_hours
            session.energy_kwh += energy
            session.soc += energy / session.visit.model.capacity_kwh
        return total
