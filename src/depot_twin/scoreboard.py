"""The scoreboard: every registered test and how it came out, generated from the result files.

EVALS.md is the full record and is written by hand. This page is the index, and it is generated, so it
cannot drift from the numbers: a test in the suite rebuilds it and fails if the committed copy differs.
"""

from __future__ import annotations

import json
from pathlib import Path

from depot_twin import provenance
from depot_twin.data import data_dir

# Every registered test, in order: id, result file, and the question it asked.
TESTS = (
    ("E1", "e1_demand.json", 'Does a week-ahead demand forecast beat "same hour last week"?'),
    ("E2", "e2_recall.json", "Do smarter recall rules serve more rides on a power-constrained depot?"),
    ("E3", "e3_surrogate.json", "Can gradient-boosted trees stand in for the simulator?"),
    ("E4", "e4_planner.json", "Can the stand-in be trusted with a search over depot designs?"),
    ("E5", "e5_active.json", "Does retraining on what the search picks let the search choose?"),
    ("E6", "e6_identify.json", "Can each vehicle's energy use be recovered from its telemetry?"),
    ("E7", "e7_forecasts.json", "Can rides be forecast 1, 6 and 24 hours ahead, with honest bounds?"),
    ("E7b", "e7b_scale_free.json", "Does forecasting the ratio to last week pass E7's bars?"),
    ("E8", "e8_heartbeat.json", "Does the heartbeat controller beat filling every free charger?"),
    ("E9", "e9_ledger.json", "Can the depot keep an hourly promise, and does E8 repeat on fresh days?"),
    ("E10", "e10_guard.json", "Does a guard catch a broken forecast and limit the damage?"),
    ("E11", "e11_apart.json", "Which part of the controller delivers the gain?"),
    ("E12", "e12_cost.json", "Does a plan that knows the price of energy cut its cost at equal service?"),
    ("E13", "e13_new_site.json", "Can a forecast be built for a place with no ride history?"),
    ("E14", "e14_power_rules.json", "Do the power-rule findings hold on another city's days?"),
    ("E15", "e15_worst_scenario.json", "Is the worst generated scenario a safe reading of a constrained depot?"),
    ("E16", "e16_regret.json", "What is a forecast worth to the plan, and does that depend on what binds?"),
    ("E17", "e17_fixes.json", "Do the model changes tighten the bound and cut error on days held back for it?"),
    (
        "E18",
        "e18_reserve.json",
        "At a required reliability, which forecast asks the fleet to hold the fewest vehicles?",
    ),
    ("E19", "e19_sweet_spot.json", "Where is the sweet spot, and what binds on either side of it?"),
    ("E20", "e20_price_steering.json", "Can the plan follow an hourly price?"),
    ("E22", "e22_cadence.json", "Does the twin survive the real visit cadence?"),
    ("E23", "e23_capacity.json", "What does one feeder carry, over many weeks and seeds, under three calling rules?"),
    ("E25", "e25_between.json", "Is the fleet halfway between the one carried and the one only served carried too?"),
    (
        "E26",
        "e26_margin.json",
        "What does one feeder carry if the vehicles use more energy than estimated?",
    ),
    ("E27", "e27_parked.json", "What does one feeder carry if a parked vehicle's systems stay on?"),
    ("E28", "e28_further.json", "How far does the plan of 600 hold?"),
    ("E29", "e29_steer.json", "What does the plan's cheaper energy cost in margin?"),
    ("E21", "e21_demand.json", "What does East Oakland ask of a depot, and when?"),
    ("E24", "e24_backtest.json", "Over 26 weeks in three series, which forecast is better and which bound holds?"),
)
# Tests best read beside another, with which.
READ_WITH = {
    "E2": "read with E11: these rules ran with power to the emptiest vehicle first",
    "E3": "read with E4: these runs measure two weekdays, E4 a full week",
    "E8": "read with E11: the gain came from the power rule, not the plan",
}


def _bars(result: dict) -> dict[str, bool] | None:
    """Return a result's bars, however that test stored them."""
    if "bars" in result:
        return {name: bool(passed) for name, passed in result["bars"].items()}
    if "passed" in result:
        return {"bar": bool(result["passed"])}
    return None


def rows(folder: Path | None = None) -> list[dict]:
    """Return one row per registered test that has been run."""
    folder = folder or data_dir() / "derived"
    out = []
    old = provenance.stale(folder)
    for ident, filename, question in TESTS:
        path = folder / filename
        if not path.exists():
            continue
        result = json.loads(path.read_text())
        bars = _bars(result)
        out.append(
            {
                "id": ident,
                "question": question,
                "passed": sum(bars.values()) if bars else None,
                "bars": len(bars) if bars else None,
                "missed": [name for name, ok in (bars or {}).items() if not ok],
                "run": result.get("run", ""),
                "note": READ_WITH.get(ident, ""),
                "current": filename not in old,
            }
        )
    return out


def _provenance_line(table: list[dict]) -> str:
    """Say whether every record was made by the code in the tree, and how many were not."""
    current = sum(r["current"] for r in table)
    if current == len(table):
        return (
            f"All {len(table)} records were made by the code in this tree: each carries a stamp of it, "
            "and `depot-twin stale` checks."
        )
    return (
        f"**{current} of the {len(table)} records were made by the code in this tree.** The rest are marked "
        "*stale*: the code has changed since they ran.\n"
    )


def render(folder: Path | None = None) -> str:
    """Return the scoreboard as a Markdown page."""
    table = rows(folder)
    scored = [r for r in table if r["bars"]]
    lines = [
        "# Scoreboard",
        "",
        "Generated from the result files by `depot-twin scoreboard`. Do not edit by hand. Each test's bars",
        "were fixed before its run; the registrations, results and what each one means are in",
        "[EVALS.md](../EVALS.md), and each test below links to its section there.",
        "",
        f"**{len(table)} tests run. {sum(r['passed'] for r in scored)} of {sum(r['bars'] for r in scored)} bars passed.**",
        "A missed bar is a result, not an omission.",
        "",
        _provenance_line(table),
        "",
        "| Test | Question | Bars passed | Record | Note |",
        "|---|---|---|---|---|",
    ]
    sections = _sections()
    for row in table:
        score = f"{row['passed']} of {row['bars']}" if row["bars"] else "no bars (attribution)"
        made = "current" if row["current"] else "*stale*"
        name = f"[{row['id']}](../EVALS.md#{sections[row['id']]})" if row["id"] in sections else row["id"]
        lines.append(f"| {name} | {row['question']} | {score} | {made} | {row['note']} |")
    lines += ["", "## Bars missed", ""]
    for row in table:
        for name in row["missed"]:
            lines.append(f"- **{row['id']}**: {name.replace('_', ' ')}")
    return "\n".join(lines) + "\n"


def _sections(record: Path = provenance.ROOT / "EVALS.md") -> dict[str, str]:
    """Each test's section in the record, as the link a Markdown viewer gives its heading."""
    import re

    out = {}
    for line in record.read_text().splitlines() if record.exists() else []:
        found = re.match(r"## (E\d+b?)\. ", line)
        if found:
            words = re.sub(r"[^a-z0-9 _-]", "", line[3:].lower())
            out[found.group(1)] = words.replace(" ", "-")
    return out


def write(path: str | Path = "docs/SCOREBOARD.md") -> Path:
    """Write the scoreboard and return its path."""
    path = Path(path)
    path.write_text(render())
    return path
