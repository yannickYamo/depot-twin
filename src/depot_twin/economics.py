"""What a day at the depot earns and costs.

Revenue is rides served. Costs are the ones the depot's design decides: energy by time of day, the capacity
subscription, chargers, the battery, the people and the land. Vehicles, insurance and remote assistance are
left out because they do not change with how the depot is built; the result is the depot's contribution,
not the service's profit.

Every price is a public figure or a stated assumption, listed with its source in docs/SITE.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from depot_twin.resources import DAY_MIN, DepotConfig


@dataclass(frozen=True)
class Prices:
    """Prices in dollars. Defaults are for the East Oakland site in 2026."""

    revenue_per_ride: float = 19.69  # average Bay Area fare in a published price survey
    energy_peak: float = 0.36003  # PG&E BEV-2-P, 4 pm to 9 pm
    energy_off_peak: float = 0.15115  # 9 pm to 9 am and 2 pm to 4 pm
    energy_super_off_peak: float = 0.12849  # 9 am to 2 pm
    subscription_per_50kw_month: float = 85.98
    dc_charger_fixed: float = 40_000.0  # installed cost of a fast charger: fixed part
    dc_charger_per_kw: float = 500.0  # and the part that grows with its power
    ac_charger: float = 8_000.0  # installed cost of a slow charger
    charger_life_years: float = 10.0
    buffer_per_kwh: float = 400.0  # installed cost of stationary battery
    buffer_life_years: float = 10.0
    staff_hour: float = 40.0  # loaded cost of one person on site
    land_month: float = 217_500.0  # 14.5 acres of industrial yard


def tariff_period(minute: float) -> str:
    """Return the time-of-use period a minute of the day falls in."""
    hour = (minute % DAY_MIN) / 60.0
    if 16 <= hour < 21:
        return "peak"
    if 9 <= hour < 14:
        return "super_off_peak"
    return "off_peak"


def energy_by_period(series: np.ndarray, skip_days: float = 0.0) -> dict[str, float]:
    """Return grid energy in kWh per tariff period, from a depot's power series."""
    rows = series[series[:, 0] >= skip_days * DAY_MIN]
    if len(rows) < 2:
        return {"peak": 0.0, "off_peak": 0.0, "super_off_peak": 0.0}
    step_hours = (rows[1, 0] - rows[0, 0]) / 60.0
    hours = (rows[:, 0] % DAY_MIN) / 60.0
    peak = (hours >= 16) & (hours < 21)
    super_off = (hours >= 9) & (hours < 14)
    return {
        "peak": float(rows[peak, 1].sum() * step_hours),
        "off_peak": float(rows[~peak & ~super_off, 1].sum() * step_hours),
        "super_off_peak": float(rows[super_off, 1].sum() * step_hours),
    }


def fixed_cost_per_day(depot: DepotConfig, prices: Prices) -> dict[str, float]:
    """Return the daily cost of what the depot owns and employs, whatever the fleet does."""
    chargers = 0.0
    for bank in depot.chargers:
        each = prices.ac_charger if bank.kind == "ac" else prices.dc_charger_fixed + prices.dc_charger_per_kw * bank.kw
        chargers += bank.count * each / (prices.charger_life_years * 365.0)
    buffer = (
        depot.buffer.energy_kwh * prices.buffer_per_kwh / (prices.buffer_life_years * 365.0) if depot.buffer else 0.0
    )
    return {
        "chargers": chargers,
        "buffer": buffer,
        "staff": depot.staff * 24.0 * prices.staff_hour,
        "land": prices.land_month * 12.0 / 365.0,
    }


def daily_contribution(
    depot: DepotConfig,
    rides_per_day: float,
    energy_kwh_per_day: dict[str, float],
    peak_kw: float,
    prices: Prices | None = None,
) -> dict[str, float]:
    """Return the depot's revenue, costs and contribution for an average day."""
    prices = prices or Prices()
    energy = (
        energy_kwh_per_day["peak"] * prices.energy_peak
        + energy_kwh_per_day["off_peak"] * prices.energy_off_peak
        + energy_kwh_per_day["super_off_peak"] * prices.energy_super_off_peak
    )
    # The subscription is bought in 50 kW blocks to cover the highest draw of the month.
    subscription = math.ceil(peak_kw / 50.0) * prices.subscription_per_50kw_month * 12.0 / 365.0
    fixed = fixed_cost_per_day(depot, prices)
    revenue = rides_per_day * prices.revenue_per_ride
    cost = energy + subscription + sum(fixed.values())
    return {"revenue": revenue, "energy": energy, "subscription": subscription, **fixed, "contribution": revenue - cost}
