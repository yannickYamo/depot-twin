"""E34: the fleet two feeders carry with the planning margin, 10% more energy use than estimated.

E33 ran two feeders at the estimate only. This is the same run, the sizing rule's count of 60 kW chargers
at the assumed mix, with energy use 10% higher, as the plan of 600 on one feeder is read.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

from depot_twin.evals import chargers, mix
from depot_twin.evals.common import _write

E34_SIZES = (1100, 1150, 1200, 1250, 1300)
E34_ENERGY = 1.1
E34_AT_LEAST = 1200  # twice the fleet one feeder is planned for


def e34_two_feeders(workers: int = 5) -> Path:
    """E34: the fleet carried in every fortnight on two feeders with 10% more energy use."""
    from depot_twin import cadence, provenance

    started_on = provenance.stamp("e34_two_feeders.json")
    chosen, best, fleet, depot = mix._setting()
    seeds = cadence.E23_SEEDS[: chargers.E33_SEEDS]
    moved = mix._fleet_moves(fleet, 0.4, E34_ENERGY)
    jobs = [
        ("all_60", 2, ("planned_2", best, "slot_power", size, window, seed, chosen, moved))
        for size in E34_SIZES
        for window in cadence.E23_WINDOWS
        for seed in seeds
    ]
    with ProcessPoolExecutor(max_workers=workers, initializer=chargers._install) as pool:
        runs = list(pool.map(chargers.charger_run, jobs, chunksize=2))
    rows = mix._rows(runs, E34_SIZES, depot.usable_kw * 2 * 24.0)
    whole, every = mix._carried(rows, E34_SIZES)
    bars = {"1_two_feeders_carry_at_least_1200_in_every_fortnight_with_10pct_more": (every or 0) >= E34_AT_LEAST}
    if provenance.stamp("e34_two_feeders.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E34 ran: its runs cannot be stamped")
    return _write(
        "e34_two_feeders.json",
        {
            "eval": "E34",
            "rule": best,
            "share_ojai": 0.4,
            "energy": E34_ENERGY,
            "feeders": 2,
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(seeds),
            "by_size": rows,
            "carried": whole,
            "carried_in_every_fortnight": every,
            "carried_pinned": mix._exact(every, E34_SIZES),
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
