import copy
import json

import numpy as np
import pytest

from depot_twin import ChargerBank, DepotConfig, VehicleModel
from depot_twin.cli import main
from depot_twin.fleet import FleetConfig, FleetSim, ThresholdRecall
from depot_twin.heartbeat import Heartbeat
from depot_twin.trace import STEP_COLUMNS, TRACE_VERSION, TraceRecorder, problems

CAR = VehicleModel("car", capacity_kwh=90, max_dc_kw=100, max_ac_kw=11, drive_kwh_per_mile=0.3, always_on_kw=2.0)
DAY = np.array([2, 1, 1, 1, 1, 2, 3, 5, 6, 5, 5, 5, 5, 5, 5, 6, 7, 7, 7, 6, 5, 5, 4, 3], dtype=float)
SHAPE = np.tile(DAY, 7) / np.tile(DAY, 7).sum()


def record(rule, policy, limit=600.0, days=1.5):
    depot = DepotConfig("t", limit, (ChargerBank("dc", 12, 60),), staff=4, cleaning_bays=4, clean_minutes=8)
    sim = FleetSim(FleetConfig(size=80, models=(CAR,), step_min=5), depot, SHAPE, rule, depot_policy=policy, seed=2)
    recorder = TraceRecorder(sim, label="test")
    sim.run(days)
    return recorder.to_dict()


@pytest.fixture(scope="module")
def trace():
    return record(Heartbeat(ledger_from_state=True), "slot_power")


def test_a_recorded_run_meets_the_contract(trace):
    assert problems(trace) == []
    assert trace["version"] == TRACE_VERSION
    assert set(trace["steps"]) == set(STEP_COLUMNS)
    assert len(trace["steps"]["minute"]) == 432  # a day and a half of five-minute steps


@pytest.mark.parametrize("rule, policy", [(ThresholdRecall(), "need_first"), (ThresholdRecall(), "slot_power")])
def test_every_rule_produces_a_sound_trace(rule, policy):
    assert problems(record(rule, policy, limit=300.0)) == []


def test_a_trace_is_plain_json(trace):
    assert json.loads(json.dumps(trace)) == trace


def test_the_ledger_shows_up_once_the_controller_has_planned(trace):
    promised = [p for p in trace["steps"]["promised"] if p is not None]
    assert len(promised) > 400 and all(0 <= p <= 80 for p in promised)


def test_a_vehicle_keeps_its_stall_while_it_charges(trace):
    seen: dict[int, int] = {}
    for step in trace["stalls"]:
        now = {vehicle: stall for stall, vehicle, _, _ in step}
        for vehicle, stall in now.items():
            if vehicle in seen:
                assert seen[vehicle] == stall
        seen = now


@pytest.mark.parametrize(
    "break_it, expect",
    [
        (lambda t: t["steps"]["on_road"].__setitem__(5, t["steps"]["on_road"][5] + 1), "do not add up"),
        (lambda t: t["steps"]["grid_kw"].__setitem__(5, 9999), "over the site limit"),
        (lambda t: t["steps"].pop("tariff"), "columns differ"),
        (lambda t: t["steps"]["served"].__setitem__(5, t["steps"]["offered"][5] + 3), "more rides served"),
        (lambda t: t.__setitem__("version", 99), "version"),
    ],
)
def test_the_contract_catches_a_broken_trace(trace, break_it, expect):
    broken = copy.deepcopy(trace)
    break_it(broken)
    assert any(expect in problem for problem in problems(broken))


def test_the_command_writes_a_trace(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.chdir(Path(__file__).parent.parent)
    out = tmp_path / "trace.json"
    code = main(
        ["trace", "scenarios/v2/east_oakland_500.toml", "--days", "0.5", "--recall", "threshold", "--out", str(out)]
    )
    assert code == 0
    assert problems(json.loads(out.read_text())) == []
