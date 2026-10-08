"""The local operator's tool: the full model behind a few widgets. Run with `depot-twin app`.

This is not the public page. The public page runs nothing it cannot show; this runs the real simulator,
the plan and the forecasts on this machine, for an operator trying a design of their own.
"""

from __future__ import annotations


def _sidebar(st, local):
    """The widgets on the left: a design and the Run button."""
    with st.sidebar:
        st.header("The design")
        fleet = st.select_slider(
            "Vehicles in the fleet", options=[200, 300, 400, 500, 600, 700, 800, 1000, 1200], value=500
        )
        feeders = st.radio("Grid connection", ["One feeder, 2.75 MW", "Two feeders, 5.5 MW"])
        chargers = st.select_slider("Chargers, against the sizing rule", options=[0.75, 1.0, 1.25, 1.5], value=1.0)
        people = st.select_slider("People, against one per forty vehicles", options=[0.5, 1.0, 2.0], value=1.0)
        names = {
            "threshold": "Fixed threshold",
            "plan": "The plan",
            "plan_with_prices": "The plan, told the price of energy",
        }
        rule = st.radio("How vehicles are called in", local.RULES, index=2, format_func=lambda r: names[r])
        demand = st.radio("Rides", local.DEMAND)
        days = st.slider("Days to run", 1, 7, 3)
        go = st.button("Run", type="primary")
    site = 2750.0 if feeders.startswith("One") else 5500.0
    return local.Design(fleet, site, chargers, people, rule, demand, days), go


def _show(st, pd, out: dict) -> None:
    """The result: four figures, the day step by step, the plan when there is one, and the account."""
    summary, trace, books = out["summary"], out["trace"], out["account"]
    a, b, c, d = st.columns(4)
    a.metric("Rides served", f"{summary['rides_served_share']:.1%}")
    b.metric("On the road at the peak", f"{summary['available_at_peak_share']:.1%}")
    c.metric("Energy per kWh", f"${books['energy_cost_per_kwh_tariff']:.3f}")
    d.metric("Contribution a day", f"${books['contribution_per_day']:,.0f}")
    steps = pd.DataFrame(trace["steps"])
    steps["hour"] = steps["minute"] / 60.0
    st.subheader("The day, step by step")
    st.line_chart(steps.set_index("hour")[["on_road", "queued", "charging"]])
    st.line_chart(steps.set_index("hour")[["grid_kw"]])
    if trace.get("plans"):
        st.subheader("The plan, each time it was redrawn")
        plans = pd.DataFrame(
            [
                {"hour": p["minute"] / 60.0, "call in this hour": p["quota"], "promised on the road": p["committed"]}
                for p in trace["plans"]
            ]
        )
        st.line_chart(plans.set_index("hour"))
    st.subheader("The account, a day")
    st.table(pd.DataFrame({"a day": books["per_day"]}).style.format("${:,.0f}"))
    st.caption(
        f"{out['chargers']} chargers, {out['people']} people. Vehicles at a parameter of $60,000 a year and $100 a day to run; a lost ride at $20 beyond its fare. See docs/SITE.md."
    )


def main() -> None:
    """Draw the page. Imported by Streamlit, so everything is inside the function."""
    import pandas as pd
    import streamlit as st

    from depot_twin import local

    st.set_page_config(page_title="depot-twin, local", layout="wide")
    st.title("A depot, run on the full model")
    st.caption(
        "The Python simulator, the day-ahead plan and the trained forecasts, on this machine. Not the public page."
    )
    design, go = _sidebar(st, local)
    if not go:
        st.info("Choose a design on the left and press Run. A three-day run takes about half a minute.")
        return
    with st.spinner("Running the full model..."):
        out = local.run(design)
    _show(st, pd, out)


if __name__ == "__main__":
    main()
