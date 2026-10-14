"""One depot run for the local tool: a design, a rule and a demand source in, a summary, a trace and the account out.

Kept apart from the Streamlit page so that the page is only widgets and charts, and this can be tested
without it. Everything here is the full model: the Python simulator, the plan, the identified energy
figures, and, when real days are chosen, the trained forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from depot_twin import finance, growth
from depot_twin.data import data_dir
from depot_twin.fleet import FleetSim, ThresholdRecall, load_weekly_shape
from depot_twin.resources import ChargerBank
from depot_twin.trace import TraceRecorder

RULES = ("threshold", "plan", "plan_with_prices")
DEMAND = ("average week", "real days from 15 April 2024")


@dataclass(frozen=True)
class Design:
    """What the operator can change."""

    fleet: int = 500
    site_limit_kw: float = 2750.0
    chargers_scale: float = 1.0
    people_scale: float = 1.0
    rule: str = "plan_with_prices"
    demand: str = DEMAND[0]
    days: int = 3
    seed: int = 1


def _rule(name: str):
    from depot_twin.economics import Prices
    from depot_twin.heartbeat import Heartbeat

    if name == "threshold":
        return ThresholdRecall()
    settings = {"ledger_adapt": 0.2, "ledger_level": 0.975, "ledger_from_state": True}
    if name == "plan_with_prices":
        settings.update(prices=Prices(), pre_peak_hours=4.0, peak_call_below=0.15)
    return Heartbeat(**settings)


def _demand(design: Design, config):
    """Real days with the trained forecasts, when the data is on disk; otherwise none (the average week)."""
    if design.demand != DEMAND[1]:
        return None
    from depot_twin import evals
    from depot_twin.replay import ReplayDemand

    return ReplayDemand.scaled(evals.replay_curves(evals.E8_START), design.fleet * config.rides_per_vehicle_day)


def run(design: Design) -> dict:
    """Run the full model on a design and return its summary, its trace and its account."""
    from depot_twin.twin import EnergyIdentifier

    config, depot = growth.scaled_v2(design.fleet, site_limit_kw=design.site_limit_kw)
    # The site bounds the plugs: no more than two for every one the usable connection feeds at once.
    count = min(int(round(growth.chargers_for(design.fleet) * design.chargers_scale)), growth.charger_ceiling(depot))
    people = max(1, int(round(depot.staff * design.people_scale)))
    depot = replace(depot, chargers=(ChargerBank("dc", count, 60.0),), staff=people, cleaning_bays=people)
    rule = _rule(design.rule)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    sim = FleetSim(
        config, depot, shape, rule, depot_policy="slot_power", seed=design.seed, demand=_demand(design, config)
    )
    drive = np.array([m.drive_kwh_per_mile for m in config.models])[sim.model_of]
    load = np.array([m.always_on_kw for m in config.models])[sim.model_of]
    sim.telemetry = EnergyIdentifier(drive, load, sim.capacity, seed=design.seed)
    if design.rule != "threshold":
        rule.energy = sim.telemetry
    recorder = TraceRecorder(sim, label=f"{design.rule} + slot_power")
    result = sim.run(design.days)
    skip = 1 if design.days > 1 else 0
    books = finance.account(result, depot, design.fleet, design.days, skip)
    return {
        "summary": result.summary(),
        "trace": recorder.to_dict(),
        "account": books,
        "chargers": count,
        "people": people,
    }
