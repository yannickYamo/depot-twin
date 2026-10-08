"""Command line: run a scenario and print what happened."""

from __future__ import annotations

import argparse
import json
import sys

from depot_twin.control import POLICIES
from depot_twin.resources import load_scenario
from depot_twin.sim import DepotSim


def _run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario, seed=args.seed)
    result = DepotSim.from_scenario(scenario, policy=args.policy).run()
    summary = {"depot": scenario.depot.name, "policy": result.policy, "seed": args.seed, **result.summary()}
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    for key, value in summary.items():
        print(f"{key:>24}  {value:.2f}" if isinstance(value, float) else f"{key:>24}  {value}")
    return 0


RECALL_RULES = ("threshold", "headroom", "plan", "heartbeat")


def _recall_rule(name: str):
    """Build a recall rule by name. Imports are local so the simple rules do not need the optimizer or torch."""
    from depot_twin.fleet import ThresholdRecall

    if name == "threshold":
        return ThresholdRecall()
    if name == "heartbeat":
        from depot_twin.economics import Prices
        from depot_twin.heartbeat import Heartbeat

        # The plan as E12 settled it: told the price of energy, steering charging around the evening peak.
        return Heartbeat(
            ledger_adapt=0.2,
            ledger_level=0.975,
            ledger_from_state=True,
            prices=Prices(),
            pre_peak_hours=4.0,
            peak_call_below=0.15,
        )
    from depot_twin.dispatch import HeadroomRecall, RollingPlan

    return HeadroomRecall() if name == "headroom" else RollingPlan()


def _replay_demand(path: str, config):
    """Read a demand file written by `new-site` and scale it to the scenario's fleet."""
    import numpy as np

    from depot_twin.replay import ReplayDemand

    return ReplayDemand.scaled(dict(np.load(path)), config.size * config.rides_per_vehicle_day)


def _fleet(args: argparse.Namespace) -> int:
    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape

    config, depot = load_fleet_scenario(args.scenario)
    shape = load_weekly_shape(args.shape)
    rule = _recall_rule(args.recall)
    demand = _replay_demand(args.demand, config) if args.demand else None
    policy = args.policy or "slot_power"
    sim = FleetSim(config, depot, shape, rule, depot_policy=policy, seed=args.seed, demand=demand)
    summary = {"depot": depot.name, "recall": args.recall, "seed": args.seed, **sim.run(args.days).summary()}
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    for key, value in summary.items():
        print(f"{key:>30}  {value:.3f}" if isinstance(value, float) else f"{key:>30}  {value}")
    return 0


def _identify_energy(sim, config, rule, seed: int) -> None:
    """Have the plan work from each vehicle's energy use as estimated from its telemetry, as in the tests."""
    import numpy as np

    from depot_twin.twin import EnergyIdentifier

    nominal_drive = np.array([m.drive_kwh_per_mile for m in config.models])[sim.model_of]
    nominal_load = np.array([m.always_on_kw for m in config.models])[sim.model_of]
    sim.telemetry = EnergyIdentifier(nominal_drive, nominal_load, sim.capacity, seed=seed)
    rule.energy = sim.telemetry


def _trace(args: argparse.Namespace) -> int:
    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.trace import TraceRecorder, problems

    config, depot = load_fleet_scenario(args.scenario)
    depot = _within_the_site(depot)
    shape = load_weekly_shape(args.shape)
    rule = _recall_rule(args.recall)
    demand = _replay_demand(args.demand, config) if args.demand else None
    sim = FleetSim(config, depot, shape, rule, depot_policy=args.policy, seed=args.seed, demand=demand)
    if args.recall == "heartbeat":
        _identify_energy(sim, config, rule, args.seed)
    recorder = TraceRecorder(sim, label=args.label or f"{args.recall} + {args.policy}")
    sim.run(args.days)
    wrong = problems(recorder.to_dict())
    if wrong:
        print("\n".join(wrong))
        return 1
    print(f"wrote {recorder.export(args.out)}")
    return 0


def _within_the_site(depot):
    """Hold a scenario's chargers to what the site takes: two plugs for each one the usable connection feeds."""
    from dataclasses import replace

    from depot_twin.growth import charger_ceiling

    banks = []
    for bank in depot.chargers:
        ceiling = charger_ceiling(depot, bank.kw)
        if bank.count > ceiling:
            print(f"{bank.count} {bank.kind} chargers held to {ceiling}: the site feeds {ceiling // 2} at once")
        banks.append(replace(bank, count=min(bank.count, ceiling)))
    return replace(depot, chargers=tuple(banks))


def _data(args: argparse.Namespace) -> int:
    # Imported here so that running a scenario never needs the network code.
    from depot_twin.data.build import BUILDERS

    for name in args.tables or sorted(BUILDERS):
        print(f"wrote {BUILDERS[name]()}")
    return 0


