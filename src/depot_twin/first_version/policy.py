"""The learned recall policy: what it sees, what it can do, and how it plugs into the fleet.

The policy turns the two dials of ParamRecall once an hour. Everything it sees is a share or a ratio, never
a count, so a policy trained on a small fleet can be run on a large one.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from depot_twin.dispatch import ParamRecall
from depot_twin.fleet import FleetState

RECALL_LEVELS = (0.15, 0.25, 0.35, 0.50, 0.65)
TARGET_LEVELS = (0.60, 0.75, 0.90)
ACTIONS = tuple((recall, target) for recall in RECALL_LEVELS for target in TARGET_LEVELS)
OBSERVATION_SIZE = 12


def observe(state: FleetState) -> np.ndarray:
    """Return the policy's view of the fleet and depot as numbers between roughly 0 and 2."""
    size = state.fleet.size
    on_road = state.on_road
    soc = state.soc[on_road] if len(on_road) else np.array([0.0])
    chargers = max(1, sum(bank.count for bank in state.depot.depot.chargers))
    hour = (state.now / 60.0) % 24.0
    can_carry = max(1.0, len(on_road) * state.rides_per_vehicle_hour)
    return np.array(
        [
            math.sin(2 * math.pi * hour / 24.0),
            math.cos(2 * math.pi * hour / 24.0),
            ((state.now // 1440) % 7) / 7.0,
            len(on_road) / size,
            float(soc.mean()),
            float((soc < 0.3).mean()),
            float((soc < 0.6).mean()),
            len(state.depot.charging) / chargers,
            min(2.0, len(state.depot.waiting) / chargers),
            min(2.0, float(state.demand_next_hours[0]) / can_carry),
            min(2.0, float(state.demand_next_hours[1:4].max()) / can_carry),
            min(2.0, float(state.demand_next_hours[4:12].max()) / can_carry),
        ],
        dtype=np.float32,
    )


class LearnedRecall(ParamRecall):
    """A trained policy acting as a recall rule."""

    name = "learned"

    def __init__(self, model_path: str | Path):
        super().__init__()
        # Imported here so the simulator does not need the training stack to run hand-written rules.
        from stable_baselines3 import PPO

        self.model = PPO.load(str(model_path), device="cpu")
        self._hour = -1

    def recall(self, state: FleetState) -> list[int]:
        """Let the policy reset the dials on the hour, then recall as ParamRecall does."""
        hour = int(state.now // 60)
        if hour != self._hour:
            self._hour = hour
            action, _ = self.model.predict(observe(state), deterministic=True)
            self.recall_soc, self.target = ACTIONS[int(action)]
        return super().recall(state)
