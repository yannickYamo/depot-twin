"""Back-of-envelope depot sizing.

This is the arithmetic a planner does before any simulation: how fast must each vehicle charge, how many
chargers one power source can feed, how many groups of chargers a wave of vehicles needs, and how many
battery buffers cover the day. The simulator is checked against these numbers on simple cases, then used
where the arithmetic stops working: mixed arrivals, queues, tapering and shared power.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def required_rate_kw(capacity_kwh: float, soc_in: float, soc_out: float, dwell_hours: float) -> float:
    """Return the constant power that takes a battery from soc_in to soc_out within the dwell."""
    return capacity_kwh * max(0.0, soc_out - soc_in) / dwell_hours


def min_arrival_soc(capacity_kwh: float, soc_out: float, charger_kw: float, dwell_hours: float) -> float:
    """Return the lowest arrival state of charge a charger of this power can still recover in the dwell."""
    return max(0.0, soc_out - charger_kw * dwell_hours / capacity_kwh)


def split_dwell(energy_kwh: float, dwell_hours: float, fast_kw: float, slow_kw: float) -> tuple[float, float]:
    """Split a dwell between a fast and a slow charger so the energy is just delivered.

    Returns (hours on fast, hours on slow). A vehicle that the slow charger alone can serve gets no fast
    time; one that even the fast charger cannot serve gets the whole dwell on fast.
    """
    if slow_kw * dwell_hours >= energy_kwh:
        return 0.0, energy_kwh / slow_kw
    if fast_kw * dwell_hours <= energy_kwh:
        return dwell_hours, 0.0
    fast_hours = (energy_kwh - slow_kw * dwell_hours) / (fast_kw - slow_kw)
    return fast_hours, dwell_hours - fast_hours


def chargers_per_source(source_kw: float, charger_kw: float) -> int:
    """Return how many chargers one power source feeds at full rate."""
    return int(source_kw // charger_kw)


def groups_needed(vehicles: int, chargers_per_group: int) -> int:
    """Return how many charger groups a wave of vehicles needs when all charge at once."""
    return math.ceil(vehicles / chargers_per_group)


def waves_per_buffer(buffer_kwh: float, group_kw: float, charge_hours: float) -> int:
    """Return how many full waves one battery buffer feeds before it must recharge."""
    return int(buffer_kwh // (group_kw * charge_hours))


def daily_energy_kwh(vehicles: int, miles_per_day: float, kwh_per_mile: float, efficiency: float = 1.0) -> float:
    """Return the energy the site must draw each day to keep the fleet driving."""
    return vehicles * miles_per_day * kwh_per_mile / efficiency


def buffers_needed(
    energy_kwh: float, usable_kwh_per_buffer: float, cycles_per_day: float = 1.0, spares: int = 0
) -> int:
    """Return the number of battery buffers that carry this much energy a day, plus spares."""
    return math.ceil(energy_kwh / (usable_kwh_per_buffer * cycles_per_day)) + spares


@dataclass(frozen=True)
class WavePlan:
    """The hand answer for one wave of identical vehicles."""

    rate_kw: float
    chargers: int
    site_kw: float
    energy_kwh: float


def plan_wave(
    vehicles: int, capacity_kwh: float, soc_in: float, soc_out: float, dwell_hours: float, charger_kw: float
) -> WavePlan:
    """Size one wave: every vehicle on its own charger, all drawing the rate they need.

    Raises ValueError when the charger is too small for the dwell, because no charger count fixes that.
    """
    rate = required_rate_kw(capacity_kwh, soc_in, soc_out, dwell_hours)
    if rate > charger_kw:
        raise ValueError(f"needs {rate:.1f} kW per vehicle, charger gives {charger_kw:.1f} kW")
    energy = vehicles * capacity_kwh * (soc_out - soc_in)
    return WavePlan(rate_kw=rate, chargers=vehicles, site_kw=vehicles * rate, energy_kwh=energy)
