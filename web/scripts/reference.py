"""Write tests/reference.json: the Python simulator's numbers for the cases the browser simulator is held to.

Run from the repository root:  python web/scripts/reference.py

Both simulators are set up alike and measured alike, so the tolerance in tests/sim.test.ts is about the two
implementations and their random numbers, not about definitions: demand drawn from the weekly shape, seven
days with the first left out, a fixed threshold, and three figures read the same way on both sides (rides
served of rides offered, arrivals at the depot per vehicle-day, grid energy per vehicle-day). Each figure
is the mean of three seeds.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEEDS = (1, 2, 3)
DAYS, SKIP_DAYS = 7, 1
# The settings the page is held to: long visits, the cadence the filings count, and a depot short of people.
CASES = {
    "": {"call_below": 0.20, "clean_every": 1, "leg_minutes": 15.0},
    "_cadence": {"call_below": 0.55, "clean_every": 4, "leg_minutes": 8.0},
    # Long visits with four people on the floor: plugging, unplugging and cleaning all wait for someone.
    "_few_people": {"call_below": 0.20, "clean_every": 1, "leg_minutes": 15.0, "staff": 4},
}


def one(job: tuple[int, str, str, int]) -> dict:
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_fleet_scenario, load_weekly_shape, served_share

    size, policy, case, seed = job
    setting = CASES[case]
    fleet, depot = load_fleet_scenario(ROOT / "scenarios" / "v2" / f"east_oakland_{size}.toml")
    # The browser scales the drive to the depot from four miles in fifteen minutes.
    leg = setting["leg_minutes"]
    fleet = replace(fleet, depot_leg_minutes=leg, depot_leg_miles=4.0 * leg / 15.0)
    depot = replace(depot, clean_every=setting["clean_every"], staff=setting.get("staff", depot.staff))
    shape = load_weekly_shape(ROOT / "data" / "derived" / "weekly_shape_sf.json")
    rule = ThresholdRecall(setting["call_below"], 0.85)
    result = FleetSim(fleet, depot, shape, rule, depot_policy=policy, seed=seed).run(DAYS)
    first, days = SKIP_DAYS * 1440.0, DAYS - SKIP_DAYS
    steps = result.steps[result.steps[:, 0] >= first]
    series = result.depot.series[result.depot.series[:, 0] >= first]
    visits = sum(1 for s in result.depot.sessions if s.visit.arrive_min >= first)
    return {
        "key": f"{size}_{policy}{case}",
        "rides_served_share": served_share(steps),
        "visits_per_vehicle_day": visits / size / days,
        "grid_kwh_per_vehicle_day": float(series[:, 1].sum()) / 60.0 / size / days,
    }


def main() -> None:
    jobs = [(size, policy, case, seed) for size in (500, 1000) for policy in ("slot_power", "need_first") for case in CASES for seed in SEEDS]
    with ProcessPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(one, jobs))
    out = {}
    for key in dict.fromkeys(run["key"] for run in runs):
        group = [run for run in runs if run["key"] == key]
        out[key] = {name: round(sum(run[name] for run in group) / len(group), 4) for name in group[0] if name != "key"}
    out["_made_by"] = "web/scripts/reference.py: seeds 1 to 3, seven days less the first, weekly shape"
    (ROOT / "web" / "tests" / "reference.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
