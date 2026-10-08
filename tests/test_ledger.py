"""The promise ledger and the price window, each on its own."""

import pytest

from depot_twin.ledger import PromiseLedger
from depot_twin.steering import expensive_window


def hour(ledger: PromiseLedger, k: int, planned: float, actual: float, fleet: int = 500) -> dict:
    ledger.close()
    ledger.commit(k, planned, fleet)
    for _ in range(12):
        ledger.observe(actual)
    entry = ledger.open
    return entry


def test_the_margin_is_a_flat_five_per_cent_until_a_day_of_history_exists():
    ledger = PromiseLedger()
    assert ledger.margin(500) == pytest.approx(25.0)
    assert ledger.commit(0, 400.0, 500) == pytest.approx(375.0)


def test_a_promise_is_kept_when_the_hour_delivers_what_was_committed():
    ledger = PromiseLedger()
    hour(ledger, 0, planned=400.0, actual=380.0)
    hour(ledger, 1, planned=400.0, actual=360.0)
    ledger.close()
    assert [entry["kept"] for entry in ledger.entries] == [True, False]
    assert ledger.entries[0]["actual"] == pytest.approx(380.0)


def test_the_margin_follows_the_shortfalls_of_the_record_and_widens_when_promises_break():
    fixed = PromiseLedger(level=0.95)
    learning = PromiseLedger(level=0.95, adapt=0.2)
    for ledger in (fixed, learning):
        for k in range(48):
            hour(ledger, k, planned=400.0, actual=340.0)  # every promise overstated by 60
        ledger.close()
    assert fixed.margin(500) == pytest.approx(60.0)
    # The first day's promises held back 25 and were broken; the adaptive margin has grown past the record's.
    assert learning.margin(500) > fixed.margin(500)


def test_the_tariff_is_expensive_from_four_to_nine_and_says_how_long_until_then():
    assert expensive_window(17 * 60.0, None) == (True, None, 5.0)
    quiet, until, length = expensive_window(10 * 60.0, None)
    assert (quiet, until, length) == (False, 6.0, 5.0)


def test_a_price_curve_is_expensive_only_where_it_stands_clear_of_the_median():
    flat = lambda minute: 0.10  # noqa: E731
    assert expensive_window(0.0, flat) == (False, None, 0.0)  # ties are not expensive hours
    evening = lambda minute: 0.30 if 17 <= (minute / 60.0) % 24 < 20 else 0.10  # noqa: E731
    assert expensive_window(10 * 60.0, evening) == (False, 7.0, 3.0)
    assert expensive_window(18 * 60.0, evening)[0] is True
