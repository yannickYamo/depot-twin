"""The heartbeat controller: the depot run as a steady pulse of short charging sessions.

A depot that fills every free charger at once works in surges: a bank of vehicles arrives together, charges
together and leaves together, and the grid draw, the staff and the road all feel the swing. This controller
replaces the surge with a beat.

- A session is a slot: a fixed amount of energy, one beat's worth at full rate. A vehicle is called only if
  it can take nearly a whole slot, and leaves when it has it. Development showed why the slot must be long
  and measured in energy. Every visit costs the road more than an hour whatever it delivers (the drive in,
  plugging, cleaning, the drive out), so many short top-ups lose more rides than they buy; and when the
  site is short of power, a slot measured in minutes sends vehicles away half fed.
- No more vehicles are plugged in than the site can feed at full rate, and those plugged in are fed in
  order. Sharing a shortage evenly keeps every vehicle off the road for longer.
- The chargers are worked in phases. Each tick only a fraction of them turn over, so a few vehicles arrive
  every few minutes instead of a bank every half hour. It is the same idea as interleaving the phases of a
  power converter to cancel ripple.
- How many vehicles each hour takes is not a threshold. Every hour a linear program plans the next day
  against the upper bound of the ride forecast: deep breaths in the troughs, shallow ones at the peak.
- The controller keeps a ledger. Each hour it commits a number of vehicles on the road, which is its plan
  less its own measured tendency to fall short, and the commitment is later checked against what happened.

Nothing here is trained. The learning is in what it is fed: the ride forecast and its bounds, and each
vehicle's energy use as identified from telemetry.
"""

from __future__ import annotations

import math
import time

import numpy as np
from ortools.linear_solver import pywraplp

from depot_twin.dispatch import lowest, must_come_in
from depot_twin.fleet import INBOUND, FleetState
from depot_twin.interfaces import EnergyEstimate, EnergyPrices
from depot_twin.ledger import PromiseLedger
from depot_twin.steering import expensive_window


