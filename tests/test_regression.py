import json

import pytest

from tests.regression_cases import GOLDEN, cases

PINNED = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}


def test_every_pinned_case_still_exists():
    assert PINNED, "tests/golden.json is missing; run: python -m tests.regression_cases"
    assert set(cases()) == set(PINNED)


@pytest.mark.parametrize("name", sorted(PINNED))
def test_pinned_numbers_have_not_moved(name):
    now = cases()[name]
    for key, value in PINNED[name].items():
        # Tight but not exact: a different maths library may differ in the last digits.
        assert now[key] == pytest.approx(value, rel=1e-6, abs=1e-6), f"{name}: {key} moved from {value} to {now[key]}"
