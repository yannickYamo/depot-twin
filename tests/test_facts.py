"""The public documents say what the result files say."""

import json
from pathlib import Path

from depot_twin import facts, provenance

ROOT = Path(__file__).parent.parent


def test_every_public_document_states_the_recorded_figures():
    assert facts.problems(ROOT) == []


def test_the_facts_file_is_the_one_the_records_give():
    written = json.loads((ROOT / "docs" / "FACTS.json").read_text())
    stamp = written.pop("code")
    assert written == facts.public_facts()
    assert stamp == provenance.page_stamp("docs/FACTS.json")


def test_a_number_in_no_claim_is_a_problem():
    listed = {"600 vehicles", "675 vehicles", "99%", "16", "47 months", "10%", "8.5 points"}
    assert facts.unlisted("One feeder is planned for 600 vehicles at a 99% floor.", listed) == []
    assert facts.unlisted("It carries 613 vehicles, or 41.7% more.", listed) == ["613 vehicles", "41.7%"]
    # A listed number under the wrong unit is not listed: 47 months is, 47 vehicles is not.
    assert facts.unlisted("The feeder carries 47 vehicles.", listed) == ["47 vehicles"]
    assert facts.unlisted("Needed in 24 months.", listed) == ["24 months"]
    # A small count with a unit is a figure; without one it is a list number.
    assert facts.unlisted("About 8 points in 9 runs of 3.", listed) == ["8 points", "9 runs"]
    # Code and link targets are not prose, and a number in a picture's caption is.
    assert facts.unlisted("1. Run `depot-twin eval e23`, see [E23](EVALS.md#e23).", listed) == []
    assert facts.unlisted("![A fleet of 999 vehicles](x.svg)", listed) == ["999 vehicles"]
    assert "an unclosed code mark, which hides what follows it" in facts.unlisted("` carries 999 vehicles", listed)


def test_the_ledger_lists_its_figures_with_their_units():
    listed = facts.listed_numbers(facts.public_facts())
    assert "600 vehicles" in listed and "2.75 MW" in listed
    # A range lists its first figure bare ("39 to 47 months"); the unit sits on the last, and only there.
    assert "47 months" in listed and "47 vehicles" not in listed and "39 vehicles" not in listed