class Heartbeat:
    """A recall rule that calls vehicles in for time-boxed slots, paced by an hourly plan."""

    name = "heartbeat"

    def __init__(
        self,
        beat_min: float = 60.0,
        top_soc: float = 0.85,
        call_below: float = 0.75,
        horizon: int = 24,
        energy: EnergyEstimate | None = None,
        ledger_days: int = 7,
        reserve_soc: float = 0.30,
        stored_value: float = 0.005,
        min_fill: float = 0.9,
        ledger_adapt: float = 0.0,
        ledger_level: float = 0.95,
        ledger_from_state: bool = False,
        prices: EnergyPrices | None = None,
        shift_peak: bool = True,
        pre_peak_hours: float = 3.0,
        peak_call_below: float = 0.18,
        price_in_program: bool = True,
    ):
        self.beat_min = beat_min
        self.top_soc = top_soc
        self.call_below = call_below
        self.horizon = horizon
        self.energy = energy  # an EnergyIdentifier; when absent the fleet's nominal figures are used
        self.ledger_days = ledger_days
        # The plan treats the fleet as one pool of energy, but vehicles are not one pool: when the average
        # sits at the floor, many are below it. So the plan is asked to hold a reserve and to charge
        # whenever vehicles and chargers are spare, not just in time.
        self.reserve_soc = reserve_soc
        self.stored_value = stored_value
        self.min_fill = min_fill  # a vehicle is called only if it can take at least this share of a slot
        # How fast the ledger's margin corrects itself. At zero the margin is the fixed percentile of last
        # week's shortfalls. Above zero, every broken promise widens it and every kept one narrows it a
        # little, at rates that balance when exactly one promise in twenty is broken.
        self.ledger_adapt = ledger_adapt
        # The share of promises the margin is built to keep. To be able to state 95% and mean it over a
        # single week, it has to be built for more than 95%: a week is only 168 promises.
        self.ledger_level = ledger_level
        self.ledger_from_state = ledger_from_state
        # An economics.Prices. When given, the plan weighs a ride's fare against what the energy for it
        # costs at each hour of the day, and so moves charging out of the expensive hours when it can.
        self.prices = prices
        self.shift_peak = shift_peak
        self.pre_peak_hours = pre_peak_hours
        self.peak_call_below = peak_call_below
        # With prices given, two things use them: the hourly program's objective, and the clock steering in
        # `_worth_calling`. This switch leaves the program blind to prices so a test can tell the two apart.
        self.price_in_program = price_in_program
        self._last_quota = 0.0
        self.calls = 0  # vehicles called in, and how many of those the floor forced rather than the plan chose
        self.forced_calls = 0
        # The hourly promise and its record are kept by the ledger; the controller only opens and closes hours.
        self.promises = PromiseLedger(days=ledger_days, level=ledger_level, adapt=ledger_adapt)
        self.tick_seconds: list[float] = []
        self._hour = -1
        self._quota = 0.0
        self._ticks_left = 1
        self.schedule: dict = {}  # the latest day plan in full, for viewers
        self.price_at = None  # optional: dollars per kWh by minute of the run, in place of the tariff's periods

    @property
    def ledger(self) -> list[dict]:
        """The record of hourly promises, oldest first."""
        return self.promises.entries

    @property
    def _open(self) -> dict | None:
        """The promise for the hour under way, for viewers that draw it."""
        return self.promises.open

    def slot_minutes(self, vehicle: int, state: FleetState) -> float:
        """Return the longest a session may last: three beats. A backstop, not the normal way a slot ends."""
        return 3.0 * self.beat_min

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Give the vehicle one slot's worth of energy, or as much of it as fits under the top.

        The slot is measured in energy, not minutes. With power to spare the two are the same thing. When
        the site is short, a slot measured in minutes would send vehicles away half fed; measured in
        energy, they wait their turn for power and then leave with what they came for.
        """
        return min(self.top_soc, float(state.soc[vehicle]) + self._slot_kwh(state) / float(state.capacity_kwh[vehicle]))

    def recall(self, state: FleetState) -> list[int]:
        """Call in this tick's share of the hour's plan, timed to arrive as chargers come free."""
        started = time.perf_counter()
        hour = int(state.now // 60)
        if hour != self._hour:
            self.promises.close()
            self._hour = hour
            self._plan(state)
        self.promises.observe(len(state.on_road))
        chargers = sum(bank.count for bank in state.depot.depot.chargers)
        phase = math.ceil(chargers * state.fleet.step_min / self.beat_min)
        share = math.ceil(self._quota / self._ticks_left) if self._quota > 0 else 0
        # A vehicle too low to stay out comes in whatever the plan says, and it takes a place like any other:
        # it counts against the chargers the site can feed and against the hour's quota. When the floor
        # fills every place the plan has none left to give, and `forced_calls` shows the plan was not in charge.
        forced = must_come_in(state)
        take = max(0, min(share, phase, self._free_on_arrival(state) - len(forced)))
        self._ticks_left = max(1, self._ticks_left - 1)
        wanted = lowest(state, take + len(forced), below=self._worth_calling(state))
        chosen = [vehicle for vehicle in wanted if vehicle not in set(forced)][:take]
        self._quota -= len(chosen) + len(forced)
        self.calls += len(chosen) + len(forced)
        self.forced_calls += len(forced)
        self.tick_seconds.append(time.perf_counter() - started)
        return sorted(set(forced) | set(chosen))

    def _worth_calling(self, state: FleetState) -> float:
        """Return the charge level under which a vehicle can use a whole slot.

        A visit costs over an hour off the road whatever it delivers. A vehicle that would hit the top
        ten minutes into its slot is not worth that hour, so only vehicles with room for at least a set
        share of a slot's energy are called.
        """
        room = self._slot_kwh(state) / float(state.capacity_kwh.mean())
        level = min(self.call_below, self.top_soc - self.min_fill * room)
        if self.prices is None or not self.shift_peak:
            return level
        # With prices known, charging is steered around the expensive hours at the level of the vehicle.
        # In the hours before an expensive stretch, also call vehicles that would otherwise run down during
        # it; during it, call only those that cannot wait.
        expensive_now, hours_to_next, stretch = self._expensive(state.now)
        if expensive_now:
            return min(level, self.peak_call_below)
        if hours_to_next is not None and hours_to_next <= self.pre_peak_hours:
            drive, always_on = self._energy_figures(state)
            burn = (always_on + state.fleet.idle_mph * drive) + state.rides_per_vehicle_hour * 0.5 * (
                state.fleet.miles_to_pickup + state.fleet.miles_with_passenger
            ) * drive
            through_peak = stretch * burn / float(state.capacity_kwh.mean())
            return min(self.call_below, level + through_peak)
        return level

    def _expensive(self, now: float) -> tuple[bool, float | None, float]:
        """Whether this hour is expensive, the hours until the next expensive stretch, and its length (`steering`)."""
        return expensive_window(now, self.price_at, self.horizon)

    def _slot_kwh(self, state: FleetState) -> float:
        """Return the energy one slot delivers at full rate. A property of the depot, not of the fleet's state."""
        site = state.depot.depot
        slot_hours = (self.beat_min - 2.0 * site.plug_minutes) / 60.0
        return max(bank.kw for bank in site.chargers) * slot_hours

    def _free_on_arrival(self, state: FleetState) -> int:
        """Return the chargers that will be free when a vehicle called now pulls in."""
        depot = state.depot
        arrive = state.now + state.fleet.depot_leg_minutes
        ending = 0
        for session in depot.charging:
            # At full rate, this is when the session will have its energy and the charger will be unplugged.
            minutes_left = 60.0 * session.energy_left_kwh / max(session.charger_kw, 1.0) + depot.depot.plug_minutes
            if state.now + minutes_left <= arrive:
                ending += 1
        spoken_for = int((state.status == INBOUND).sum()) + len(depot.waiting)
        free = sum(depot.free.values()) + ending - spoken_for
        # Never plug in more vehicles than the site can feed at full rate. Past that point every extra
        # vehicle only slows the others down, and each one is a vehicle off the road for a trickle.
        site = depot.depot
        # What the site can deliver right now includes the battery while it has charge to give.
        feedable = int(depot.power.available_kw(depot.step_min / 60.0) / max(bank.kw for bank in site.chargers))
        in_use = len(depot.charging) - ending + spoken_for
        return min(free, feedable - in_use)

    def _energy_figures(self, state: FleetState) -> tuple[float, float]:
        """Return the fleet's mean driving energy (kWh per mile) and always-on load (kW), as best known."""
        if self.energy is not None:
            return float(np.mean(self.energy.drive_kwh_per_mile)), float(np.mean(self.energy.always_on_kw))
        fleet = state.fleet
        weights = np.array(fleet.mix) / sum(fleet.mix)
        drive = [m.drive_kwh_per_mile if m.drive_kwh_per_mile is not None else fleet.kwh_per_mile for m in fleet.models]
        load = [m.always_on_kw if m.always_on_kw is not None else fleet.idle_kw for m in fleet.models]
        return float(np.dot(weights, drive)), float(np.dot(weights, load))

    def _visit(self, state: FleetState) -> tuple[float, float, float]:
        """Return what one visit costs and gives: hours off the road, kWh gained, and visits per hour possible.

        A visit is far longer than its charging slot: the drive in, plugging, the slot, unplugging,
        cleaning, and the drive back out. The road loses the vehicle for all of it; the charger only for
        the slot. Treating the two as the same thing is what makes a plan under-use its chargers.
        """
        fleet, site = state.fleet, state.depot.depot
        slot_hours = (self.beat_min - 2.0 * site.plug_minutes) / 60.0
        charger_kw = max(bank.kw for bank in site.chargers)
        chargers = sum(bank.count for bank in site.chargers)
        cap = float(state.capacity_kwh.mean())
        on_road = state.on_road
        tail = max(1, fleet.size // 10)
        soc_in = float(np.sort(state.soc[on_road])[:tail].mean()) if len(on_road) else 0.2
        gained = max(5.0, min(charger_kw * slot_hours, (self.top_soc - soc_in) * cap))
        away_hours = (2.0 * fleet.depot_leg_minutes + self.beat_min + site.clean_minutes) / 60.0
        by_chargers = chargers * 60.0 / self.beat_min
        by_power = site.usable_kw * site.charger_efficiency / gained
        return away_hours, gained, min(by_chargers, by_power)

    def _plan(self, state: FleetState) -> None:
        """Solve the day plan, set this hour's quota, and enter this hour's commitment in the ledger."""
        fleet = state.fleet
        away_hours, gained, max_visits = self._visit(state)
        drive, always_on = self._energy_figures(state)
        cap = float(state.capacity_kwh.mean())
        eligible = int((state.soc[state.on_road] < self._worth_calling(state)).sum())
        self._quota, planned = solve_beat_plan(
            size=fleet.size,
            demand=state.demand_upper_hours,  # the level demand should stay under, not the level expected
            rate=state.rides_per_vehicle_hour,
            away_hours=away_hours,
            max_visits=max_visits,
            eligible_now=eligible,
            gained_kwh=gained - 2.0 * fleet.depot_leg_miles * drive,  # less the energy spent driving in and out
            ride_kwh=(fleet.miles_to_pickup + fleet.miles_with_passenger) * drive,
            idle_kwh=always_on + fleet.idle_mph * drive,
            energy_now=float((state.soc * state.capacity_kwh).sum()),
            energy_full=self.top_soc * cap * fleet.size,
            energy_reserve=self.reserve_soc * cap * fleet.size,
            stored_value=self.stored_value,
            horizon=self.horizon,
            schedule=self.schedule,
            **self._money(state),
        )
        self._ticks_left = max(1, round(60.0 / fleet.step_min))
        if self.ledger_from_state:
            # What the depot can promise for the coming hour starts from what is on the road now, moved by
            # how many more or fewer vehicles the plan calls in than it did last hour. The plan's own
            # steady-state figure ignores vehicles already on their way in or out.
            planned = len(state.on_road) - away_hours * (self._quota - self._last_quota)
        self._last_quota = self._quota
        self.promises.commit(self._hour, planned, fleet.size)

    def _money(self, state: FleetState) -> dict:
        """Return the fare and the hourly price of a visit's energy, or nothing when the plan ignores money."""
        if self.prices is None or not self.price_in_program:
            return {}
        from depot_twin.economics import tariff_period

        site = state.depot.depot
        by_period = {
            "peak": self.prices.energy_peak,
            "off_peak": self.prices.energy_off_peak,
            "super_off_peak": self.prices.energy_super_off_peak,
        }
        hour_now = int(state.now // 60)
        # A price curve by the minute (a day-ahead market, say) replaces the tariff's three periods in the
        # hourly program. The steering before and during the evening peak stays on the tariff's clock.
        price = [
            (self.price_at((hour_now + k) * 60.0) if self.price_at else by_period[tariff_period((hour_now + k) * 60.0)])
            for k in range(self.horizon)
        ]
        # A visit's energy as the grid sees it: the whole slot, before charger losses.
        return {
            "fare": self.prices.revenue_per_ride,
            "visit_cost": [p * self._slot_kwh(state) / site.charger_efficiency for p in price],
        }


def solve_beat_plan(
    *,
    size: int,
    demand: np.ndarray,
    rate: float,
    away_hours: float,
    max_visits: float,
    eligible_now: int,
    gained_kwh: float,
    ride_kwh: float,
    idle_kwh: float,
    energy_now: float,
    energy_full: float,
    energy_reserve: float,
    stored_value: float,
    horizon: int = 24,
    fare: float = 1.0,
    visit_cost: list[float] | None = None,
    schedule: dict | None = None,
) -> tuple[float, float]:
    """Plan visits per hour for the next day. Returns this hour's visits and the vehicles it leaves on the road.

    The fleet is treated as one pool of energy and one pool of vehicles. Each hour, every visit takes a
    vehicle off the road for away_hours and adds gained_kwh to the pool. Rides served are limited by the
    demand and by the vehicles left on the road. The plan maximizes rides served, values energy in hand a
    little (so it charges when vehicles are spare, never at the cost of a ride), and pays for dipping
    under the reserve.

    With fare and visit_cost given, the objective is in money: fares earned less what each hour's visits
    cost in energy at that hour's price. The plan then also chooses when to charge, not only how much.

    When a dict is passed as schedule, the whole plan is written into it: visits, vehicles on the road,
    rides served and energy in hand for each hour of the horizon. A viewer can then show the plan as it
    stood each hour, and how it was redrawn the next.
    """
    solver = pywraplp.Solver.CreateSolver("GLOP")
    inf = solver.infinity()
    hours = range(horizon)
    # No more visits than keep at least one vehicle in ten on the road, whatever the energy says.
    most = min(max_visits, 0.9 * size / away_hours)
    visits = [solver.NumVar(0, most, f"visits{t}") for t in hours]
    visits[0].SetUb(min(most, float(eligible_now)))  # this hour, only vehicles with room for a full slot
    served = [solver.NumVar(0, float(demand[t % len(demand)]), f"served{t}") for t in hours]
    energy = [solver.NumVar(-inf, energy_full, f"energy{t}") for t in hours]
    short = [solver.NumVar(0, inf, f"short{t}") for t in hours]
    previous = min(energy_now, energy_full)
    for t in hours:
        on_road = size - away_hours * visits[t]
        solver.Add(served[t] <= rate * on_road)
        solver.Add(energy[t] == previous - ride_kwh * served[t] - idle_kwh * on_road + gained_kwh * visits[t])
        solver.Add(short[t] >= energy_reserve - energy[t])
        previous = energy[t]
    kwh_per_ride = max(ride_kwh + idle_kwh / rate, 1e-9)
    held = stored_value / kwh_per_ride * sum(energy)
    spent = sum(visit_cost[t] * visits[t] for t in hours) if visit_cost else 0.0
    solver.Maximize(fare * (sum(served) - 0.05 / kwh_per_ride * sum(short) + held) - spent)
    if solver.Solve() not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return 0.0, float(size)
    now = float(visits[0].solution_value())
    if schedule is not None:
        schedule.update(
            visits=[round(v.solution_value(), 2) for v in visits],
            on_road=[round(size - away_hours * v.solution_value(), 1) for v in visits],
            served=[round(v.solution_value(), 1) for v in served],
            energy_kwh=[round(v.solution_value()) for v in energy],
        )
    return now, size - away_hours * now
