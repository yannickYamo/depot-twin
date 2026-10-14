"""Run six of the published runs again and print them beside the record: the headlines, checked in minutes.

The full chain needs the public ride records, the forecast models and hours of compute. This needs none of
that: it reads the replay curves of one fortnight committed under data/reproduce, and runs the power rule
at 1,000 vehicles both ways, the fleet at the hundred-vehicle step that was carried and the step past it,
the fleet between them, and the planned fleet with 10% more energy use. Each run is compared with the
same run in its record (`e23_capacity.json`, `e25_between.json`, `e26_margin.json`). The simulator is
seeded, so the figures must agree to the last digit kept. Under each run it prints how many times the
fortnight was replayed before the scored week stopped moving. A run that has no counterpart in the
records is a failure, not a skip.
"""

from __future__ import annotations

import json

from depot_twin.data import data_dir

WINDOW, SEED = "2024-04-15", 2301


def cases(record: dict, between: dict, margin: dict) -> list[tuple]:
    """The runs to repeat, each with the record it is in: label, rule, power rule, fleet, energy use, record."""
    from depot_twin import analysis

    planned, _ = analysis.planned_fleet(data_dir() / "derived")
    capacity = record["capacity"] or record["setting"].get("fleet", 600)
    best = record["best_rule"]
    return [
        ("power", "threshold", "slot_power", 1000, 1.0, record),
        ("power", "threshold", "need_first", 1000, 1.0, record),
        ("base", best, "slot_power", capacity, 1.0, record),
        ("base", best, "slot_power", capacity + 100, 1.0, record),
        ("between", best, "slot_power", between["size"], 1.0, between),
        (f"energy_{margin['margin']:g}", best, "slot_power", planned, margin["margin"], margin),
    ]


def main() -> int:
    """Run the cases, print each beside its recorded value, and return 0 when every one is there and agrees."""
    from depot_twin import cadence
    from depot_twin.evals import margin as margin_test

    derived = data_dir() / "derived"
    record, between, margin = (
        json.loads((derived / name).read_text())
        for name in ("e23_capacity.json", "e25_between.json", "e26_margin.json")
    )
    setting = record["setting"]
    fleet, _ = cadence._fleet_and_depot(600, setting["leg"], setting["clean_every"], setting["chargers"])
    agree = True
    print(f"{'run':62s} {'rides served':>13s} {'recorded':>10s}")
    for label, rule, policy, size, energy, source in cases(record, between, margin):
        name = f"{size} vehicles, {rule}, {'in order' if policy == 'slot_power' else 'emptiest first'}"
        name += "" if energy == 1.0 else f", energy use x{energy:g}"
        want = next(
            (
                r
                for r in source["runs"]
                if (r["label"], r["rule"], r["policy"], r["size"], r["window"], r["seed"])
                == (label, rule, policy, size, WINDOW, SEED)
            ),
            None,
        )
        if want is None:
            agree = False
            print(f"{name:62s} {'':13s} {'':10s}   NOT IN THE RECORD")
            continue
        moved = {} if energy == 1.0 else {"models": margin_test._models(fleet, energy)}
        got = cadence.capacity_run((label, rule, policy, size, WINDOW, SEED, setting, moved))
        same = (
            abs(got["served"] - want["served"]) < 5e-6
            and abs(got["arrived_at_floor_share"] - want["arrived_at_floor_share"]) < 5e-6
        )
        agree = agree and same
        print(f"{name:62s} {got['served']:13.4%} {want['served']:10.4%} {'' if same else '  DIFFERS'}")
        # How long the fortnight was replayed before the scored week stopped moving, and by how much it still did.
        print(
            f"{'':6s}{got['passes']} passes; low-battery arrivals {got['arrived_at_floor_share']:.1%}"
            f" against {got['arrived_at_floor_share_a_pass_earlier']:.1%} a pass earlier"
        )
    print("every run agrees with the record" if agree else "a run differs from the record, or is not in it")
    return 0 if agree else 1
