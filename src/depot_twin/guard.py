"""A guard around the controller: watch what it relies on, and fall back when that breaks.

The heartbeat controller plans against the upper bound of the ride forecast. If the forecast goes wrong (a
feed that stalls, a model that has drifted, an event nobody modelled), the controller will plan for a quiet
day on a busy one and call vehicles in when the road needs them. Nothing in the controller can notice,
because it trusts the bound.

The guard checks the one thing the bound claims: that rides stay under it about 95% of the time. Each hour
it compares the rides that were actually offered with the bound it was given an hour before. If the bound
is being broken far more often than it should be, the guard hands control to a rule that uses no forecast,
and hands it back only after the bound has held again for a while.

The same wrapper is how a new controller is introduced. Run with the incumbent in control and the newcomer
shadowing, the newcomer is asked every tick what it would do and its answers are recorded, not acted on.
"""

from __future__ import annotations

from depot_twin.fleet import FleetState


class Guarded:
    """Runs a primary recall rule, monitors the forecast bound it depends on, and falls back when it fails."""

    name = "guarded"

    def __init__(
        self,
        primary,
        fallback,
        window_hours: int = 12,
        trip_share: float = 0.5,
        hold_hours: int = 24,
        shadow_only: bool = False,
    ):
        self.primary = primary
        self.fallback = fallback
        self.window_hours = window_hours
        self.trip_share = trip_share  # the bound is meant to break 5% of the time; half the time is a failure
        self.hold_hours = hold_hours
        self.shadow_only = shadow_only  # the primary never acts; it only records what it would have done
        self.active = fallback if shadow_only else primary
        self.events: list[dict] = []
        self.breaks: list[bool] = []
        self.shadow_calls: list[int] = []
        self._hour = -1
        self._bound_given: float | None = None
        self._tripped_at: int | None = None

    def recall(self, state: FleetState) -> list[int]:
        """Let the active rule decide; keep the other informed; check the forecast bound on the hour."""
        hour = int(state.now // 60)
        if hour != self._hour:
            self._check(hour, state)
            self._hour = hour
            self._bound_given = float(state.demand_upper_hours[0])
        # Both rules see every tick, so whichever is not in control has current state when it takes over.
        primary_choice = self.primary.recall(state)
        fallback_choice = self.fallback.recall(state)
        if self.active is self.primary:
            return primary_choice
        self.shadow_calls.append(len(primary_choice))
        return fallback_choice

    def target_soc(self, vehicle: int, state: FleetState) -> float:
        """Return the active rule's release level."""
        return self.active.target_soc(vehicle, state)

    def slot_minutes(self, vehicle: int, state: FleetState) -> float | None:
        """Return the active rule's session limit, if it has one."""
        limit = getattr(self.active, "slot_minutes", None)
        return limit(vehicle, state) if limit else None

    def _check(self, hour: int, state: FleetState) -> None:
        """Record whether last hour's rides broke the bound given for it, and trip or restore on the trend."""
        if self._bound_given is not None:
            self.breaks.append(state.offered_last_hour > self._bound_given)
        if self.shadow_only or len(self.breaks) < self.window_hours:
            return
        share = sum(self.breaks[-self.window_hours :]) / self.window_hours
        if self._tripped_at is None and share >= self.trip_share:
            self._tripped_at = hour
            self.active = self.fallback
            self.events.append({"hour": hour, "event": "fell back", "bound_broken_share": round(share, 3)})
        elif (
            self._tripped_at is not None and hour - self._tripped_at >= self.hold_hours and share <= self.trip_share / 2
        ):
            self._tripped_at = None
            self.active = self.primary
            self.events.append({"hour": hour, "event": "restored", "bound_broken_share": round(share, 3)})
