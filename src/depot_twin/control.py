"""Control rules: which waiting vehicle gets the next charger, and how shared power is split.

A rule sees the sessions and the clock and nothing else, so rules can be swapped without touching the
simulator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from depot_twin.grid import fill_in_order, share_equally

if TYPE_CHECKING:
    from depot_twin.sim import Session


class Policy(Protocol):
    """What the simulator asks of a control rule."""

    def queue_order(self, waiting: list[Session], now: float) -> list[Session]:
        """Return waiting sessions, most urgent first."""
        ...

    def bank_order(self, session: Session, now: float) -> list[str]:
        """Return charger kinds to try for this session, best first."""
        ...

    def allocate(
        self, charging: list[Session], wants: dict[str, float], available_kw: float, now: float
    ) -> dict[str, float]:
        """Return the power each charging session receives this step."""
        ...


def slack_minutes(session: Session, now: float, kw: float | None = None) -> float:
    """Return the spare time a session has: time until it is due, less the time it still needs to charge."""
    visit = session.visit
    if visit.due_min is None:
        return float("inf")
    rate = kw or session.charger_kw or visit.model.max_dc_kw
    need_min = 60.0 * session.energy_left_kwh / max(rate, 1e-9)
    return visit.due_min - now - need_min


class Fifo:
    """First come, first served; fast chargers first; power split evenly."""

    name = "fifo"

    def queue_order(self, waiting: list[Session], now: float) -> list[Session]:
        """Serve in order of arrival."""
        return sorted(waiting, key=lambda s: s.visit.arrive_min)

    def bank_order(self, session: Session, now: float) -> list[str]:
        """Take a fast charger when one is free."""
        return ["dc", "ac"]

    def allocate(
        self, charging: list[Session], wants: dict[str, float], available_kw: float, now: float
    ) -> dict[str, float]:
        """Split power evenly."""
        return share_equally(wants, available_kw)


class NeedFirst:
    """Charge the vehicles that need it most.

    The vehicle with the least spare time goes first in the queue and first in line for power. A vehicle
    that a slow charger can finish on time is sent to one, which keeps fast chargers for the vehicles that
    cannot wait.
    """

    name = "need_first"

    def __init__(self, ac_margin_min: float = 15.0):
        self.ac_margin_min = ac_margin_min

    def queue_order(self, waiting: list[Session], now: float) -> list[Session]:
        """Serve the session with the least slack first."""
        return sorted(waiting, key=lambda s: self._urgency(s, now))

    def bank_order(self, session: Session, now: float) -> list[str]:
        """Prefer a slow charger when it still finishes on time."""
        if session.visit.due_min is None:
            # A vehicle with no deadline earns nothing while it sits here, so it gets the fastest charger.
            return ["dc", "ac"]
        ac_kw = session.visit.model.max_ac_kw
        if slack_minutes(session, now, kw=ac_kw) >= self.ac_margin_min:
            return ["ac", "dc"]
        return ["dc", "ac"]

    def allocate(
        self, charging: list[Session], wants: dict[str, float], available_kw: float, now: float
    ) -> dict[str, float]:
        """Feed sessions in order of slack, least first."""
        order = [s.sid for s in sorted(charging, key=lambda s: self._urgency(s, now))]
        return fill_in_order(wants, available_kw, order)

    @staticmethod
    def _urgency(session: Session, now: float) -> tuple[float, float, float]:
        # Deadlines first; among vehicles with none, the emptiest battery; then order of arrival.
        return (slack_minutes(session, now), session.soc, session.visit.arrive_min)


class SlotPower:
    """Power for slot charging: full rate, in order of plugging in.

    When the site can feed every plugged vehicle, each gets all it can take. When it cannot, the vehicles
    that plugged in first are fed at full rate and the rest wait their turn. Sharing the shortage evenly
    looks fairer and is worse: every vehicle then crawls, and all of them are off the road for longer.
    Finishing vehicles one after another at full rate returns the first of them to service sooner and
    delays none of the others' finish by more than the sharing would have.
    """

    name = "slot_power"

    def queue_order(self, waiting: list[Session], now: float) -> list[Session]:
        """Serve in order of arrival; slots are handed out before vehicles arrive."""
        return sorted(waiting, key=lambda s: s.visit.arrive_min)

    def bank_order(self, session: Session, now: float) -> list[str]:
        """Slot charging belongs on fast chargers."""
        return ["dc", "ac"]

    def allocate(
        self, charging: list[Session], wants: dict[str, float], available_kw: float, now: float
    ) -> dict[str, float]:
        """Feed vehicles at full rate in the order they plugged in."""
        order = [s.sid for s in sorted(charging, key=lambda s: (s.connected_min or 0.0, s.visit.arrive_min))]
        return fill_in_order(wants, available_kw, order)


class LeastLeft(SlotPower):
    """Full rate to the vehicle with the least energy still to take.

    Scheduling theory's answer to "which job first" when the aim is the lowest average time in the system:
    the one with the least work remaining. Here that is the vehicle closest to its target. It is the mirror
    image of feeding the emptiest first. Vehicles still take chargers in order of arrival; only the power
    is shared this way.
    """

    name = "least_left"

    def allocate(
        self, charging: list[Session], wants: dict[str, float], available_kw: float, now: float
    ) -> dict[str, float]:
        """Feed vehicles at full rate, the one nearest its target first."""
        order = [s.sid for s in sorted(charging, key=lambda s: (s.energy_left_kwh, s.connected_min or 0.0))]
        return fill_in_order(wants, available_kw, order)


POLICIES = {"fifo": Fifo, "need_first": NeedFirst, "slot_power": SlotPower, "least_left": LeastLeft}


def make_policy(name: str) -> Policy:
    """Build a control rule by name."""
    return POLICIES[name]()
