"""Which code made which record, so a result cannot outlive the model it was measured on.

Every record under data/derived carries a stamp: a hash of the simulator's code, a hash of the forecasting
code, a hash of the modules that ran the test, and a hash of any other record or input file it was
computed from. A record is stale when a stamp it depends on no longer matches the tree. The code hashes
are taken over the code with comments and docstrings left out, so that rewording a comment does not ask
for an overnight run and changing a line of the model always does.

Page files, figures, `docs/FACTS.json` and the committed site plans are stamped the same way (`PAGE`),
and a plan also keeps a hash of its site file and demand files. `depot-twin stale` lists stale records, and the suite fails while there are any that are not named, with
the reason, in data/derived/stale.json. What is not stamped: the downloaded public data the series are
built from (`data/raw`, the parquet caches), which change only when a publisher revises a file.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import tokenize
import tomllib
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
        # The demand and forecasts every replayed depot run reads, as committed.
        "../../data/reproduce",
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
WIDE = ("evals/wide.py",)
MARGIN = ("evals/margin.py",)
PARKED = ("evals/margin.py", "evals/parked.py")
FURTHER = ("evals/margin.py", "evals/parked.py", "evals/further.py")
MIX = ("evals/parked.py", "evals/mix.py")
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
    "session_length.json": (BOTH, CONTROL + WIDE),
    "staffing.json": (BOTH, CONTROL + WIDE),
    "e14_power_rules.json": (BOTH, CONTROL),
    "sensitivity.json": (BOTH, CONTROL + WIDE),
    "e13_new_site.json": (BOTH, FORECASTS),
    "e15_worst_scenario.json": (BOTH, FORECASTS),
    "first_hour.json": (BOTH, FORECASTS),
    "e16_regret.json": (BOTH, FORECASTS),
    "e17_fixes.json": (FORECAST, FORECASTS),
    "e18_reserve.json": (FORECAST, FORECASTS),
    "e19_sweet_spot.json": (BOTH, MONEY + WIDE),
    "e20_price_steering.json": (BOTH, MONEY),
    "e22_cadence.json": (BOTH, CADENCE),
    "e23_capacity.json": (BOTH, CADENCE),
    "e21_demand.json": (BOTH, CADENCE),
    "e24_backtest.json": (FORECAST, FORECASTS),
    "e25_between.json": (BOTH, CADENCE + WIDE),
    "e26_margin.json": (BOTH, CADENCE + MARGIN),
    "e27_parked.json": (BOTH, CADENCE + PARKED),
    "e28_further.json": (BOTH, CADENCE + FURTHER),
    "e29_steer.json": (BOTH, CADENCE + ("evals/parked.py", "evals/steer.py")),
    "e30_mix.json": (BOTH, CADENCE + MIX),
    "e31_new_vehicle.json": (BOTH, CADENCE + MIX),
    "e32_range.json": (BOTH, CADENCE + MIX),
    "e33_chargers.json": (BOTH, CADENCE + MIX + ("evals/chargers.py",)),
    "e34_two_feeders.json": (BOTH, CADENCE + MIX + ("evals/chargers.py", "evals/feeders.py")),
}
# Records computed from other files under data/derived: the test reads them, so a change in one of them
# makes the result stale. E23 runs at the cadence setting E22 chose, and E21 counts vehicles against the
# capacity E23 measured.
UPSTREAM: dict[str, tuple[str, ...]] = {
    "e23_capacity.json": ("e22_cadence.json",),
    "e21_demand.json": ("e23_capacity.json", "footprint.json"),
    "e25_between.json": ("e23_capacity.json",),
    "e26_margin.json": ("e23_capacity.json", "e25_between.json"),
    "e27_parked.json": ("e23_capacity.json", "e26_margin.json"),
    "e28_further.json": ("e23_capacity.json", "e26_margin.json"),
    "e29_steer.json": ("e23_capacity.json",),
    "e30_mix.json": ("e23_capacity.json", "e26_margin.json"),
    "e31_new_vehicle.json": ("e23_capacity.json", "e30_mix.json"),
    "e32_range.json": ("e23_capacity.json", "e26_margin.json"),
    "e33_chargers.json": ("e23_capacity.json", "e30_mix.json"),
    "e34_two_feeders.json": ("e23_capacity.json",),
}


def _docstring_lines(node: ast.AST) -> range:
    """The lines a module's, class's or function's docstring covers, or none."""
    body = getattr(node, "body", None)
    if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not body:
        return range(0)
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return range(first.lineno, (first.end_lineno or first.lineno) + 1)
    return range(0)


