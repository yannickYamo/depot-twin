"""The public documents say what the result files say."""

import json
from pathlib import Path

from depot_twin import facts

ROOT = Path(__file__).parent.parent


def test_every_public_document_states_the_recorded_figures():
    assert facts.problems(ROOT) == []


def test_the_facts_file_is_the_one_the_records_give():
    assert json.loads((ROOT / "docs" / "FACTS.json").read_text()) == facts.public_facts()
