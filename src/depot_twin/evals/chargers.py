"""What the chargers do for a fleet of two vehicle types, on one feeder and on two.

Every capacity test before this one ran 60 kW chargers, so neither type ever charged at its own top rate:
up to 104 kW for the I-PACE in the model and, as assumed, 150 kW for the Ojai. E33 runs the fleet at the assumed mix, 40% Ojai, on
one feeder and on two, under six charger designs: the sizing rule's count at 60 kW and at 150 kW, half
that count at each power, and a bank with 40% of its chargers at 150 kW, either kept for the Ojai or taken
by whichever vehicle comes first. It reads the fleet carried in every fortnight and what the chargers cost.

The runs are `cadence.capacity_run`, the capacity test's own. The simulator's code is not changed: the
worker processes build each design's depot in place of the capacity test's, and for the mixed bank give
each vehicle its order of chargers.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path

from depot_twin.data import data_dir
from depot_twin.evals import mix
from depot_twin.evals.common import _write

FEEDER_KW = 2750.0
E33_FEEDERS = {
    1: (600, 625, 650, 675, 700, 725),
    2: (1200, 1250, 1300, 1350, 1400, 1450),
}
E33_STEP = {1: 25, 2: 50}
E33_FAST_KW = 150.0
E33_SLOW_KW = 60.0
E33_FAST_SHARE = 0.4  # the share of a mixed bank at 150 kW: the share of the fleet that can use it
# Each design: the share of the sizing rule's count, the power of every charger or None for the mixed
# bank, and which charger a vehicle asks for first.
E33_DESIGNS = {
    "all_60": (1.0, E33_SLOW_KW, None),
    "all_150": (1.0, E33_FAST_KW, None),
    "half_60": (0.5, E33_SLOW_KW, None),
    "half_150": (0.5, E33_FAST_KW, None),
    "mixed_kept_for_ojai": (1.0, None, "by_type"),
    "mixed_fastest_free": (1.0, None, "fastest"),
}
E33_SEEDS = 3

_DESIGN: dict = {}


def _chargers(design: str, count: int) -> tuple:
    """The charger banks of one design for a sizing-rule count."""
    from depot_twin.resources import ChargerBank

    share, kw, _ = E33_DESIGNS[design]
    count = max(1, round(count * share))
    if kw is not None:
        return (ChargerBank("dc", count, kw),)
    fast = round(count * E33_FAST_SHARE)
    return (ChargerBank("fast", fast, E33_FAST_KW), ChargerBank("dc", count - fast, E33_SLOW_KW))


def _install() -> None:
    """In this process, build each run's depot for its design and give each vehicle its order of chargers."""
    from depot_twin import cadence, control

    mix._keep_last_run()
    if getattr(cadence, "_by_design", False):
        return
    built = cadence._fleet_and_depot

    def depot_for(size, leg, clean_every, chargers):
        fleet, depot = built(size, leg, clean_every, chargers)
        design, feeders = _DESIGN["design"], _DESIGN["feeders"]
        count = sum(bank.count for bank in depot.chargers)
        return fleet, replace(depot, site_limit_kw=FEEDER_KW * feeders, chargers=_chargers(design, count))

    order = control.SlotPower.bank_order

    def bank_order(self, session, now):
        rule = E33_DESIGNS[_DESIGN["design"]][2]
        if rule == "by_type":
            return ["fast", "dc"] if session.visit.model.name == "ojai" else ["dc", "fast"]
        if rule == "fastest":
            return ["fast", "dc"]
        return order(self, session, now)

    setattr(cadence, "_fleet_and_depot", depot_for)  # noqa: B010
    setattr(control.SlotPower, "bank_order", bank_order)  # noqa: B010
    setattr(cadence, "_by_design", True)  # noqa: B010


def charger_run(job: tuple) -> dict:
    """One capacity run under one charger design and feeder count, with what each vehicle type did."""
    design, feeders, base = job
    _DESIGN.update(design=design, feeders=feeders)
    run = mix.mix_run(base)
    # The share of each type's visits on a 150 kW charger, over the scored week.
    from depot_twin.evals import E8_DAYS, E8_WARMUP_DAYS

    first = (E8_DAYS * run["passes"] - (E8_DAYS - E8_WARMUP_DAYS)) * 1440.0
    sessions = [s for s in mix._LAST["result"].depot.sessions if s.visit.arrive_min >= first and s.kind]
    for name, figures in run["by_type"].items():
        mine = [s for s in sessions if s.visit.model.name == name]
        figures["on_150_kw_share"] = round(sum(s.charger_kw >= E33_FAST_KW for s in mine) / max(len(mine), 1), 4)
    return {**run, "design": design, "feeders": feeders}


def _label(design: str, feeders: int) -> str:
    return f"{design}_{feeders}"


