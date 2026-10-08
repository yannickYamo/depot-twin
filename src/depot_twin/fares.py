"""What a ride pays, simulated the way the robotaxi prices it, not read off a taxi meter.

The service publishes how a price is built but not its rates: a minimum, a part for distance, a part for
time, and an adjustment for demand, all quoted up front before the ride. A taxi meter is a different
product (a flag fall and a rate per mile, no time part, no demand part), so taxi fares are not used here.
The model:

- rates: base + per mile + per minute, in the proportions a public price survey reported for the Bay
  Area service in late 2025. The proportions are that survey's reading, not a rate card; the level is set
  here so that the quiet price of the filed average trip equals the published average fare;
- trip: the filed miles with a passenger, and the minutes the fleet model gives that part of a ride;
- busy pricing: a mild multiplier when the fleet is nearly all busy, read from the twin's own run. Each
  step knows how many vehicles are on the road and how many rides they served; above a busy threshold
  the price rises to a cap. Public descriptions of the service put the adjustment at one to three tenths,
  so the cap is 1.3 and the threshold is a parameter.

The account pays each served ride the price of its step. Revenue therefore depends on how the fleet is
run: a fleet with no slack sells every ride at the busy price and loses the rides it cannot take.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PUBLISHED_AVERAGE_FARE = 19.69  # average Bay Area robotaxi fare in a published price survey, late 2025
PAID_TRIP_MILES = 3.93  # the filed average, see docs/SITE.md
RIDE_MINUTES = 23.0  # the fleet model's ride, pickup leg included (fleet.FleetConfig.ride_minutes)
MILES_TO_PICKUP = 0.99  # filed


@dataclass(frozen=True)
class PriceModel:
    """The price of one ride: rates in the survey's proportions, scaled to the published average, plus busy pricing."""

    base: float = 9.52  # survey proportions, scaled by `level`
    per_mile: float = 1.66
    per_minute: float = 0.30
    busy_threshold: float = 0.8  # share of on-road vehicles busy above which the price starts to rise
    busy_cap: float = 1.3  # the multiplier at full use; public descriptions put busy pricing at 1.1 to 1.3

    @property
    def paid_minutes(self) -> float:
        """Minutes with a passenger: the ride's minutes, in proportion to the miles with a passenger."""
        return RIDE_MINUTES * PAID_TRIP_MILES / (PAID_TRIP_MILES + MILES_TO_PICKUP)

    @property
    def level(self) -> float:
        """The factor that puts the quiet price of the filed average trip on the published average."""
        return PUBLISHED_AVERAGE_FARE / (
            self.base + self.per_mile * PAID_TRIP_MILES + self.per_minute * self.paid_minutes
        )

    def quiet(self, miles: float = PAID_TRIP_MILES, minutes: float | None = None) -> float:
        """The price of a trip with no demand adjustment."""
        minutes = self.paid_minutes if minutes is None else minutes
        return self.level * (self.base + self.per_mile * miles + self.per_minute * minutes)

    def multiplier(self, busy: np.ndarray) -> np.ndarray:
        """Busy pricing from the share of on-road vehicles busy: flat to the threshold, then up to the cap."""
        above = np.clip((busy - self.busy_threshold) / (1.0 - self.busy_threshold), 0.0, 1.0)
        return 1.0 + (self.busy_cap - 1.0) * above

    def busy_share(self, steps: np.ndarray, ride_minutes: float = RIDE_MINUTES) -> np.ndarray:
        """Share of on-road vehicles busy in each step of (minute, offered, served, on_road, ...)."""
        step_minutes = float(np.median(np.diff(steps[:, 0]))) if len(steps) > 1 else 5.0
        capacity = np.maximum(steps[:, 3], 1.0) * step_minutes / ride_minutes
        return np.clip(steps[:, 2] / capacity, 0.0, 1.0)

    def prices(self, steps: np.ndarray, ride_minutes: float = RIDE_MINUTES) -> np.ndarray:
        """The price of a ride in each step, levelled so the rides served average the published fare.

        The published average already contains busy pricing. So the multiplier moves the price between
        quiet and busy steps, and the average over the rides served stays where the filings put it. Without
        this a depot that starves its road is paid more per ride for doing so, with no rider turning away
        at the higher price: scarcity the depot caused would read as revenue.
        """
        multiplier = self.multiplier(self.busy_share(steps, ride_minutes))
        served = steps[:, 2]
        mean = float((served * multiplier).sum() / served.sum()) if served.sum() > 0 else 1.0
        return self.quiet() * multiplier / mean

    def revenue(self, steps: np.ndarray, ride_minutes: float = RIDE_MINUTES) -> float:
        """Fares earned over the steps: each served ride at the price of its step."""
        return float((steps[:, 2] * self.prices(steps, ride_minutes)).sum())

    def describe(self) -> dict:
        """The model's figures, for the record."""
        return {
            "published_average_fare": PUBLISHED_AVERAGE_FARE,
            "paid_trip_miles": PAID_TRIP_MILES,
            "paid_minutes": round(self.paid_minutes, 2),
            "rates_scaled": {
                "base": round(self.level * self.base, 2),
                "per_mile": round(self.level * self.per_mile, 3),
                "per_minute": round(self.level * self.per_minute, 3),
            },
            "busy_threshold": self.busy_threshold,
            "busy_cap": self.busy_cap,
        }
