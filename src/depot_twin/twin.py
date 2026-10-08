"""Identifying the twin: estimating each vehicle's parameters from its own telemetry.

The simulator is built from physics and public figures, but the numbers that matter most are not public and
differ from vehicle to vehicle: how much energy a mile costs, how much the computers and climate control
draw whether the vehicle moves or not, and how fast the battery really accepts charge. These are not
trained. They are identified: estimated continuously from what each vehicle reports, starting from a
published or assumed value and corrected by every new reading.

In operation the telemetry would come from the fleet. Here it comes from the simulator, whose vehicles are
given true values the estimator is not shown. That is what makes the estimator testable.
"""

from __future__ import annotations

import numpy as np

from depot_twin.resources import VehicleModel


class EnergyIdentifier:
    """Estimates, per vehicle, energy = (kWh per mile) x miles + (kW always on) x hours.

    One small Kalman filter per vehicle, with the two parameters as a state that does not move. Each
    reading is the energy a vehicle used over one step, as seen through its state-of-charge gauge, which
    is noisy. The filter weighs a reading by how much it can still learn from it.
    """

    def __init__(
        self,
        prior_drive: np.ndarray,
        prior_always_on: np.ndarray,
        capacity_kwh: np.ndarray,
        prior_spread: float = 0.15,
        soc_noise: float = 0.001,
        seed: int = 0,
    ):
        count = len(prior_drive)
        self.theta = np.column_stack([prior_drive, prior_always_on]).astype(float)
        self.cov = np.zeros((count, 2, 2))
        self.cov[:, 0, 0] = (prior_spread * prior_drive) ** 2
        self.cov[:, 1, 1] = (prior_spread * prior_always_on) ** 2
        # Energy over a step is the difference of two gauge readings, each off by soc_noise of the pack.
        self.noise_kwh = soc_noise * capacity_kwh * np.sqrt(2.0)
        self.readings = np.zeros(count, dtype=int)
        self._rng = np.random.default_rng(seed)

    def record(self, vehicles: np.ndarray, miles: np.ndarray, hours: float, energy_kwh: np.ndarray) -> None:
        """Take one step's telemetry for the given vehicles and update their estimates."""
        measured = energy_kwh + self._rng.normal(0.0, self.noise_kwh[vehicles])
        x = np.column_stack([miles, np.full(len(vehicles), hours)])
        cov = self.cov[vehicles]
        cov_x = np.einsum("nij,nj->ni", cov, x)
        gain = cov_x / (self.noise_kwh[vehicles] ** 2 + np.einsum("ni,ni->n", x, cov_x))[:, None]
        error = measured - np.einsum("ni,ni->n", x, self.theta[vehicles])
        self.theta[vehicles] += gain * error[:, None]
        self.cov[vehicles] = cov - np.einsum("ni,nj->nij", gain, cov_x)
        self.readings[vehicles] += 1

    @property
    def drive_kwh_per_mile(self) -> np.ndarray:
        """Return the current estimate of each vehicle's driving energy."""
        return self.theta[:, 0]

    @property
    def always_on_kw(self) -> np.ndarray:
        """Return the current estimate of each vehicle's always-on load."""
        return self.theta[:, 1]


class ChargeCurveIdentifier:
    """Estimates, per vehicle type, how much power the battery accepts at each state of charge.

    Only readings where the vehicle got everything it could take are used; when the site was short of
    power, the reading says nothing about the battery. The estimate for a band of charge is the median
    of those readings, which is the battery's limit or the charger's, whichever is lower.
    """

    def __init__(self, bin_width: float = 0.05):
        self.bin_width = bin_width
        self._seen: dict[str, dict[int, list[float]]] = {}

    def record(self, model: VehicleModel, soc: float, delivered_kw: float, could_take_kw: float) -> None:
        """Take one power reading from a charging session."""
        if delivered_kw < could_take_kw - 1e-6:
            return
        band = int(min(soc, 0.9999) / self.bin_width)
        self._seen.setdefault(model.name, {}).setdefault(band, []).append(delivered_kw)

    def curve(self, name: str, min_readings: int = 30) -> list[tuple[float, float]]:
        """Return (state of charge at the middle of the band, kW accepted) for every band seen enough."""
        bands = self._seen.get(name, {})
        return [
            ((band + 0.5) * self.bin_width, float(np.median(values)))
            for band, values in sorted(bands.items())
            if len(values) >= min_readings
        ]


def relative_error(estimate: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """Return the absolute error of each estimate as a share of the true value."""
    return np.abs(estimate - truth) / truth
