"""E1 to E6: the first version's tests, from the demand model to the identification of the twin's own parameters.

Each function corresponds to one entry in EVALS.md; the registration there fixes the data, the split, the
metric and the bar before the run it reports, and this module only executes it.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from depot_twin.data import data_dir
from depot_twin.evals.common import _write
from depot_twin.fleet import served_share


def e1_demand(last_day: date = date(2026, 8, 31)) -> Path:
    """E1: week-ahead demand forecast against "same hour last week" on the final 91 days."""
    from depot_twin.data import chicago
    from depot_twin.models import demand

    frame = demand.hourly_frame(chicago.fetch_hours(last=last_day))
    model, result = demand.backtest(frame)
    model_path = data_dir() / "derived" / "demand_model.json"
    model.save_model(str(model_path))
    # The simulation consumes a typical week: the forecast for the last week, as shares of weekly demand.
    shape = demand.weekly_shape(model, frame)
    _write("weekly_shape.json", {"first_hour": "Monday 00:00", "shares": [round(float(x), 6) for x in shape]})
    return _write(
        "e1_demand.json",
        {
            "eval": "E1",
            "data": {"first": str(frame.index.min()), "last": str(frame.index.max()), "hours": len(frame)},
            "train_cutoff": result.cutoff,
            "holdout_hours": result.hours,
            "model_wape": round(result.model_wape, 4),
            "naive_wape": round(result.naive_wape, 4),
            "error_removed": round(result.improvement, 4),
            "bar": 0.15,
            "passed": bool(result.improvement >= 0.15),
            "run": date.today().isoformat(),
        },
    )


def e1_walk_forward(last_day: date = date(2026, 8, 31)) -> Path:
    """A robustness report for E1: four earlier windows, none touching the held-out period. No bar."""
    from depot_twin.data import chicago
    from depot_twin.models import demand

    frame = demand.hourly_frame(chicago.fetch_hours(last=last_day))
    return _write("e1_walk_forward.json", {"windows": demand.walk_forward(frame), "run": date.today().isoformat()})


E2_SEEDS = tuple(range(101, 111))
E2_SIZES = (500, 1000)
E2_RULES = ("threshold", "headroom", "plan", "learned")


def _e2_run(task: tuple[str, int, int]) -> dict:
    from depot_twin.dispatch import HeadroomRecall, RollingPlan
    from depot_twin.first_version.policy import LearnedRecall
    from depot_twin.first_version.train import MODEL_PATH
    from depot_twin.fleet import FleetSim, ThresholdRecall, load_fleet_scenario, load_weekly_shape

    rule_name, size, seed = task
    rules = {
        "threshold": ThresholdRecall,
        "headroom": HeadroomRecall,
        "plan": RollingPlan,
        "learned": lambda: LearnedRecall(MODEL_PATH),
    }
    fleet, depot = load_fleet_scenario(f"scenarios/east_oakland_{size}.toml")
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape.json")
    # Eight days with the last seven measured: the first day is the fleet settling from its starting charge.
    result = FleetSim(fleet, depot, shape, rules[rule_name](), seed=seed).run(8)
    summary = result.summary()
    return {
        "rule": rule_name,
        "size": size,
        "seed": seed,
        "served": served_share(result.steps[result.steps[:, 0] >= 1440.0]),
        "at_peak": summary["available_at_peak_share"],
        "stranded": summary["stranded"],
    }


def e2_recall(workers: int = 5) -> Path:
    """E2: four recall rules on the constrained depot, ten held-out seeds each."""
    from concurrent.futures import ProcessPoolExecutor

    tasks = [(rule, size, seed) for rule in E2_RULES for size in E2_SIZES for seed in E2_SEEDS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_e2_run, tasks))
    table = {}
    for rule in E2_RULES:
        for size in E2_SIZES:
            group = [r for r in runs if r["rule"] == rule and r["size"] == size]
            served = [r["served"] for r in group]
            table[f"{rule}_{size}"] = {
                "served_mean": round(sum(served) / len(served), 4),
                "served_min": round(min(served), 4),
                "served_max": round(max(served), 4),
                "at_peak_mean": round(sum(r["at_peak"] for r in group) / len(group), 4),
                "stranded": sum(r["stranded"] for r in group),
            }
    mean = {key: value["served_mean"] for key, value in table.items()}
    best_hand = max(mean["threshold_1000"], mean["headroom_1000"], mean["plan_1000"])
    bars = {
        "1_headroom_beats_threshold_by_2pt_at_1000": mean["headroom_1000"] - mean["threshold_1000"] >= 0.02,
        "2a_plan_no_worse_than_headroom_at_500": mean["plan_500"] >= mean["headroom_500"],
        "2b_plan_within_half_pt_of_headroom_at_1000": mean["plan_1000"] >= mean["headroom_1000"] - 0.005,
        "3_learned_beats_threshold_at_1000": mean["learned_1000"] > mean["threshold_1000"],
        "4_learned_within_1pt_of_best_hand_rule_at_1000": mean["learned_1000"] >= best_hand - 0.01,
    }
    return _write(
        "e2_recall.json",
        {"eval": "E2", "seeds": list(E2_SEEDS), "table": table, "bars": bars, "run": date.today().isoformat()},
    )


def growth_study() -> Path:
    """The growth study: fleet sizes from 200 to 2,000 under each grid option."""
    from depot_twin import growth

    sizes = [200, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000]
    rows = growth.sweep(sizes, seeds=[11, 12, 13])
    limits = {
        option: {
            "serves_99pct_up_to": growth.largest_fleet(rows, option, 0.99),
            "serves_95pct_up_to": growth.largest_fleet(rows, option, 0.95),
            "hand_check": growth.hand_check(growth.OPTIONS[option]["site_limit_kw"]),
        }
        for option in growth.OPTIONS
    }
    return _write("growth.json", {"rule": "headroom", "rows": rows, "limits": limits, "run": date.today().isoformat()})


E3_CASES = (
    {"size": 500.0, "site_limit_kw": 2750.0},
    {"size": 1000.0, "site_limit_kw": 2750.0},
    {"size": 1500.0, "site_limit_kw": 5500.0},
)
E3_GIVEN = {"rides_per_vehicle_day": 25.0, "peak_gamma": 1.0, "kwh_per_mile": 0.40}


def _e3_rows() -> list[dict]:
    """Return the design sweep, running it only if it is not already on disk."""
    from depot_twin.first_version import surrogate

    path = data_dir() / "derived" / "surrogate_runs.json"
    if path.exists():
        return json.loads(path.read_text())
    designs = surrogate.sample_designs(1600, seed=0)
    rows = surrogate.run_designs(designs, seeds=[0]) + surrogate.run_designs(designs[:200], seeds=[1])
    path.write_text(json.dumps(rows) + "\n")
    return rows


def _e3_use_cases(models: dict) -> list[dict]:
    """Let the trees pick a design for each case, then ask the simulator what that design really does."""
    from depot_twin.first_version import surrogate

    cases = []
    for case in E3_CASES:
        pick = surrogate.best_design(models, {**E3_GIVEN, **case})
        actual = surrogate.simulate(pick["design"], seed=7)
        actual_value = surrogate.contribution(pick["design"], actual)
        cases.append(
            {
                "case": case,
                "design": {k: round(v, 3) for k, v in pick["design"].items() if k in surrogate.CHOICES},
                "predicted_served": round(pick["predicted"]["served_share"], 4),
                "simulated_served": round(actual["served_share"], 4),
                "predicted_contribution": round(pick["predicted_contribution"], 2),
                "simulated_contribution": round(actual_value, 2),
            }
        )
    return cases


def e3_surrogate() -> Path:
    """E3: XGBoost as a stand-in for the simulator, with the split and the bars registered in EVALS.md."""
    import numpy as np

    from depot_twin.first_version import surrogate

    rows = _e3_rows()
    first = [r for r in rows if r["seed"] == 0]
    parts = surrogate.split(first)
    models, report = surrogate.train_all(parts)
    surrogate.save_models(models, data_dir() / "derived" / "surrogate")

    served = report["served_share"]
    test = parts["test"]
    hand = float(np.mean([abs(surrogate.hand_estimate(r) - r["served_share"]) for r in test]))
    hard = [r for r in test if r["served_share"] < 0.99]
    hard_mae = surrogate.mae(models["served_share"], hard, "served_share")
    cases = _e3_use_cases(models)
    gains = models["served_share"].get_booster().get_score(importance_type="gain")
    total_gain = sum(gains.values())
    bars = {
        "1_test_mae_at_most_1.5pt": served["test_mae"] <= 0.015,
        "2_at_most_half_the_spreadsheet_error": served["test_mae"] <= 0.5 * hand,
        "3_constrained_designs_mae_at_most_3pt": hard_mae <= 0.03,
        "4_test_at_most_1.3x_validation": served["test_mae"] <= 1.3 * served["valid_mae"],
        "5_gap_mae_at_most_2.5pt": served["gap_mae"] <= 0.025,
        "6_picked_designs_hold_up_in_simulation": all(
            abs(c["predicted_served"] - c["simulated_served"]) <= 0.02
            and abs(c["predicted_contribution"] - c["simulated_contribution"])
            <= 0.05 * abs(c["simulated_contribution"])
            for c in cases
        ),
    }
    return _write(
        "e3_surrogate.json",
        {
            "eval": "E3",
            "rows": {name: len(part) for name, part in parts.items()},
            "models": report,
            "spreadsheet_test_mae": round(hand, 5),
            "constrained_test_designs": len(hard),
            "constrained_test_mae": round(hard_mae, 5),
            "noise_floor": {t: round(surrogate.noise_floor(rows[:200] + rows[1600:], t), 5) for t in surrogate.TARGETS},
            "top_features": sorted(((k, round(v / total_gain, 3)) for k, v in gains.items()), key=lambda kv: -kv[1])[
                :6
            ],
            "use_cases": cases,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


E4_CASES = (
    {"size": 400.0, "site_limit_kw": 2750.0},
    {"size": 600.0, "site_limit_kw": 2750.0},
    {"size": 1000.0, "site_limit_kw": 5500.0},
)
E4_INFEASIBLE = {"size": 1000.0, "site_limit_kw": 2750.0}


def _cached(name: str, make) -> list:
    """Return a list stored under data/derived, building and storing it on first use."""
    path = data_dir() / "derived" / name
    if path.exists():
        return json.loads(path.read_text())
    value = make()
    path.write_text(json.dumps(value) + "\n")
    return value


def _e4_pool() -> list[dict]:
    from depot_twin.first_version import planner, surrogate

    def make():
        space = planner.sample_sobol(1000, seed=10, first_id=0)
        edge = planner.sample_boundary(1000, seed=20, first_id=100_000)
        week = surrogate.WEEK_RUN_DAYS
        first = surrogate.run_designs(space + edge, seeds=[0], run_days=week)
        return first + surrogate.run_designs(space[:100] + edge[:100], seeds=[1], run_days=week)

    return _cached("e4_runs.json", make)


def _e4_prospective() -> list[dict]:
    from depot_twin.first_version import planner, surrogate

    def make():
        fresh = planner.sample_sobol(150, seed=3000, first_id=200_000)
        fresh += planner.sample_boundary(150, seed=4000, first_id=300_000)
        return surrogate.run_designs(fresh, seeds=[0], run_days=surrogate.WEEK_RUN_DAYS)

    return _cached("e4_prospective.json", make)


def _simulated(designs: list[dict], seed: int) -> list[dict]:
    """Simulate designs and attach the true contribution per vehicle to each."""
    from depot_twin.first_version import surrogate

    rows = surrogate.run_designs(designs, seeds=[seed], run_days=surrogate.WEEK_RUN_DAYS)
    for row, design in zip(rows, designs, strict=True):
        row["true_value"] = surrogate.contribution(design, row)
    return rows


def _e4_search_case(plan, case: dict) -> dict:
    """Rank candidates for one case, simulate the top 50 and 100 at random, and measure the gap."""
    import numpy as np
    from scipy.stats import spearmanr

    from depot_twin.first_version import planner

    pool = planner.candidates({**E3_GIVEN, **case}, seed=1)
    top = planner.rank(plan, pool, top=50)
    if not top:
        # The planner found nothing it would accept. Recorded as the worst outcome on every measure.
        empty = {"regret": 1.0, "top50_serving_99pct": 0, "top50_worst_served": 0.0, "simulated_served": 0.0}
        return {"case": case, "offered": 0, **empty}
    picks = np.random.default_rng(5).choice(len(pool), size=100, replace=False)
    reference = [pool[int(n)] for n in picks]
    designs = [t["design"] for t in top] + reference
    rows = _simulated(designs, seed=7)
    outcomes = plan.predict(designs)
    predicted = planner._values(designs, outcomes, None)
    true = np.array([r["true_value"] for r in rows])
    served = np.array([r["served_share"] for r in rows])
    best = float(true[served >= planner.SERVICE_LEVEL].max())
    head = served[: len(top)]
    return {
        "case": case,
        "picked": {k: round(v, 3) for k, v in top[0]["design"].items() if k in planner.CHOICES},
        "predicted_served": round(top[0]["predicted_served"], 4),
        "simulated_served": round(float(served[0]), 4),
        "predicted_value": round(top[0]["predicted_value"], 2),
        "simulated_value": round(float(true[0]), 2),
        "best_simulated_value": round(best, 2),
        "regret": round((best - float(true[0])) / best, 4),
        "top50_serving_99pct": int((head >= planner.SERVICE_LEVEL).sum()),
        "top50_worst_served": round(float(head.min()), 4),
        "rank_correlation": round(float(spearmanr(predicted, true).statistic), 3),
    }


def _e4_robust_case(plan, case: dict) -> dict:
    """Pick one design on expected demand and one across scenarios, and simulate both under fresh scenarios."""
    from depot_twin.first_version import planner, surrogate

    pool = planner.candidates({**E3_GIVEN, **case}, seed=1)
    # The planner may accept nothing: its margin can be wider than the room any design has above the service level.
    offered = planner.rank(plan, pool, top=1)
    nominal = offered[0]["design"] if offered else None
    robust_pick = planner.rank_robust(plan, pool, planner.demand_scenarios(40, seed=0), top=1)
    fresh = planner.demand_scenarios(20, seed=99)
    out = {"case": case}
    for label, design in (("expected", nominal), ("robust", robust_pick[0]["design"] if robust_pick else None)):
        if design is None:
            out[label] = None
            continue
        faced = [{**planner.under(design, scenario), "id": n} for n, scenario in enumerate(fresh)]
        rows = surrogate.run_designs(faced, seeds=[11], run_days=surrogate.WEEK_RUN_DAYS)
        out[label] = {
            "design": {k: round(v, 3) for k, v in design.items() if k in planner.CHOICES},
            "scenarios_serving_99pct": sum(r["served_share"] >= planner.SERVICE_LEVEL for r in rows),
            "worst_served": round(min(r["served_share"] for r in rows), 4),
            "value": round(surrogate.contribution(design, plan_outcome(plan, design)), 2),
        }
    return out


def plan_outcome(plan, design: dict) -> dict:
    """Return the planner's predicted outcome for one design as plain numbers."""
    outcomes = plan.predict([design])
    return {target: float(values[0]) for target, values in outcomes.items()}


