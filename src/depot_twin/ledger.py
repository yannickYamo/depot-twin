"""The depot's hourly promise, and the record of whether it was kept.

Each hour the plan says how many vehicles it will have on the road. The promise is that figure less a
margin, and the margin is learned from the plan's own record: how far it has tended to overstate. The
ledger holds the record, sizes the margin, and corrects it when promises break. It knows nothing about
charging or prices, which is why it lives apart from the controller that uses it.
"""

from __future__ import annotations

import math

import numpy as np


class PromiseLedger:
    """One entry per hour: what was planned, what was committed, what came, and whether the promise held."""

    def __init__(self, days: int = 7, level: float = 0.95, adapt: float = 0.0):
        self.days = days  # how much history sizes the margin
        # The share of promises the margin is built to keep. To state 95% and mean it over a single week
        # it has to be built for more: a week is only 168 promises.
        self.level = level
        # How fast the margin corrects itself. At zero it is the fixed percentile of recent shortfalls.
        # Above zero every broken promise widens it and every kept one narrows it a little, at rates that
        # balance when exactly the allowed share is broken.
        self.adapt = adapt
        self.entries: list[dict] = []
        self.open: dict | None = None
        self._scale = 1.0
        self._on_road_sum = 0.0
        self._ticks_seen = 0

    def observe(self, on_road: int) -> None:
        """Count one tick's vehicles on the road towards the open hour's outcome."""
        self._on_road_sum += on_road
        self._ticks_seen += 1

    def margin(self, fleet_size: int) -> float:
        """How far the plan has tended to overstate vehicles on the road, at the level the promise is built for."""
        recent = self.entries[-24 * self.days :]
        if len(recent) < 24:
            return 0.05 * fleet_size  # until a day of history exists, hold back a flat 5% of the fleet
        base = float(max(0.0, np.quantile([entry["planned"] - entry["actual"] for entry in recent], self.level)))
        # A week with no shortfall gives no margin to scale; fall back on a sliver of the fleet.
        return self._scale * max(base, 0.005 * fleet_size)

    def commit(self, hour: int, planned: float, fleet_size: int) -> float:
        """Open the hour's promise: the planned figure less the margin. Returns what was committed."""
        committed = max(0.0, planned - self.margin(fleet_size))
        self.open = {"hour": hour, "planned": planned, "committed": committed}
        return committed

    def close(self) -> None:
        """Record what the hour just ended delivered against what was committed, and correct the margin."""
        if self.open is not None and self._ticks_seen:
            self.open["actual"] = self._on_road_sum / self._ticks_seen
            self.open["kept"] = self.open["actual"] >= self.open["committed"]
            self.entries.append(self.open)
            missed = 0.0 if self.open["kept"] else 1.0
            self._scale *= math.exp(self.adapt * (missed - (1.0 - self.level)))
        self._on_road_sum, self._ticks_seen, self.open = 0.0, 0, None