def _report(args: argparse.Namespace) -> int:
    from depot_twin.report import build

    print(f"wrote {build(args.out)}")
    return 0


def _scoreboard(args: argparse.Namespace) -> int:
    from depot_twin.scoreboard import write

    print(f"wrote {write(args.out)}")
    return 0


def _facts(args: argparse.Namespace) -> int:
    from depot_twin import facts

    print(f"wrote {facts.write(args.out)}")
    wrong = facts.problems()
    print("\n".join(wrong) if wrong else "every public document agrees with the records")
    return 1 if wrong else 0


def _stale(args: argparse.Namespace) -> int:
    from depot_twin import provenance
    from depot_twin.data import data_dir

    old = provenance.stale(data_dir() / "derived")
    for name, why in sorted(old.items()):
        print(f"{name}: {why}")
    print(f"{len(old)} of {len(provenance.RECORDS)} records are stale")
    return 1 if old else 0


def _eval(args: argparse.Namespace) -> int:
    from depot_twin.evals import EVALS

    # Every evaluation at once is hours of compute and rewrites every record; it has to be asked for by name.
    if not args.names and not args.all:
        print("name the evaluations to run, or pass --all:\n  " + "  ".join(sorted(EVALS)))
        return 2
    for name in args.names or sorted(EVALS):
        print(f"wrote {EVALS[name]()}")
    return 0


def _kinds(text: str) -> dict[str, float]:
    """Parse a mix of kinds of place such as "outer=0.6,inner=0.4"."""
    from depot_twin.data.donors import KINDS

    mix = {name: float(share) for name, share in (part.split("=") for part in text.split(","))}
    unknown = set(mix) - set(KINDS)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown kind of place: {sorted(unknown)}; choose from {KINDS}")
    return mix


def _new_site(args: argparse.Namespace) -> int:
    """Generate demand for a site with no history, train its forecast, and say how wrong it may be."""
    from pathlib import Path

    import numpy as np
    import pandas as pd

    from depot_twin import newsite
    from depot_twin.data import data_dir

    site = newsite.Site(args.name, args.lat, args.lon, args.timezone, args.kinds, args.rides_per_hour)
    until = pd.Timestamp(args.until)
    first = newsite.monday_before(until, newsite.GENERATED_WEEKS) - pd.Timedelta(days=1)
    weather = newsite.weather_for((site.latitude, site.longitude, site.timezone), first, until)
    sources = newsite.Sources.load()
    forecasts = newsite.site_forecasts(sources, site, weather, until)
    out = Path(args.out) / site.name
    out.mkdir(parents=True, exist_ok=True)
    bounds = {}
    for horizon, forecast in forecasts.items():
        forecast.model.save_model(str(out / f"forecast_site_{horizon}h.json"))
        bounds[f"{horizon}h"] = {
            "upper_relative": forecast.upper_relative,
            "lower_relative": forecast.lower_relative,
            "trust": forecast.trust,
        }
    for scenario in range(args.scenarios):
        curves = newsite.site_demand(sources, site, forecasts, weather, until, seed=scenario)
        np.savez_compressed(out / f"demand_{scenario}.npz", **curves)
    tested = data_dir() / "derived" / "e13_new_site.json"
    expected = newsite.expected_error(json.loads(tested.read_text())) if tested.exists() else None
    summary = {"site": vars(site), "bounds": bounds, "expected_error": expected, "demand_files": args.scenarios}
    (out / "site.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {out}")
    for horizon, entry in (expected or {}).items():
        print(
            f"  {horizon:>3} ahead: in held-out cities the error was {entry['error_against_last_week_best']:.0%} to "
            f"{entry['error_against_last_week_worst']:.0%} of last week's curve's, and the upper bound held "
            f"{entry['upper_bound_held_least']:.0%} to {entry['upper_bound_held_most']:.0%} of the time (sized for 95%)"
        )
    return 0


def _app(args: argparse.Namespace) -> int:
    """Open the local operator's tool in the browser, on the full model."""
    import subprocess
    from pathlib import Path

    from depot_twin import app

    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(Path(app.__file__)), "--server.port", str(args.port)]
    )


def _package(args: argparse.Namespace) -> int:
    """Gather the trained models, their bounds and the model card into one folder for a release."""
    import shutil
    from pathlib import Path

    from depot_twin.data import data_dir

    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    (out / "workbench").mkdir(parents=True)
    derived = data_dir() / "derived"
    shipped = []
    for path in sorted(derived.glob("forecast_ratio_*.json")):
        shutil.copy(path, out / path.name)
        shipped.append(path.name)
    for path in sorted((derived / "workbench").glob("*.json")):
        shutil.copy(path, out / "workbench" / path.name)
        shipped.append(f"workbench/{path.name}")
    shutil.copy("docs/MODEL_CARD.md", out / "MODEL_CARD.md")
    shutil.copy("docs/SCOREBOARD.md", out / "SCOREBOARD.md")
    (out / "MANIFEST.txt").write_text("\n".join(shipped) + "\n")
    print(f"wrote {out} ({len(shipped)} model and score files)")
    return 0