def _in_range(outcomes: dict) -> bool:
    shares_ok = all(((outcomes[t] >= 0.0) & (outcomes[t] <= 1.0)).all() for t in ("served_share", "peak_period_share"))
    return bool(shares_ok and (outcomes["kwh_per_vehicle_day"] > 0.0).all())


def e4_planner() -> Path:
    """E4: the planner, with boundary sampling, bounded targets, a regret test and a robustness test."""
    from depot_twin.first_version import planner, surrogate

    rows = _e4_pool()
    first = [r for r in rows if r["seed"] == 0]
    parts = surrogate.split(first)
    plan, report = planner.train(parts)
    for target, model in plan.models.items():
        model.save_model(str(data_dir() / "derived" / f"planner_{target}.json"))

    # Everything above is frozen before the prospective designs are generated or simulated.
    fresh = _e4_prospective()
    band = [r for r in fresh if 0.95 <= r["served_share"] < 0.999]
    prospective, band_mae = plan.mae("served_share", fresh), plan.mae("served_share", band)
    search = [_e4_search_case(plan, case) for case in E4_CASES]
    robust = [_e4_robust_case(plan, case) for case in E4_CASES]
    impossible = planner.rank(plan, planner.candidates({**E3_GIVEN, **E4_INFEASIBLE}, seed=1), top=1)
    served = report["served_share"]
    bars = {
        "1_prospective_mae_at_most_1.5pt_overall_and_in_the_95_to_99.9_band": prospective <= 0.015
        and band_mae <= 0.015,
        "2_prospective_at_most_1.3x_validation": prospective <= 1.3 * served["valid_mae"],
        "3_gap_mae_at_most_2.5pt": served["gap_mae"] <= 0.025,
        "4_regret_and_top50_hold_in_every_case": all(
            c["regret"] <= 0.02 and c["top50_serving_99pct"] >= 40 and c["top50_worst_served"] >= 0.97 for c in search
        ),
        "5_no_design_offered_for_the_infeasible_case": len(impossible) == 0,
        "6_robust_design_holds_in_18_of_20": all(
            c["robust"] and c["robust"]["scenarios_serving_99pct"] >= 18 for c in robust
        ),
        "7_predictions_inside_physical_range": _in_range(plan.predict(fresh)),
    }
    replicated = [r for r in rows if r["id"] < 100 or 100_000 <= r["id"] < 100_100]
    return _write(
        "e4_planner.json",
        {
            "eval": "E4",
            "rows": {**{name: len(part) for name, part in parts.items()}, "prospective": len(fresh), "band": len(band)},
            "models": report,
            "prospective_mae": round(prospective, 5),
            "prospective_band_mae": round(band_mae, 5),
            "prospective_spreadsheet_mae": round(
                sum(abs(surrogate.hand_estimate(r) - r["served_share"]) for r in fresh) / len(fresh), 5
            ),
            "margin": round(plan.margin, 5),
            "noise_floor_served": round(surrogate.noise_floor(replicated, "served_share"), 5),
            "search": search,
            "robust": robust,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def _e5_round(plan, parts: dict, number: int):
    """Simulate what the planner picks in 30 fresh situations, add the runs to training, and retrain."""
    from depot_twin.first_version import planner, surrogate

    def make():
        situations = planner.sample_situations(30, seed=5000 + number)
        designs = planner.searched_designs(plan, situations, top=20, first_id=500_000 + 100_000 * number)
        return surrogate.run_designs(designs, seeds=[0], run_days=surrogate.WEEK_RUN_DAYS)

    rows = _cached(f"e5_round{number}.json", make)
    before = planner.over_prediction(plan, rows)
    parts = {**parts, "train": parts["train"] + rows}
    retrained, report = planner.train(parts)
    return retrained, report, parts, {"designs": len(rows), "over_prediction_before_training_on_them": round(before, 5)}


def _e5_margin(plan) -> tuple[float, int]:
    """Measure over-prediction on searched designs that were never trained on."""
    from depot_twin.first_version import planner, surrogate

    def make():
        situations = planner.sample_situations(12, seed=7000)
        designs = planner.searched_designs(plan, situations, top=20, first_id=900_000)
        return surrogate.run_designs(designs, seeds=[0], run_days=surrogate.WEEK_RUN_DAYS)

    rows = _cached("e5_margin.json", make)
    # With nothing picked there is nothing to measure the margin on, and the margin from training stands.
    return (planner.over_prediction(plan, rows) if rows else plan.margin), len(rows)


def e5_active() -> Path:
    """E5: two rounds of training on what the search picks, a margin from searched designs, then the E4 test."""
    from depot_twin.first_version import planner, surrogate

    first = [r for r in _e4_pool() if r["seed"] == 0]
    parts = surrogate.split(first)
    plan, _ = planner.train(parts)
    rounds = []
    for number in (1, 2):
        plan, report, parts, summary = _e5_round(plan, parts, number)
        rounds.append(summary)
    plan.margin, margin_designs = _e5_margin(plan)
    for target, model in plan.models.items():
        model.save_model(str(data_dir() / "derived" / f"planner_e5_{target}.json"))

    search = [_e4_search_case(plan, case) for case in E4_CASES]
    acceptable = []
    for case in E4_CASES:
        pool = planner.candidates({**E3_GIVEN, **case}, seed=1)
        acceptable.append(int((plan.predict(pool)["served_share"] - plan.margin >= planner.SERVICE_LEVEL).sum()))
    fresh = _e4_prospective()
    prospective = plan.mae("served_share", fresh)
    valid = report["served_share"]["valid_mae"]
    bars = {
        "1_regret_and_top50_hold_in_every_case": all(
            c["regret"] <= 0.02 and c["top50_serving_99pct"] >= 40 and c["top50_worst_served"] >= 0.97 for c in search
        ),
        "2_first_pick_truly_serves_99pct": all(c["simulated_served"] >= planner.SERVICE_LEVEL for c in search),
        "3_prospective_accuracy_kept": prospective <= 0.015 and prospective <= 1.3 * valid,
    }
    return _write(
        "e5_active.json",
        {
            "eval": "E5",
            "rounds": rounds,
            "margin": round(plan.margin, 5),
            "margin_designs": margin_designs,
            "acceptable_candidates": acceptable,
            "train_rows": len(parts["train"]),
            "served_model": report["served_share"],
            "prospective_mae": round(prospective, 5),
            "search": search,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )


def e6_identify(days: float = 7.0, seed: int = 21) -> Path:
    """E6: recover each vehicle's hidden energy parameters and each type's charge curve from telemetry."""
    import numpy as np

    from depot_twin.dispatch import HeadroomRecall
    from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape
    from depot_twin.twin import ChargeCurveIdentifier, EnergyIdentifier, relative_error

    fleet, depot = load_fleet_scenario("scenarios/v2/east_oakland_500.toml")
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape.json")
    sim = FleetSim(fleet, depot, shape, HeadroomRecall(), seed=seed)
    # The estimator starts from each type's published or assumed figure and never sees the true values.
    nominal_drive = np.array([m.drive_kwh_per_mile for m in fleet.models])[sim.model_of]
    nominal_load = np.array([m.always_on_kw for m in fleet.models])[sim.model_of]
    energy = EnergyIdentifier(nominal_drive, nominal_load, sim.capacity, seed=seed)
    curves = ChargeCurveIdentifier()
    sim.telemetry = energy
    sim.depot.on_power = lambda session, kw, could: curves.record(session.visit.model, session.soc, kw, could)

    checkpoints = {}
    for day in range(1, int(days) + 1):
        sim.advance(1440.0)
        if day in (1, int(days)):
            checkpoints[f"day_{day}"] = {
                "drive_median_error": round(
                    float(np.median(relative_error(energy.drive_kwh_per_mile, sim.drive_kwh))), 4
                ),
                "always_on_median_error": round(
                    float(np.median(relative_error(energy.always_on_kw, sim.always_on_kw))), 4
                ),
            }
    drive_error = relative_error(energy.drive_kwh_per_mile, sim.drive_kwh)
    load_error = relative_error(energy.always_on_kw, sim.always_on_kw)
    nominal = {
        "drive_median_error": round(float(np.median(relative_error(nominal_drive, sim.drive_kwh))), 4),
        "always_on_median_error": round(float(np.median(relative_error(nominal_load, sim.always_on_kw))), 4),
    }
    charger_kw = max(bank.kw for bank in depot.chargers)
    curve_error = {}
    for model in fleet.models:
        points = curves.curve(model.name)
        truth = [min(charger_kw, model.accept_kw(soc, "dc")) for soc, _ in points]
        curve_error[model.name] = {
            "bands": len(points),
            "mean_abs_error_kw": round(
                float(np.mean([abs(kw - t) for (_, kw), t in zip(points, truth, strict=True)])), 2
            ),
        }
    final = checkpoints[f"day_{int(days)}"]
    within = float(np.mean((drive_error <= 0.08) & (load_error <= 0.08)))
    bars = {
        "1_driving_energy_median_error_at_most_3pct_and_half_the_nominal": final["drive_median_error"] <= 0.03
        and final["drive_median_error"] <= 0.5 * nominal["drive_median_error"],
        "2_always_on_median_error_at_most_5pct_and_half_the_nominal": final["always_on_median_error"] <= 0.05
        and final["always_on_median_error"] <= 0.5 * nominal["always_on_median_error"],
        "3_nine_in_ten_vehicles_within_8pct_on_both": within >= 0.9,
        "4_charge_curves_within_3kw": all(c["mean_abs_error_kw"] <= 3.0 for c in curve_error.values()),
    }
    return _write(
        "e6_identify.json",
        {
            "eval": "E6",
            "vehicles": fleet.size,
            "days": days,
            "readings_per_vehicle_median": int(np.median(energy.readings)),
            "using_the_type_figure": nominal,
            "identified": checkpoints,
            "share_within_8pct_on_both": round(within, 4),
            "charge_curves": curve_error,
            "bars": bars,
            "run": date.today().isoformat(),
        },
    )
