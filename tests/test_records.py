"""The documents must agree with the result files they quote."""

import json
from pathlib import Path

import pytest

from depot_twin import scoreboard

ROOT = Path(__file__).parent.parent
DERIVED = ROOT / "data" / "derived"


def test_scoreboard_is_up_to_date():
    committed = (ROOT / "docs" / "SCOREBOARD.md").read_text()
    assert committed == scoreboard.render(DERIVED), "run: depot-twin scoreboard"


def test_every_result_file_is_listed_on_the_scoreboard():
    listed = {filename for _, filename, _ in scoreboard.TESTS}
    present = {p.name for p in DERIVED.glob("e[0-9]*.json") if "walk" not in p.name and "prospective" not in p.name}
    working = (
        "runs",
        "round",
        "e5_margin",
        "development",
        "blocks",
        "baseline",
    )  # intermediate files and side studies, not results
    results = {name for name in present if not any(word in name for word in working)}
    assert results <= listed, f"result files not on the scoreboard: {sorted(results - listed)}"


@pytest.mark.parametrize("name", ["e8_heartbeat.json", "e9_ledger.json"])
def test_recorded_bars_follow_from_the_recorded_table(name):
    result = json.loads((DERIVED / name).read_text())
    table = result["table"]
    gain = table["heartbeat_1000"]["served"] - table["headroom_1000"]["served"]
    not_worse = table["heartbeat_500"]["served"] >= table["headroom_500"]["served"] - 0.002
    key = next(k for k in result["bars"] if "serves_1pt_more" in k)
    assert result["bars"][key] == (gain >= 0.01 and not_worse)


def test_every_registered_test_in_the_record_has_a_result_section():
    record = (ROOT / "EVALS.md").read_text()
    assert record.count("\n### Result\n") >= record.count("\n## E")
    assert "Not yet run." not in record


def test_stale_records_are_exactly_the_ones_named():
    """A record whose code has changed since it ran must be named in stale.json, and running it again clears the name."""
    from depot_twin import provenance

    old = set(provenance.stale(DERIVED)) | set(provenance.stale_pages(ROOT))
    named = set(provenance.acknowledged(DERIVED))
    assert old - named == set(), (
        f"records gone stale without being named: {sorted(old - named)}; run them again or name them"
    )
    assert named - old == set(), f"named as stale but current: {sorted(named - old)}; remove them from stale.json"


def test_every_scored_record_has_a_code_stamp_entry():
    from depot_twin import provenance

    assert {filename for _, filename, _ in scoreboard.TESTS} <= set(provenance.RECORDS)


def test_a_stamp_moves_with_the_code_and_not_with_its_comments():
    from depot_twin import provenance

    source = (ROOT / "src" / "depot_twin" / "grid.py").read_text()
    code = provenance._code_only(source)
    assert provenance._code_only(source.replace('"""Power at the site', '"""The power at the site')) == code
    assert provenance._code_only(source + "\n# a note at the end\n") == code
    assert provenance._code_only(source.replace("LIMIT_TOLERANCE_KW = 1e-6", "LIMIT_TOLERANCE_KW = 1e-3")) != code
    assert "#" not in code.replace("# noqa", "") and '"""' not in code


def test_every_page_file_the_documents_quote_is_stamped():
    from depot_twin import provenance

    for entry in provenance.PAGE:
        assert sorted(ROOT.glob(entry)), f"no file matches {entry}"
    stamp = provenance.page_stamp("web/public/money.json", ROOT)
    assert set(stamp) == {"driver", "upstream"}  # built from a record, by one module


def test_growth_is_read_three_ways_and_a_date_follows_each():
    from depot_twin import cadence

    ways = cadence.growth_estimates([0.10, 0.14, 0.145, 0.15])  # one jump, then little
    assert ways["last_six_months"] < ways["fitted"] < ways["first_to_last"]
    steady = cadence.growth_estimates([0.10, 0.11, 0.121, 0.1331])
    assert steady["first_to_last"] == pytest.approx(steady["fitted"]) == pytest.approx(steady["last_six_months"])
    assert cadence.months_until(600, 241, 0.05) < cadence.months_until(600, 241, 0.02)
    assert cadence.months_until(600, 700, 0.02) == 0 and cadence.months_until(600, 241, 0.0) is None


def test_a_fleet_is_carried_when_nine_runs_in_ten_serve_the_floor_and_every_smaller_fleet_is():
    from depot_twin import cadence

    def runs(size, served):
        return [
            {"size": size, "served": s, "trips_per_visit": 8.0, "arrived_at_floor_share": 0.0, "stranded": 0.0}
            for s in served
        ]

    data = (
        runs(500, [1.0] * 10)
        + runs(600, [1.0] * 9 + [0.98])
        + runs(700, [1.0] * 8 + [0.98] * 2)
        + runs(800, [1.0] * 10)
    )
    out = cadence.carried(data, (500, 600, 700, 800))
    assert out["capacity"] == 600  # 700 falls short, so 800 does not count though its runs pass
    assert out["by_size"]["700"]["runs_at_floor"] == 0.8
    # A fleet that serves its rides with most vehicles arriving at the low-battery level is not carried.
    edge = [dict(r, arrived_at_floor_share=0.9) if r["size"] == 600 else r for r in data]
    out = cadence.carried(edge, (500, 600, 700, 800))
    assert (out["capacity"], out["largest_serving_the_floor"]) == (500, 600)


def test_the_replayed_fortnights_are_committed_and_are_the_ones_the_fitted_forecasts_give():
    from depot_twin import cadence, provenance

    assert provenance.REPLAYED == cadence.E23_WINDOWS
    assert provenance.replay_problems(ROOT) == {}


def test_no_downloaded_file_on_disk_differs_from_the_manifest():
    from depot_twin.data import build

    assert build.manifest_problems(str(ROOT / "data" / "manifest.json")) == []
