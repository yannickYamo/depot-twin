"""Which code made which record, so a result cannot outlive the model it was measured on.

Every record under data/derived carries a stamp: a hash of the simulator's code, a hash of the forecasting
code, a hash of the modules that ran the test, and a hash of any other record or input file it was
computed from. A record is stale when a stamp it depends on no longer matches the tree. The code hashes
are taken over the code with comments and docstrings left out, so that rewording a comment does not ask
for an overnight run and changing a line of the model always does.

`depot-twin stale` lists stale records, and the suite fails while there are any that are not named, with
the reason, in data/derived/stale.json. What is not stamped: the downloaded public data the series are
built from (`data/raw`, the parquet caches), which change only when a publisher revises a file.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import tokenize
from functools import cache
from pathlib import Path

PACKAGE = Path(__file__).parent
ROOT = PACKAGE.parent.parent

# The code a result of each kind was measured on. Scenario files are part of the simulator: they hold its
# physics. So are the weekly demand shapes it draws rides from. The data loaders are in both groups; the
# builders of the page's files (`data/build.py`) read results and are in neither.
GROUPS: dict[str, tuple[str, ...]] = {
    "sim": (
        "resources.py",
        "interfaces.py",
        "sim.py",
        "grid.py",
        "control.py",
        "fleet.py",
        "dispatch.py",
        "heartbeat.py",
        "ledger.py",
        "steering.py",
        "replay.py",
        "twin.py",
        "trace.py",
        "guard.py",
        "growth.py",
        "sizing.py",
        "economics.py",
        "finance.py",
        "fares.py",
        "data",
        "evals/common.py",
        "../../scenarios",
        "../../data/derived/weekly_shape_sf.json",
        "../../data/derived/weekly_shape.json",
    ),
    "forecast": (
        "features.py",
        "models",
        "newsite.py",
        "synth.py",
        "workbench.py",
        "data",
        "../../data/splits.json",
        "evals/common.py",
    ),
}

SIM, FORECAST, BOTH = ("sim",), ("forecast",), ("sim", "forecast")
FOUNDATIONS = ("evals/foundations.py", "first_version")
CONTROL = ("evals/control.py",)
FORECASTS = ("evals/forecast.py", "evals/control.py")
MONEY = ("evals/money.py", "evals/control.py")
CADENCE = ("cadence.py",)
# Every result file: the groups it was measured on and the modules that ran it. A plan that reads forecast
# curves depends on both groups, whether or not the forecast change at hand could reach it.
RECORDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "e1_demand.json": (FORECAST, FOUNDATIONS),
    "e1_walk_forward.json": (FORECAST, FOUNDATIONS),
    "e2_recall.json": (SIM, FOUNDATIONS),
    "growth.json": (SIM, FOUNDATIONS),
    "e3_surrogate.json": (SIM, FOUNDATIONS),
    "e4_planner.json": (SIM, FOUNDATIONS),
    "e5_active.json": (SIM, FOUNDATIONS),
    "e6_identify.json": (SIM, FOUNDATIONS),
    "e7_forecasts.json": (FORECAST, FORECASTS),
    "e7b_scale_free.json": (FORECAST, FORECASTS),
    "e8_heartbeat.json": (BOTH, CONTROL),
    "growth_v2.json": (BOTH, CONTROL),
    "e9_ledger.json": (BOTH, CONTROL),
    "e10_guard.json": (BOTH, CONTROL),
    "e11_apart.json": (BOTH, CONTROL),
    "e12_cost.json": (BOTH, CONTROL),
    "session_length.json": (BOTH, CONTROL),
    "staffing.json": (BOTH, CONTROL),
    "e14_power_rules.json": (BOTH, CONTROL),
    "sensitivity.json": (BOTH, CONTROL),
    "e13_new_site.json": (BOTH, FORECASTS),
    "e15_worst_scenario.json": (BOTH, FORECASTS),
    "first_hour.json": (BOTH, FORECASTS),
    "e16_regret.json": (BOTH, FORECASTS),
    "e17_fixes.json": (FORECAST, FORECASTS),
    "e18_reserve.json": (FORECAST, FORECASTS),
    "e19_sweet_spot.json": (BOTH, MONEY),
    "e20_price_steering.json": (BOTH, MONEY),
    "e22_cadence.json": (BOTH, CADENCE),
    "e21_demand.json": (BOTH, CADENCE),
}
# Records computed from other files under data/derived: the test reads them, so a change in one of them
# makes the result stale. E21 counts vehicles against the capacity E22 measured.
UPSTREAM: dict[str, tuple[str, ...]] = {
    "e21_demand.json": ("e22_cadence.json", "footprint.json"),
}


def _code_only(source: str) -> str:
    """A module's code with its comments, docstrings and blank lines taken out.

    Done on the text, not on a dump of the parsed tree: the tree's printed form changes from one Python
    version to the next, and a stamp has to read the same on every version the suite runs on. The code is
    kept in one format by the formatter, so the text that remains moves only when the code does.
    """
    lines = source.split("\n")
    drop: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            drop.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, column = token.start
            lines[row - 1] = lines[row - 1][:column]
    kept = (line.rstrip() for number, line in enumerate(lines, start=1) if number not in drop)
    return "\n".join(line for line in kept if line)


def _digest(path: Path) -> bytes:
    """What a file contributes: its code for Python, its windows for the split registry, its bytes for anything else."""
    if path.suffix == ".py":
        return _code_only(path.read_text()).encode()
    if path.name == "splits.json":
        # The windows are what a result depends on: which days of which series serve which purpose. The
        # notes beside them are prose, and rewording a note does not change what any test ran on.
        windows = json.loads(path.read_text())["windows"]
        kept = [[w["id"], w["series"], w["from"], w["to"], w["purpose"]] for w in windows]
        return json.dumps(sorted(kept)).encode()
    return path.read_bytes()


def _files(entry: str) -> list[Path]:
    path = (PACKAGE / entry).resolve()
    if path.is_dir():
        return sorted(
            p
            for p in path.rglob("*")
            if p.suffix in (".py", ".toml", ".json") and "__pycache__" not in p.parts and p.name != "build.py"
        )
    return [path]


def file_hash(*paths: Path) -> str:
    """A short hash of files as they are on disk, for inputs that are data and not code."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


