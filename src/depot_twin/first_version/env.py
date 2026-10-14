"""The fleet and depot as a reinforcement-learning environment.

One step is one hour. The action sets the recall and release levels for that hour; the reward is the rides
lost in it, as a share of an average hour's demand. An episode is one week.
"""

from __future__ import annotations

from pathlib import Path

import gymnasium as gym
import numpy as np

from depot_twin.dispatch import ParamRecall
from depot_twin.first_version.policy import ACTIONS, OBSERVATION_SIZE, observe
from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape


class DepotEnv(gym.Env):
    """A week of fleet operation, decided hour by hour."""

    metadata = {"render_modes": []}

    def __init__(self, scenario: str | Path, shape: str | Path, days: int = 7, first_seed: int = 1000):
        self.fleet_config, self.depot_config = load_fleet_scenario(scenario)
        self.shape = load_weekly_shape(shape)
        self.hours = days * 24
        # Training episodes draw seeds from first_seed upward, well away from the seeds used in evaluation.
        self._next_seed = first_seed
        self.action_space = gym.spaces.Discrete(len(ACTIONS))
        self.observation_space = gym.spaces.Box(-1.0, 2.0, shape=(OBSERVATION_SIZE,), dtype=np.float32)
        self.sim: FleetSim | None = None

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        """Start a new week with a fresh fleet."""
        super().reset(seed=seed)
        if seed is not None:
            self._next_seed = seed
        self.rule = ParamRecall()
        # Three-minute power steps: three times faster, and the hourly decisions do not need finer.
        self.sim = FleetSim(
            self.fleet_config, self.depot_config, self.shape, self.rule, seed=self._next_seed, depot_step_min=3.0
        )
        self._next_seed += 1
        self._hour = 0
        self._row = 0
        self.sim.advance(0.0)
        return observe(self.sim.state()), {}

    def step(self, action: int):
        """Apply the levels for one hour and return the rides lost in it as a negative reward."""
        self.rule.recall_soc, self.rule.target = ACTIONS[int(action)]
        self.sim.advance(60.0)
        rows = np.array(self.sim._steps[self._row :])
        self._row = len(self.sim._steps)
        lost = float((rows[:, 1] - rows[:, 2]).sum())
        average_hour = self.fleet_config.size * self.fleet_config.rides_per_vehicle_day / 24.0
        self._hour += 1
        done = self._hour >= self.hours
        return observe(self.sim.state()), -lost / average_hour, done, False, {"lost": lost}