def _code_only(source: str) -> str:
    """A module's code with its comments, docstrings and blank lines taken out.

    Done on the text, not on a dump of the parsed tree: the tree's printed form changes from one Python
    version to the next, and a stamp has to read the same on every version the suite runs on. The code is
    kept in one format by the formatter, so the text that remains moves only when the code does. A string
    over several lines is data, and is kept exactly: its blank lines and trailing spaces are part of the program.
    """
    lines = source.split("\n")
    drop: set[int] = set()
    inside_text: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        drop.update(_docstring_lines(node))
        if isinstance(node, (ast.Constant, ast.JoinedStr)) and (node.end_lineno or node.lineno) > node.lineno:
            inside_text.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, column = token.start
            lines[row - 1] = lines[row - 1][:column]
    kept = [
        line if number in inside_text else line.rstrip()
        for number, line in enumerate(lines, start=1)
        if number not in drop and (number in inside_text or line.strip())
    ]
    return "\n".join(kept)


def _arrays(path: Path) -> bytes:
    """The arrays in a stored file, by name: the file's own bytes carry the time it was written."""
    import numpy as np

    with np.load(path) as stored:
        return b"".join(name.encode() + np.ascontiguousarray(stored[name]).tobytes() for name in sorted(stored.files))


REPLAYED = ("2024-03-18", "2024-04-15", "2024-04-29", "2024-05-13")  # the four fortnights the depot tests replay


def replay_problems(root: Path = ROOT) -> dict[str, str]:
    """Every replayed fortnight whose committed curves are missing, or differ from the ones the tree would use.

    The depot tests read curves made from the fitted forecasts. The committed copies are part of every
    result's stamp. Where the fitted forecasts are present, the curves they give must be the committed
    ones; where they are not, as on a fresh clone, the committed ones are what runs.
    """
    from depot_twin.evals import common

    out = {}
    for start in REPLAYED:
        committed = root / "data" / "reproduce" / f"replay_{start}.npz"
        if not committed.exists():
            out[committed.name] = "not committed"
            continue
        if not list((root / "data" / "derived").glob("forecast_ratio_*h.json")):
            continue
        local = common.replay_cache(start)
        if not local.exists():
            out[committed.name] = "the fitted forecasts have no curves yet: run `depot-twin data reproduce`"
        elif _arrays(local) != _arrays(committed):
            out[committed.name] = "differs from the curves the fitted forecasts give: run `depot-twin data reproduce`"
    return out


def _digest(path: Path) -> bytes:
    """What a file contributes: its code for Python, its values for a scenario, its windows for the split registry, its bytes for anything else."""
    if path.suffix == ".py":
        return _code_only(path.read_text()).encode()
    if path.suffix == ".npz":
        return _arrays(path)
    if path.suffix == ".toml":
        # A scenario is its values. A comment beside one is prose, as in a module.
        return json.dumps(tomllib.loads(path.read_text()), sort_keys=True, default=str).encode()
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
            if p.suffix in (".py", ".toml", ".json", ".npz") and "__pycache__" not in p.parts and p.name != "build.py"
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