@cache
def code_hash(*entries: str) -> str:
    """A short hash of the code in the named files and folders."""
    digest = hashlib.sha256()
    for entry in entries:
        for path in _files(entry):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(_digest(path))
    return digest.hexdigest()[:12]


def stamp(name: str, folder: Path | None = None) -> dict[str, str]:
    """The stamp a record written now would carry. A file not in RECORDS is stamped on everything."""
    groups, drivers = RECORDS.get(name, (BOTH, ("evals/common.py",)))
    out = {**{group: code_hash(*GROUPS[group]) for group in groups}, "driver": code_hash(*drivers)}
    if name in UPSTREAM:
        folder = folder or ROOT / "data" / "derived"
        out["upstream"] = file_hash(*(folder / other for other in UPSTREAM[name]))
    return out


def stale(folder: Path) -> dict[str, str]:
    """Every result file whose stamp does not match the tree, with what differs."""
    out = {}
    for name in RECORDS:
        path = folder / name
        if not path.exists():
            continue
        carried = json.loads(path.read_text()).get("code")
        if not carried:
            out[name] = "no stamp"
            continue
        differs = [part for part, value in stamp(name, folder).items() if carried.get(part) != value]
        if differs:
            out[name] = "the tree has changed since it ran: " + ", ".join(differs)
    return out


def acknowledged(folder: Path) -> dict[str, str]:
    """The stale records the project has named, with why each is still there."""
    path = folder / "stale.json"
    return json.loads(path.read_text()) if path.exists() else {}
