"""The account: one depot design and one way of running it, turned into money the way an operator counts it.

An operator counts per vehicle-day and per ride, because vehicles and rides are what scale. So the account
gives every line two ways: the site's day, and each vehicle's day. What goes in:

- revenue: each served ride at the price of its step, from a price model built the way the service builds
  its prices (base, distance, time, busy pricing) and levelled on the published average fare (`fares.py`);
- energy, three ways: the tariff the site pays (the base case); and two scenarios for an operator whose
  supply contract passes wholesale prices through, settled day-ahead or in real time, plus a delivery
  charge that is an assumption;
- the capacity subscription, chargers, storage, the grid connection, land and people, as in the cost
  model, annualized straight-line;
- vehicles, at a cost per vehicle-year, and running them outside the depot at a cost per vehicle-day: both
  parameters, because no public figure exists and none is claimed;
- a cost for each ride lost beyond its fare, so that reliability has a price and a design that drops
  rides is not simply the cheaper one: a parameter;
- the reserve the forecast asks the fleet to hold, as information: its value depends on whether vehicles
  bind, and the account says so rather than booking it.

Nothing here changes the simulation. It reads a finished run.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from depot_twin.economics import Prices, energy_by_period, fixed_cost_per_day
from depot_twin.fares import PriceModel
from depot_twin.resources import DepotConfig

STEP_HOURS = 5.0 / 60.0


@dataclass(frozen=True)
class Assumptions:
    """Figures the account needs that the cost model does not carry. Each is labelled where it is shown."""

    vehicle_cost_per_year: float = 60_000.0  # parameter, no public source; the page runs it from 30,000 to 100,000
    # Running a vehicle outside the depot: maintenance, insurance, remote assistance, support, cleaning
    # supplies, software. A parameter with no public source; it scales with the fleet, so it moves the sweet spot.
    operations_per_vehicle_day: float = 100.0
    connection_per_kw: float = 200.0  # assumed: a service upgrade, inside published ranges for fleet depots
    connection_life_years: float = 20.0  # assumed
    delivery_adder_usd_per_kwh: float = 0.08  # assumed: delivery and non-bypassable charges on a pass-through contract
    required_service: float = 0.99  # share of rides served a design must reach to count
    # What a lost ride costs beyond its fare: the rider who does not come back, the refund, the regulator's
    # eye. A parameter with no public source, set at about one fare; the page runs it from nothing to three.
    lost_ride_cost: float = 20.0
    pricing: PriceModel = PriceModel()  # what a ride pays, by how busy the fleet is at the time

    def describe(self) -> dict:
        """The figures as plain values, for the record."""
        return {**{k: v for k, v in self.__dict__.items() if k != "pricing"}, "pricing": self.pricing.describe()}


PriceCurve = Callable[[float], float]  # minute of the run -> dollars per kWh


def energy_cost(series: np.ndarray, price_at: PriceCurve, skip_days: int) -> float:
    """Energy cost over the scored days at a price that varies by the minute.

    The power series has one row per power step, whatever its length; the step is read from the rows.
    """
    rows = series[series[:, 0] >= skip_days * 1440.0]
    step_hours = float(np.median(np.diff(rows[:, 0]))) / 60.0 if len(rows) > 1 else STEP_HOURS
    return float(sum(row[1] * step_hours * price_at(row[0]) for row in rows))


def tariff_curve(prices: Prices) -> PriceCurve:
    """The tariff as a price curve, for comparison with the wholesale scenarios on the same footing."""
    from depot_twin.economics import tariff_period

    by_period = {
        "peak": prices.energy_peak,
        "off_peak": prices.energy_off_peak,
        "super_off_peak": prices.energy_super_off_peak,
    }
    return lambda minute: by_period[tariff_period(minute)]


def wholesale_curve(usd_per_mwh: list[float], step_minutes: int, adder: float) -> PriceCurve:
    """A wholesale price series, by hour or by five minutes from the run's first minute, plus delivery."""
    values = np.array(usd_per_mwh, dtype=float)
    filled = np.where(np.isnan(values), np.nanmean(values), values)

    def price(minute: float) -> float:
        k = min(int(minute // step_minutes), len(filled) - 1)
        return float(filled[k]) / 1000.0 + adder

    return price


def account(
    result,
    depot: DepotConfig,
    fleet_size: int,
    days: int,
    skip_days: int,
    prices: Prices | None = None,
    assumptions: Assumptions | None = None,
    wholesale: dict[str, PriceCurve] | None = None,
    reserve_vehicles: float | None = None,
) -> dict:
    """Turn a finished run into the account, per site-day and per vehicle-day."""
    prices, assumptions = prices or Prices(), assumptions or Assumptions()
    scored = days - skip_days
    steps = result.steps[result.steps[:, 0] >= skip_days * 1440.0]
    # Rides given up on are counted as they happen; a ride still waiting at the end is neither served nor lost.
    served, lost = float(steps[:, 2].sum()), float(steps[:, 5].sum())
    offered = served + lost
    step_hours = float(np.median(np.diff(steps[:, 0]))) / 60.0 if len(steps) > 1 else STEP_HOURS
    series = result.depot.series
    energy = energy_by_period(series, skip_days=skip_days)
    kwh = sum(energy.values())
    peak_kw = float(series[series[:, 0] >= skip_days * 1440.0][:, 1].max())
    fixed = fixed_cost_per_day(depot, prices)
    connection_capital = depot.site_limit_kw * assumptions.connection_per_kw
    pricing = assumptions.pricing
    per_day = {
        "revenue": pricing.revenue(steps) / scored,
        "energy_tariff": energy_cost(series, tariff_curve(prices), skip_days) / scored,
        "subscription": math.ceil(peak_kw / 50.0) * prices.subscription_per_50kw_month * 12.0 / 365.0,
        **{name: value for name, value in fixed.items()},
        "connection": connection_capital / assumptions.connection_life_years / 365.0,
        "vehicles": fleet_size * assumptions.vehicle_cost_per_year / 365.0,
        "vehicle_operations": fleet_size * assumptions.operations_per_vehicle_day,
        "reliability": (offered - served) * assumptions.lost_ride_cost / scored,
    }
    for name, curve in (wholesale or {}).items():
        per_day[f"energy_{name}"] = energy_cost(series, curve, skip_days) / scored
    costs = ["energy_tariff", "subscription", *fixed, "connection", "vehicles", "vehicle_operations", "reliability"]
    contribution = per_day["revenue"] - sum(per_day[name] for name in costs)
    site_capital = connection_capital + sum(
        fixed[name] * 365.0 * life
        for name, life in (("chargers", prices.charger_life_years), ("buffer", prices.buffer_life_years))
        if name in fixed
    )
    hours_on_road = float(steps[:, 3].sum()) * step_hours
    out = {
        "per_day": {name: round(value, 2) for name, value in per_day.items()},
        "contribution_per_day": round(contribution, 2),
        "contribution_per_vehicle_day": round(contribution / fleet_size, 2),
        "contribution_per_ride": round(contribution * scored / max(served, 1.0), 3),
        "rides_served_share": round(served / max(offered, 1.0), 4),
        "rides_lost_per_day": round((offered - served) / scored, 1),
        "fare_per_ride": round(per_day["revenue"] * scored / max(served, 1.0), 2),
        "busy_share": round(float(pricing.busy_share(steps).mean()), 4),
        "busy_priced_share": round(float((pricing.multiplier(pricing.busy_share(steps)) > 1.0).mean()), 4),
        "rides_per_vehicle_day": round(served / scored / fleet_size, 2),
        "availability": round(hours_on_road / (fleet_size * 24.0 * scored), 4),
        "kwh_per_ride": round(kwh / max(served, 1.0), 3),
        "energy_cost_per_kwh_tariff": round(per_day["energy_tariff"] * scored / max(kwh, 1.0), 4),
        "site_capital": round(site_capital, 0),
        "payback_years": round(site_capital / (365.0 * contribution), 2) if contribution > 0 else None,
        "meets_service": served / max(offered, 1.0) >= assumptions.required_service,
    }
    for name in wholesale or {}:
        out[f"energy_cost_per_kwh_{name}"] = round(per_day[f"energy_{name}"] * scored / max(kwh, 1.0), 4)
        out[f"contribution_per_day_{name}"] = round(
            contribution + per_day["energy_tariff"] - per_day[f"energy_{name}"], 2
        )
    if reserve_vehicles is not None:
        # Information, not a line: what fewer vehicles held for the bound would be worth if vehicles bind.
        out["reserve_vehicles"] = round(reserve_vehicles, 1)
        out["reserve_cost_per_day_if_vehicles_bind"] = round(
            reserve_vehicles * assumptions.vehicle_cost_per_year / 365.0, 2
        )
    return out