# The files the page and the documents read that are not test records: the groups and modules each was built
# by, and the records it was built from. A figure quoted from one of these is tied to its code like any other.
PAGE: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "web/public/models.json": (BOTH, ("workbench.py",), ()),
    "web/public/trust.json": (BOTH, ("trust.py", "workbench.py"), ()),
    "data/derived/workbench/*.json": (BOTH, ("workbench.py",), ()),
    "web/public/money.json": ((), ("data/build.py",), ("data/derived/e19_sweet_spot.json",)),
    "web/public/backtest.json": ((), ("backtest_page.py",), ("data/derived/e24_backtest.json",)),
    "web/public/demand.json": (
        (),
        ("data/build.py", "analysis.py"),
        (
            "data/derived/e21_demand.json",
            "data/derived/e23_capacity.json",
            "data/derived/e25_between.json",
            "data/derived/e26_margin.json",
            "data/derived/footprint.json",
        ),
    ),
    "web/public/facts.json": (
        (),
        ("data/build.py",),
        ("data/derived/e7b_scale_free.json", "data/derived/e13_new_site.json"),
    ),
    # The runs the page plays back, and the Python side of the browser parity test. The forecast view's own
    # recordings (traces/model_*.json) are written by the build of models.json and stand under its stamp.
    "web/public/traces/stamp.json": (BOTH, ("trace.py",), ()),
    "web/tests/reference_stamp.json": (("sim",), ("fleet.py",), ()),
    "data/derived/account_study.json": (
        (),
        ("analysis.py", "finance.py", "economics.py", "cadence.py"),
        (
            "data/derived/e19_sweet_spot.json",
            "data/derived/e21_demand.json",
            "data/derived/e23_capacity.json",
            "data/derived/e25_between.json",
            "data/derived/e26_margin.json",
            "data/derived/footprint.json",
        ),
    ),
    # The claim ledger and the documents' figures: built from records, so stale when a record or their code moves.
    "docs/FACTS.json": (
        (),
        ("facts.py", "analysis.py", "scoreboard.py"),
        (
            "sites/plans/east_oakland.json",
            "sites/plans/shape_chicago.json",
            "sites/plans/shape_new_york.json",
            "sites/plans/shape_san_francisco_hourly.json",
            "data/derived/e21_demand.json",
            "data/derived/e23_capacity.json",
            "data/derived/e24_backtest.json",
            "data/derived/e24_baseline.json",
            "data/derived/sensitivity.json",
            "data/derived/capacity_spread.json",
            "data/derived/e25_between.json",
            "data/derived/e26_margin.json",
            "data/derived/e27_parked.json",
            "data/derived/e28_further.json",
            "data/derived/e29_steer.json",
            "data/derived/e30_mix.json",
            "data/derived/e31_new_vehicle.json",
            "data/derived/e32_range.json",
            "data/derived/e33_chargers.json",
            "data/derived/e34_two_feeders.json",
            "data/derived/account_study.json",
        ),
    ),
    "docs/images/stamp.json": (
        (),
        ("figures.py", "analysis.py"),
        (
            "data/derived/e21_demand.json",
            "data/derived/e23_capacity.json",
            "data/derived/e25_between.json",
            "data/derived/e26_margin.json",
            "data/derived/e27_parked.json",
            "data/derived/account_study.json",
        ),
    ),
    # Plans made from site files (`depot-twin plan`): the simulator, the planner and the parked-load method.
    "sites/plans/*.json": (("sim",), ("siteplan.py", "cadence.py", "evals/parked.py"), ()),
    "data/derived/capacity_spread.json": (
        (),
        ("analysis.py",),
        ("data/derived/e23_capacity.json", "data/derived/e26_margin.json"),
    ),
    "data/derived/e24_baseline.json": (FORECAST, ("baseline.py",), ("data/derived/e24_backtest.json",)),
    "data/derived/e24_blocks.json": ((), ("blocks.py",), ("data/derived/e24_backtest.json",)),
    "web/public/outcome.json": (
        (),
        ("data/build.py", "analysis.py"),
        (
            "data/derived/e19_sweet_spot.json",
            "data/derived/e21_demand.json",
            "data/derived/e23_capacity.json",
            "data/derived/e25_between.json",
            "data/derived/e26_margin.json",
            "data/derived/e27_parked.json",
            "data/derived/e29_steer.json",
            "data/derived/e30_mix.json",
            "data/derived/e31_new_vehicle.json",
            "data/derived/e32_range.json",
            "data/derived/e33_chargers.json",
            "data/derived/e34_two_feeders.json",
            "data/derived/account_study.json",
        ),
    ),
}


def page_stamp(entry: str, root: Path = ROOT) -> dict[str, str]:
    """The stamp a page file written now would carry. `entry` is its key in PAGE."""
    groups, drivers, upstream = PAGE[entry]
    out = {**{group: code_hash(*GROUPS[group]) for group in groups}, "driver": code_hash(*drivers)}
    if upstream:
        out["upstream"] = file_hash(*(root / other for other in upstream))
    return out


def _inputs_moved(plan: Path, root: Path) -> bool:
    """Whether the site file a committed plan was made from, or a demand file it names, has changed since."""
    from depot_twin import siteplan

    file = root / "sites" / f"{plan.stem}.toml"
    kept = json.loads(plan.read_text()).get("made_from")
    try:
        return kept != siteplan.made_from(file, siteplan.load(file, allow_unusual=True))
    except siteplan.SiteError:  # a site file that is gone or no longer loads has moved
        return True


def stale_pages(root: Path = ROOT) -> dict[str, str]:
    """Every page file whose stamp does not match the tree, with what differs."""
    out = {}
    for entry in PAGE:
        for path in sorted(root.glob(entry)):
            carried = json.loads(path.read_text()).get("code")
            name = str(path.relative_to(root))
            if not carried:
                out[name] = "no stamp"
                continue
            differs = [part for part, value in page_stamp(entry, root).items() if carried.get(part) != value]
            if entry == "sites/plans/*.json" and _inputs_moved(path, root):
                differs.append("its site file or demand files")
            if differs:
                out[name] = "the tree has changed since it was built: " + ", ".join(differs)
    return out


def acknowledged(folder: Path) -> dict[str, str]:
    """The stale records the project has named, with why each is still there."""
    path = folder / "stale.json"
    return json.loads(path.read_text()) if path.exists() else {}
