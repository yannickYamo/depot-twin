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
    working = ("runs", "round", "margin", "development")  # intermediate files, not results
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

    old, named = set(provenance.stale(DERIVED)), set(provenance.acknowledged(DERIVED))
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
