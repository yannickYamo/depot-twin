"""The figures the public documents quote, read from the result files in one place.

A finding has one figure. The README, the brief and the story each state the same handful of findings, so
each must state them with the same numbers, and those numbers come from here: `docs/FACTS.json` is
written from the result files, and a test fails when a headline document says anything else. The count
of bars passed is quoted more widely, so every public document and the page's own text are checked for it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from depot_twin.data import data_dir
from depot_twin.scoreboard import rows

# The three documents a reader meets first. Each states every headline finding, in the same figures.
DOCUMENTS = ("README.md", "docs/BRIEF.md", "docs/STORY.md")
# Everything else a reader can open.
OTHER_PUBLIC = (
    "PRODUCT.md",
    "DESIGN.md",
    "docs/ARCHITECTURE.md",
    "docs/DATA.md",
    "docs/FORECAST_PLAN.md",
    "docs/MODEL_CARD.md",
    "docs/RELATED_WORK.md",
    "docs/ROADMAP.md",
    "docs/SITE.md",
    "docs/TRAINING.md",
    "web/index.html",
)
PAGE_SOURCES = ("web/src/*.ts", "web/src/views/*.ts")


def _record(name: str) -> dict:
    return json.loads((data_dir() / "derived" / name).read_text())


def _best_design(sweep: dict, feeder: str | None = None) -> dict:
    """The design with the highest contribution a day among those serving the required share of rides, as E19 ranks them."""
    groups: dict[tuple, list[dict]] = {}
    for row in sweep["rows"]:
        if feeder is None or row["feeder"] == feeder:
            groups.setdefault((row["feeder"], row["fleet"], row["chargers"], row["control"]), []).append(row)
    designs = []
    for (name, fleet, chargers, control), group in groups.items():
        mean = lambda key, group=group: sum(r[key] for r in group) / len(group)  # noqa: E731
        if mean("rides_served_share") >= sweep["assumptions"]["required_service"]:
            designs.append(
                {
                    "feeder": name,
                    "fleet": fleet,
                    "chargers": chargers,
                    "control": control,
                    "contribution_per_day": round(mean("contribution_per_day"), -2),
                    "contribution_per_vehicle_day": round(mean("contribution_per_vehicle_day"), 1),
                    "rides_served_share": round(mean("rides_served_share"), 4),
                }
            )
    return max(designs, key=lambda design: design["contribution_per_day"])


def public_facts() -> dict:
    """Every headline figure, from the record that produced it."""
    table = rows()
    scored = [r for r in table if r["bars"]]
    cadence, demand = _record("e22_cadence.json"), _record("e21_demand.json")
    apart, cost = _record("e11_apart.json")["table"], _record("e12_cost.json")["table"]
    reserve = _record("e18_reserve.json")["series"]["nyc_yellow"]
    arm = {r["arm"]: r for r in cadence["findings"]}
    area = demand["areas"]["east_bay_20km"]
    sweep = _record("e19_sweet_spot.json")
    return {
        "tests_run": len(table),
        "bars_passed": sum(r["passed"] for r in scored),
        "bars_total": sum(r["bars"] for r in scored),
        "capacity_one_feeder_at_99": cadence["capacity_at_99"],
        "capacity_one_feeder_at_99_long_sessions": cadence["capacity_at_99_long_sessions"],
        "cadence_call_below": cadence["chosen"]["call_below"],
        "cadence_clean_every": cadence["chosen"]["clean_every"],
        "cadence_leg_minutes": cadence["chosen"]["leg"],
        "power_rule_in_order": round(arm["slot_1000"]["served"], 3),
        "power_rule_emptiest_first": round(arm["need_1000"]["served"], 3),
        "power_rule_long_sessions_in_order": round(apart["threshold+slot_power_1000"]["served"], 3),
        "power_rule_long_sessions_emptiest_first": round(apart["threshold+need_first_1000"]["served"], 3),
        "energy_saving": round(1.0 - arm["plan_500"]["cost_per_kwh"] / arm["threshold_500"]["cost_per_kwh"], 3),
        "energy_saving_long_sessions": round(
            1.0 - cost["plan_with_prices_500"]["cost_per_kwh"] / cost["threshold_500"]["cost_per_kwh"], 3
        ),
        "energy_saving_long_sessions_clock_only": round(
            1.0 - cost["plan_clock_only_500"]["cost_per_kwh"] / cost["threshold_500"]["cost_per_kwh"], 3
        ),
        "best_design": _best_design(sweep),
        "best_design_one_feeder": _best_design(sweep, "one_feeder"),
        "pretrained_error": reserve["C_chronos_1h"]["error"],
        "trained_here_error": reserve["A_reference_bound_1h"]["error"],
        "pretrained_reserve_vehicles": round(reserve["C_chronos_1h"]["reserve_at_95_achieved"], 1),
        "trained_here_reserve_vehicles": round(reserve["A_reference_bound_1h"]["reserve_at_95_achieved"], 1),
        "penetration_trips_per_resident_month": round(demand["penetration_trips_per_resident_month"], 2),
        "east_bay_vehicles_today": int(area["vehicles_at_25_rides"]),
        "months_to_second_feeder": area["months_until_second_feeder"],
        "months_to_second_feeder_at_half_growth": area["months_until_second_feeder_at_half_the_growth"],
    }


def statements(facts: dict | None = None) -> list[str]:
    """What each headline document must say, word for word. One list: the three do not get a figure each."""
    f = facts or public_facts()
    pct = lambda share: f"{100 * share:.1f}%"  # noqa: E731
    return [
        f"{f['bars_passed']} of {f['bars_total']} bars",
        f"about {f['capacity_one_feeder_at_99']} vehicles",
        pct(f["power_rule_in_order"]),
        pct(f["power_rule_emptiest_first"]),
        f"{f['east_bay_vehicles_today']} vehicles",
        f"{f['months_to_second_feeder']} months",
    ]


# The count of bars is quoted in many places. Wherever a public file says "N of M bars", it is this count.
BARS_QUOTED = re.compile(r"\b(\d+) of (\d+) bars\b")


def _public_files(root: Path) -> list[Path]:
    files = [root / name for name in (*DOCUMENTS, *OTHER_PUBLIC)]
    for pattern in PAGE_SOURCES:
        files += sorted(root.glob(pattern))
    return [path for path in files if path.exists()]


def problems(root: Path = Path(".")) -> list[str]:
    """Every headline a document should state and does not, and every other count of bars than the scoreboard's."""
    facts = public_facts()
    wrong = []
    wanted = statements(facts)
    for name in DOCUMENTS:
        text = (root / name).read_text()
        wrong += [f"{name}: does not say {phrase!r}" for phrase in wanted if phrase not in text]
    for path in _public_files(root):
        for passed, total in BARS_QUOTED.findall(path.read_text()):
            # A single test's own score ("4 of 4 bars") is not the project's count.
            if int(total) > 20 and (int(passed), int(total)) != (facts["bars_passed"], facts["bars_total"]):
                wrong.append(f"{path.relative_to(root)}: says {passed} of {total} bars")
    return wrong


def write(path: str | Path = "docs/FACTS.json") -> Path:
    """Write the facts beside the documents that quote them."""
    target = Path(path)
    target.write_text(json.dumps(public_facts(), indent=1) + "\n")
    return target
