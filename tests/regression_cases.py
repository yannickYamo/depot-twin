"""Small, fast, fully seeded runs whose headline numbers are pinned in golden.json.

These are not claims about depots. They exist so that a change which alters what the simulator computes
cannot slip in unnoticed: if a number here moves, either the change was meant to move it (regenerate the
file and say why in the commit) or something broke.

Regenerate with:  python -m tests.regression_cases
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from depot_twin import ChargerBank, DepotConfig, DepotSim, VehicleModel, load_scenario
from depot_twin.dispatch import HeadroomRecall, RollingPlan
from depot_twin.fleet import FleetConfig, FleetSim, ThresholdRecall
from depot_twin.heartbeat import Heartbeat
from depot_twin.replay import ReplayDemand

ROOT = Path(__file__).parent.parent
GOLDEN = Path(__file__).parent / "golden.json"
LEGACY_CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11)
CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11, drive_kwh_per_mile=0.3, always_on_kw=2.0)
DAY = np.array([2, 1, 1, 1, 1, 2, 3, 5, 6, 5, 5, 5, 5, 5, 5, 6, 7, 7, 7, 6, 5, 5, 4, 3], dtype=float)
SHAPE = np.tile(DAY, 7) / np.tile(DAY, 7).sum()
KEYS = ("rides_served_share", "available_at_peak_share", "miles_per_vehicle_day", "kwh_per_vehicle_day")
KEYS += ("depot_visits_per_vehicle_day", "depot_turnaround_mean_min", "depot_peak_grid_kw", "stranded")


def _depot(chargers: int, limit: float) -> DepotConfig:
    return DepotConfig("t", limit, (ChargerBank("dc", chargers, 60),), staff=4, cleaning_bays=4, clean_minutes=8)


def _fleet(rule, policy: str, limit: float = 2000.0, model: VehicleModel = LEGACY_CAR, **fleet) -> dict:
    config = FleetConfig(size=120, models=(model,), **fleet)
    summary = FleetSim(config, _depot(16, limit), SHAPE, rule, depot_policy=policy, seed=7).run(2).summary()
    return {key: round(float(summary[key]), 6) for key in KEYS}


def _replay() -> ReplayDemand:
    steps = 2 * 288
    hourly = np.tile(np.repeat(DAY, 12), 2) * 120 * 25 / (DAY.sum() * 12)
    ahead = np.array([[hourly[min(steps - 1, s + 12 * k)] * 12 for k in range(24)] for s in range(steps)])
    return ReplayDemand(counts=hourly, mean=ahead, upper=ahead * 1.2, actual=ahead)


def cases() -> dict[str, dict]:
    """Return every pinned case, computed now."""
    example = DepotSim.from_scenario(load_scenario(ROOT / "scenarios" / "overnight_example.toml", seed=1)).run()
    heartbeat = FleetSim(
        FleetConfig(size=120, models=(CAR,), step_min=5, vehicle_spread=0.08),
        _depot(16, 600.0),
        SHAPE,
        Heartbeat(ledger_adapt=0.2, ledger_level=0.975, ledger_from_state=True),
        depot_policy="slot_power",
        seed=7,
        demand=_replay(),
    ).run(2)
    return {
        "depot_overnight_example": {k: round(float(v), 6) for k, v in example.summary().items()},
        "fleet_threshold_lowest_first": _fleet(ThresholdRecall(), "need_first"),
        "fleet_headroom_lowest_first": _fleet(HeadroomRecall(), "need_first"),
        "fleet_plan_lowest_first": _fleet(RollingPlan(), "need_first"),
        "fleet_threshold_in_order_power_short": _fleet(ThresholdRecall(), "slot_power", limit=350.0),
        "fleet_threshold_lowest_first_power_short": _fleet(ThresholdRecall(), "need_first", limit=350.0),
        "fleet_heartbeat_replayed_demand": {key: round(float(heartbeat.summary()[key]), 6) for key in KEYS},
    }


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(cases(), indent=2) + "\n")
    print(f"wrote {GOLDEN}")