def _arms(runs: list[dict], depot) -> dict:
    """Each design on each feeder count: its rows by fleet, the fleet carried, and what its chargers cost."""
    from depot_twin.economics import Prices, fixed_cost_per_day
    from depot_twin.growth import chargers_for

    prices = Prices()
    arms = {}
    for feeders, sizes in E33_FEEDERS.items():
        usable = depot.usable_kw * feeders * 24.0
        for design in E33_DESIGNS:
            rows = mix._rows([r for r in runs if r["label"] == _label(design, feeders)], sizes, usable)
            whole, every = mix._carried(rows, sizes)
            for size in sizes:
                banks = _chargers(design, chargers_for(size))
                rows[str(size)]["chargers"] = [{"kw": b.kw, "count": b.count} for b in banks]
                rows[str(size)]["charger_cost_per_day"] = round(
                    fixed_cost_per_day(replace(depot, chargers=banks), prices)["chargers"], 2
                )
            arms[_label(design, feeders)] = {
                "design": design,
                "feeders": feeders,
                "by_size": rows,
                "carried": whole,
                "carried_in_every_fortnight": every,
                "carried_pinned": mix._exact(every, sizes),
                "at_the_top_of_the_steps": every == sizes[-1],
            }

    return arms


def _bars(arms: dict) -> dict:
    """The registered bars, read off the arms."""

    def carried(design: str, feeders: int) -> int | None:
        return arms[_label(design, feeders)]["carried_pinned"]

    def within_a_step(a: str, b: str, feeders: int) -> bool:
        x, y = carried(a, feeders), carried(b, feeders)
        return x is not None and y is not None and abs(x - y) <= E33_STEP[feeders]

    def cost_at(design: str, feeders: int) -> float:
        # The chargers a day at the fleet the full count at 60 kW carries.
        size = carried("all_60", feeders) or E33_FEEDERS[feeders][0]
        return arms[_label(design, feeders)]["by_size"][str(size)]["charger_cost_per_day"]

    def fewer_with_half_at_60() -> bool:
        # Below the smallest step counts as fewer: none of its fleets was carried.
        full, half = carried("all_60", 1), arms[_label("half_60", 1)]["carried_in_every_fortnight"]
        return full is not None and (half is None or half <= full - E33_STEP[1])

    return {
        "1_on_one_feeder_150_kw_chargers_carry_within_one_step_of_60_kw": within_a_step("all_150", "all_60", 1),
        "2_on_two_feeders_150_kw_chargers_carry_within_one_step_of_60_kw": within_a_step("all_150", "all_60", 2),
        "3_half_as_many_150_kw_chargers_carry_within_one_step_of_the_full_count_at_60_kw_for_less": all(
            within_a_step("half_150", "all_60", f) and cost_at("half_150", f) < cost_at("all_60", f)
            for f in E33_FEEDERS
        ),
        "4_on_one_feeder_half_as_many_60_kw_chargers_carry_at_least_one_step_fewer": fewer_with_half_at_60(),
        "5_keeping_the_fast_chargers_for_the_ojai_carries_at_least_as_many_as_fastest_free": all(
            (arms[_label("mixed_kept_for_ojai", f)]["carried_in_every_fortnight"] or 0)
            >= (arms[_label("mixed_fastest_free", f)]["carried_in_every_fortnight"] or 0)
            for f in E33_FEEDERS
        ),
    }


def e33_chargers(workers: int = 5) -> Path:
    """E33: the fleet carried in every fortnight under six charger designs, on one feeder and on two."""
    from depot_twin import cadence, provenance

    started_on = provenance.stamp("e33_chargers.json")
    chosen, best, fleet, depot = mix._setting()
    seeds = cadence.E23_SEEDS[:E33_SEEDS]
    moved = mix._fleet_moves(fleet, 0.4, 1.0)
    jobs = [
        (design, feeders, (_label(design, feeders), best, "slot_power", size, window, seed, chosen, moved))
        for feeders, sizes in E33_FEEDERS.items()
        for design in E33_DESIGNS
        for size in sizes
        for window in cadence.E23_WINDOWS
        for seed in seeds
    ]
    with ProcessPoolExecutor(max_workers=workers, initializer=_install) as pool:
        runs = list(pool.map(charger_run, jobs, chunksize=2))
    arms = _arms(runs, depot)
    bars = _bars(arms)
    # The one-feeder control against E30's runs at the mix on the same seeds: the same fleet carried.
    record = json.loads((data_dir() / "derived" / "e30_mix.json").read_text())
    control = [r for r in record["runs"] if r["label"] == "0.4_1" and r["seed"] in seeds]
    same = sum(
        any(
            r["design"] == "all_60"
            and r["feeders"] == 1
            and (r["size"], r["window"], r["seed"]) == (c["size"], c["window"], c["seed"])
            and r["served"] == c["served"]
            for r in runs
        )
        for c in control
    )
    if provenance.stamp("e33_chargers.json") != started_on:
        raise RuntimeError("the code or an upstream record changed while E33 ran: its runs cannot be stamped")
    return _write(
        "e33_chargers.json",
        {
            "eval": "E33",
            "rule": best,
            "share_ojai": 0.4,
            "windows": list(cadence.E23_WINDOWS),
            "seeds": list(seeds),
            "feeder_kw": FEEDER_KW,
            "designs": {
                name: {"share_of_the_rule": share, "kw": kw, "order": order}
                for name, (share, kw, order) in E33_DESIGNS.items()
            },
            "arms": arms,
            "same_as_e30": {"runs": len(control), "same": same},
            "runs": [{key: value for key, value in run.items() if key != "per_day"} for run in runs],
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
