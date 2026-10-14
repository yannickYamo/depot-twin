"""Which hours are expensive: the question the plan's price steering asks, apart from the plan.

On a tariff the answer is the peak period. On a price curve it has to be worked out from the next day's
prices: the dearest quarter of the hours ahead, and only those well above the median, so that a flat
curve has no expensive hours at all. The rule is written down here once, with its test.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

PriceAt = Callable[[float], float]  # minute of the run -> dollars per kWh


def expensive_window(now: float, price_at: PriceAt | None, horizon: int = 24) -> tuple[bool, float | None, float]:
    """Return whether this hour is expensive, how many hours until the next expensive stretch, and its length.

    On the tariff, expensive means the peak period, 4 pm to 9 pm, five hours long. On a price curve, an
    hour is expensive when it is in the dearest quarter of the next `horizon` hours and costs at least a
    fifth more than the median hour. The second condition keeps a day with five dear hours and nineteen
    alike from counting the nineteen: a quantile alone does, when prices tie.
    """
    from depot_twin.economics import tariff_period

    if price_at is None:
        hour = (now / 60.0) % 24.0
        return tariff_period(now) == "peak", (16.0 - hour if hour < 16.0 else None), 5.0
    start = int(now // 60) * 60.0
    prices = np.array([price_at(start + k * 60.0) for k in range(horizon)])
    expensive = (prices >= np.quantile(prices, 0.75)) & (prices >= 1.2 * np.median(prices))
    if expensive[0]:
        return True, None, 1.0
    ahead = np.flatnonzero(expensive)
    if len(ahead) == 0:
        return False, None, 0.0
    first = int(ahead[0])
    length = 1
    while first + length < len(expensive) and expensive[first + length]:
        length += 1
    return False, float(first), float(length)