def _add_site_command(commands) -> None:
    package = commands.add_parser("package", help="gather the trained models and the model card for a release")
    package.add_argument("--out", default="out/release")
    package.set_defaults(func=_package)
    tool = commands.add_parser(
        "app", help="the local operator's tool: the full model behind a few widgets (needs the app extra)"
    )
    tool.add_argument("--port", type=int, default=8501)
    tool.set_defaults(func=_app)
    site = commands.add_parser("new-site", help="generate demand and a forecast for a place with no ride history")
    site.add_argument("name")
    site.add_argument("--lat", type=float, required=True)
    site.add_argument("--lon", type=float, required=True)
    site.add_argument("--timezone", default="America/Los_Angeles")
    site.add_argument(
        "--kinds", type=_kinds, default={"outer": 1.0}, help='mix of kinds of place, e.g. "outer=0.6,inner=0.4"'
    )
    site.add_argument(
        "--rides-per-hour", type=float, required=True, help="expected rides an hour, averaged over the week"
    )
    site.add_argument("--until", default="2026-08-31", help="generate history up to this day, on its real weather")
    site.add_argument("--scenarios", type=int, default=5, help="how many two-week demand files to write")
    site.add_argument("--out", default="out/sites")
    site.set_defaults(func=_new_site)


def _add_simulation_commands(commands) -> None:
    run = commands.add_parser("run", help="run a scenario file")
    run.add_argument("scenario")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--policy", choices=sorted(POLICIES), default=None, help="override the scenario's control rule")
    run.add_argument("--json", action="store_true", help="print the summary as JSON")
    run.set_defaults(func=_run)
    fleet = commands.add_parser("fleet", help="run a driverless fleet against its depot")
    fleet.add_argument("scenario")
    fleet.add_argument("--days", type=float, default=7.0)
    fleet.add_argument("--seed", type=int, default=0)
    fleet.add_argument("--shape", default="data/derived/weekly_shape.json", help="weekly demand shape file")
    fleet.add_argument("--recall", choices=RECALL_RULES, default="headroom", help="rule for calling vehicles in")
    fleet.add_argument("--policy", choices=sorted(POLICIES), default=None, help="depot control rule")
    fleet.add_argument("--demand", default=None, help="replay a demand file written by new-site")
    fleet.add_argument("--json", action="store_true", help="print the summary as JSON")
    fleet.set_defaults(func=_fleet)


def _add_trace_command(commands) -> None:
    trace = commands.add_parser("trace", help="record a run step by step, for a viewer to replay")
    trace.add_argument("scenario")
    trace.add_argument("--out", default="out/trace.json")
    trace.add_argument("--days", type=float, default=2.0)
    trace.add_argument("--seed", type=int, default=0)
    trace.add_argument("--shape", default="data/derived/weekly_shape_sf.json", help="weekly demand shape file")
    trace.add_argument("--recall", choices=RECALL_RULES, default="heartbeat", help="rule for calling vehicles in")
    trace.add_argument("--policy", choices=sorted(POLICIES), default="slot_power", help="how power is shared")
    trace.add_argument("--label", default="", help="a name for the run, shown by viewers")
    trace.add_argument("--demand", default=None, help="replay a demand file: real days with the trained forecasts")
    trace.set_defaults(func=_trace)


def _add_build_commands(commands) -> None:
    data = commands.add_parser("data", help="rebuild derived tables from their public sources")
    data.add_argument("tables", nargs="*", help="tables to rebuild; all when omitted")
    data.set_defaults(func=_data)
    report = commands.add_parser("report", help="build the HTML report from the derived results")
    report.add_argument("--out", default="out/report.html")
    report.set_defaults(func=_report)
    board = commands.add_parser("scoreboard", help="regenerate docs/SCOREBOARD.md from the result files")
    board.add_argument("--out", default="docs/SCOREBOARD.md")
    board.set_defaults(func=_scoreboard)
    stated = commands.add_parser("facts", help="write the figures the documents quote, and check the documents")
    stated.add_argument("--out", default="docs/FACTS.json")
    stated.set_defaults(func=_facts)
    old = commands.add_parser("stale", help="list the result files made by code that has since changed")
    old.set_defaults(func=_stale)
    evals = commands.add_parser("eval", help="run the evaluations registered in EVALS.md")
    evals.add_argument("names", nargs="*", help="evaluations to run, by their names in EVALS.md")
    evals.add_argument("--all", action="store_true", help="run every registered evaluation (hours)")
    evals.set_defaults(func=_eval)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the depot-twin command."""
    parser = argparse.ArgumentParser(prog="depot-twin", description="A digital twin of a robotaxi depot.")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_simulation_commands(commands)
    _add_build_commands(commands)
    _add_trace_command(commands)
    _add_site_command(commands)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
