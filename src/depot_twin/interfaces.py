"""The interfaces the simulator and the controller ask of what is plugged into them.

A fleet takes a demand source, a telemetry sink and an observer; a controller takes an energy estimate
and prices. Each is small, and writing them down means a type checker can say when a replacement does
not fit, instead of a run failing an hour in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    from depot_twin.fleet import FleetSim


class DemandSource(Protocol):
    """Rides offered in a step, and the forecast for the hours ahead with its upper bound."""

    def offered(self, minute: float, step_min: float) -> float:
        """Rides offered in the step starting at this minute."""
        ...

    def ahead(self, minute: float) -> tuple[np.ndarray, np.ndarray]:
        """The forecast for the coming hours, and its upper bound."""
        ...


class TelemetrySink(Protocol):
    """Receives each step's miles, hours and energy for the vehicles on the road."""

    def record(self, vehicles: np.ndarray, miles: np.ndarray, hours: float, energy_kwh: np.ndarray) -> None:
        """Take one step's readings."""
        ...


class EnergyEstimate(Protocol):
    """Each vehicle's driving energy and always-on load, as estimated so far."""

    @property
    def drive_kwh_per_mile(self) -> np.ndarray:
        """Driving energy per mile, by vehicle."""
        ...

    @property
    def always_on_kw(self) -> np.ndarray:
        """Load that runs whether the vehicle moves or not, by vehicle."""
        ...


class FleetObserver(Protocol):
    """Called once per step, after the step's rides are served."""

    def tick(self, sim: FleetSim) -> None:
        """See the fleet as it stands after this step."""
        ...


class EnergyPrices(Protocol):
    """What a ride pays and what energy costs in each tariff period."""

    revenue_per_ride: float
    energy_peak: float
    energy_off_peak: float
    energy_super_off_peak: float
