"""The local tool's run function: the full model on a small design, without Streamlit."""

from depot_twin import local


def test_a_small_design_runs_and_returns_summary_trace_and_account():
    out = local.run(local.Design(fleet=200, site_limit_kw=2750.0, rule="plan_with_prices", days=1, seed=3))
    assert 0.0 <= out["summary"]["rides_served_share"] <= 1.0
    assert out["trace"]["meta"]["fleet"] == 200 and len(out["trace"]["steps"]["minute"]) == 288
    assert out["trace"]["plans"], "the plan should have been redrawn at least once"
    assert set(out["account"]["per_day"]) >= {"revenue", "energy_tariff", "vehicles", "reliability"}
    assert out["chargers"] > 0 and out["people"] > 0


def test_a_threshold_design_makes_no_plan():
    out = local.run(local.Design(fleet=200, rule="threshold", days=1, seed=4))
    assert out["trace"]["plans"] == []
