"""Power at the site: the grid connection, the battery buffer, and who gets how much.

The site can never draw more than the usable share of its connection. When vehicles want more than the grid gives, the buffer covers
the gap until it runs down; when they want less, the spare power refills the buffer.
"""

from __future__ import annotations

from dataclasses import dataclass

from depot_twin.resources import DepotConfig


def share_equally(wants: dict[str, float], available_kw: float) -> dict[str, float]:
    """Split power evenly, giving back what a vehicle cannot take to the others."""
    grants = dict.fromkeys(wants, 0.0)
    open_ids = [sid for sid, want in wants.items() if want > 0]
    left = available_kw
    while open_ids and left > 1e-9:
        share = left / len(open_ids)
        still_open = []
        for sid in open_ids:
            room = wants[sid] - grants[sid]
            give = min(share, room)
            grants[sid] += give
            left -= give
            if room - give > 1e-9:
                still_open.append(sid)
        if len(still_open) == len(open_ids):
            break
        open_ids = still_open
    return grants


def fill_in_order(wants: dict[str, float], available_kw: float, order: list[str]) -> dict[str, float]:
    """Give each vehicle all it can take, in the given order, until the power runs out."""
    grants = dict.fromkeys(wants, 0.0)
    left = available_kw
    for sid in order:
        give = min(wants[sid], left)
        grants[sid] = give
        left -= give
        if left <= 1e-9:
            break
    return grants


LIMIT_TOLERANCE_KW = 1e-6


class SiteLimitExceeded(RuntimeError):
    """More power was delivered in a step than the connection and the buffer can supply."""


@dataclass
class PowerStep:
    """What happened to power during one time step."""

    grid_kw: float
    buffer_kw: float  # positive when the buffer discharges, negative when it charges
    delivered_kw: float


class PowerManager:
    """Tracks the buffer and enforces the site limit, one time step at a time."""

    def __init__(self, depot: DepotConfig):
        self.depot = depot
        self.buffer_kwh = depot.buffer.energy_kwh if depot.buffer else 0.0

    def available_kw(self, dt_hours: float) -> float:
        """Return the power that can reach vehicles this step, after charger losses."""
        return (self.depot.usable_kw + self._buffer_out_kw(dt_hours)) * self.depot.charger_efficiency

    def _buffer_out_kw(self, dt_hours: float) -> float:
        buffer = self.depot.buffer
        if buffer is None:
            return 0.0
        usable = self.buffer_kwh - buffer.min_soc * buffer.energy_kwh
        return max(0.0, min(buffer.power_kw, usable / dt_hours))

    def settle(self, delivered_kw: float, dt_hours: float, refill: bool = True) -> PowerStep:
        """Account for one step in which vehicles received delivered_kw in total."""
        drawn = delivered_kw / self.depot.charger_efficiency
        grid = min(drawn, self.depot.usable_kw)
        from_buffer = drawn - grid
        buffer = self.depot.buffer
        # The site limit is enforced where power is handed out. If more was delivered than the connection
        # and the buffer could supply, the run is wrong and must not be recorded as if it had kept the limit.
        if from_buffer > self._buffer_out_kw(dt_hours) + LIMIT_TOLERANCE_KW:
            raise SiteLimitExceeded(
                f"{drawn:.1f} kW drawn against {self.depot.usable_kw:.1f} kW usable"
                + (f" and {self._buffer_out_kw(dt_hours):.1f} kW from the buffer" if buffer else "")
            )
        if buffer is None:
            return PowerStep(grid_kw=grid, buffer_kw=0.0, delivered_kw=delivered_kw)
        self.buffer_kwh -= from_buffer * dt_hours
        into_buffer = 0.0
        if refill and from_buffer <= 1e-9:
            room_kw = (buffer.energy_kwh - self.buffer_kwh) / (dt_hours * buffer.efficiency)
            into_buffer = max(0.0, min(self.depot.usable_kw - grid, buffer.power_kw, room_kw))
            self.buffer_kwh += into_buffer * dt_hours * buffer.efficiency
        return PowerStep(grid_kw=grid + into_buffer, buffer_kw=from_buffer - into_buffer, delivered_kw=delivered_kw)
