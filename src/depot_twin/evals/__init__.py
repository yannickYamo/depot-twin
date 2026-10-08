"""The registered evaluations, by name, and the names other modules reach for.

The tests live in five modules by subject (`common`, `foundations`, `control`, `forecast`, `money`); this
package is the registry `depot-twin eval` reads, and it re-exports the settings and helpers the workbench,
the cadence tests and the local tool reuse, so that `depot_twin.evals.E8_START` keeps meaning one thing.
"""

from __future__ import annotations

from depot_twin.evals.common import (  # noqa: F401
    E8_DAYS,
    E8_DEV_START,
    E8_RULES,
    E8_SEEDS,
    E8_SIZES,
    E8_START,
    E8_WARMUP_DAYS,
    E9_LEDGER,
    E9_SEEDS,
    E9_START,
    E12_ARMS,
    E12_SEEDS,
    E12_SETTINGS,
    E12_START,
    _e8_rule,
    _e8_scores,
    _sf_counts,
    _sf_counts_cached,
    _weather_frame,
    _write,
    replay_curves,
)
from depot_twin.evals.control import (  # noqa: F401
    E14_START,
    e8_heartbeat,
    e8_run,
    e9_ledger,
    e10_guard,
    e11_apart,
    e12_cost,
    e12_run,
    e14_power_rules,
    growth_study_v2,
    sensitivity_study,
    session_length_study,
    staffing_study,
)
from depot_twin.evals.forecast import (  # noqa: F401
    E17_WINDOW,
    e7_forecasts,
    e7b_scale_free,
    e13_new_site,
    e15_worst_scenario,
    e16_regret,
    e17_fixes,
    e18_reserve,
    first_hour_study,
)
from depot_twin.evals.foundations import (  # noqa: F401
    e1_demand,
    e1_walk_forward,
    e2_recall,
    e3_surrogate,
    e4_planner,
    e5_active,
    e6_identify,
    growth_study,
)
from depot_twin.evals.money import (  # noqa: F401
    E19_CHARGERS,
    E19_CONTROLS,
    E19_FEEDERS,
    E19_FLEETS,
    e19_sweet_spot,
    e20_price_steering,
)


def _lazy(module: str, name: str):
    """A registered test that lives in another module, imported when it is run."""
    import importlib

    def run(*args, **kwargs):
        return getattr(importlib.import_module(f"depot_twin.{module}"), name)(*args, **kwargs)

    return run


EVALS = {
    "e1": e1_demand,
    "e1-walk": e1_walk_forward,
    "e2": e2_recall,
    "growth": growth_study,
    "e3": e3_surrogate,
    "e4": e4_planner,
    "e5": e5_active,
    "e6": e6_identify,
    "e7": e7_forecasts,
    "e7b": e7b_scale_free,
    "e8": e8_heartbeat,
    "growth-v2": growth_study_v2,
    "e9": e9_ledger,
    "e10": e10_guard,
    "e11": e11_apart,
    "e12": e12_cost,
    "session-length": session_length_study,
    "staffing": staffing_study,
    "e13": e13_new_site,
    "e14": e14_power_rules,
    "sensitivity": sensitivity_study,
    "e15": e15_worst_scenario,
    "first-hour": first_hour_study,
    "e16": e16_regret,
    "e17": e17_fixes,
    "e18": e18_reserve,
    "e19": e19_sweet_spot,
    "e20": e20_price_steering,
    "e22": _lazy("cadence", "e22_cadence"),
    "e21": _lazy("cadence", "e21_demand"),
}
