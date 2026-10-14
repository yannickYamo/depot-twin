"""The figures the public documents quote, read from the result files in one place.

A finding has one figure, and a figure has a range and the conditions it holds under. The README and
the story are the front door: each must state the plan and the calling rule (`FRONT`). The brief must
state every claim. The figures come from here: `docs/FACTS.json` is a ledger of claims written from the
result files, and a test fails when a document leaves out a claim it must state or says anything else. The README
and the brief's statement of the decision are held tighter: every number in them must be in a claim, or
be an input the ledger names with where it is set. The count of bars passed is quoted more widely, so
every public document and the page's own text are checked for it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from depot_twin import analysis
from depot_twin.data import data_dir
from depot_twin.scoreboard import rows

# The documents held to the ledger. The brief states every finding; the README and the story state the FRONT two.
DOCUMENTS = ("README.md", "docs/BRIEF.md", "docs/STORY.md")
FRONT = ("planned_fleet", "calling_rule")
# Everything else a reader can open.
OTHER_PUBLIC = ("EVALS.md", "docs/DECISIONS.md", "docs/METHOD.md", "docs/ML.md", "docs/DATA.md", "web/index.html")
PAGE_SOURCES = ("web/src/*.ts", "web/src/views/*.ts")


def _record(name: str) -> dict:
    return json.loads((data_dir() / "derived" / name).read_text())


def _points(share: float) -> str:
    """A share as a percentage to one decimal, halves rounded up, so a figure reads the same wherever it is printed."""
    from decimal import ROUND_HALF_UP, Decimal

    return str((Decimal(repr(share)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _claim(key: str, says: tuple[str, ...], stated_in: tuple[str, ...], **fields: object) -> dict:
    """One figure a document may state: its value, its range, the conditions it holds under and its record."""
    # Where a claim must be stated is decided here, by FRONT. The `stated_in` each call passes is where the
    # finding was first written, kept for the reader of this file.
    stated = DOCUMENTS if key in FRONT else ("docs/BRIEF.md",)
    return {"claim": key, **fields, "says": list(says), "stated_in": list(stated)}


def _mean_cost(capacity: dict, size: int, seeds: list[int]) -> float:
    """What the rule that waits for a free charger pays for a kWh at one fleet, on the seeds a later test used."""
    rule = capacity["best_rule"]
    paid = [
        r["cost_per_kwh"]
        for r in capacity["runs"]
        if r["label"] == "base" and r["rule"] == rule and r["size"] == size and r["seed"] in seeds
    ]
    return sum(paid) / len(paid)


def claims() -> list[dict]:  # noqa: PLR0915
    """Every headline figure with its range, its conditions and the record behind it.

    `says` is what a document states word for word, so a figure never travels without its range, and
    `stated_in` is the documents that must state it. Nothing here is typed in: each value is read from
    the record named in `source`.
    """
    capacity, demand = _record("e23_capacity.json"), _record("e21_demand.json")
    backtest, account = _record("e24_backtest.json"), _record("account_study.json")
    margin, parked = _record("e26_margin.json"), _record("e27_parked.json")
    baseline, sensitivity = _record("e24_baseline.json"), _record("sensitivity.json")
    spread = _record("capacity_spread.json")
    further, steer = _record("e28_further.json"), _record("e29_steer.json")
    busier = further["rides"]["1.1"]
    as_tested, raised = (steer["by_peak_level"][level] for level in ("0.15", "0.25"))
    best = capacity["rules"][capacity["best_rule"]]
    gain, saving = capacity["power_rule_gain"], capacity["plan_energy_saving_at_500"]
    derived = data_dir() / "derived"
    carried, at_estimate = analysis.carried_fleet(derived)
    planned, _ = analysis.planned_fleet(derived)
    area = analysis.demand_at(demand, planned)["east_bay_20km"]
    low, high = area["months_until_second_feeder_range"]
    fewest, most = (int(v) for v in area["vehicles_range"])
    chicago = backtest["series"]["chicago"]["1h"]
    base = str(account["base_design"]["fleet"])
    limit = capacity["largest_serving_the_floor"][capacity["best_rule"]]
    rides = capacity["rides_per_vehicle_day"]
    at_limit = best["by_size"][str(limit)]
    runs = f"{len(capacity['windows'])} fortnights by {len(capacity['seeds'])} draws"
    setting = "the cadence setting E22 chose, each fortnight replayed until the fleet settles and its last week scored"
    more = f"{margin['margin']:g}"
    above = margin["by_energy"][more]["by_size"][str(planned)]
    same = margin["on_the_same_steps"]
    timing = account["feeder_timing"]["summary"]
    late = timing["a_year_late_at_base_costs_on_the_faster_growth_readings"]
    early = timing["carrying_cost_of_applying_a_year_early"]
    served = capacity["power_rule_served"]
    millions = lambda value: f"{value / 1e6:.0f}"  # noqa: E731
    settled = account["feeder_timing"]["growth_since_the_footprint_settled"]
    settled_months = sorted(settled["months_until_one_feeder_is_full"].values())
    faster_high = max(
        months
        for row in area["by_level"].values()
        for name, months in row["months_until_second_feeder_by_estimate"].items()
        if name != settled["nearest_reading"]
    )
    slow_by_lead = {
        lead: [
            s["cost_of_waiting"]
            for s in account["feeder_timing"]["scenarios"]
            if (s["growth"], s["fleet_costs"], s["applied_months_after_signing"], s["lead_months"])
            == (settled["nearest_reading"], "base", 12, lead)
        ]
        for lead in account["feeder_timing"]["lead_months_assumed"]
    }
    longest = max(slow_by_lead)
    both = parked["by_energy"][more]
    chicago_base = baseline["series"]["chicago"]["1h"]
    ny = [
        baseline["series"][name]["1h"]["difference"]["trained_here_less_baseline"]["mean"]
        for name in ("nyc_ridehail", "nyc_yellow")
    ]
    moving = spread["where_rides_served_moves"]
    plans = Path(__file__).parent.parent.parent / "sites" / "plans"
    site = json.loads((plans / "east_oakland.json").read_text())
    shapes = {path.stem: json.loads(path.read_text()) for path in sorted(plans.glob("shape_*.json"))}
    other_demand = {name: plan["carried"] for name, plan in shapes.items()}
    removed = [c["carried_with_it"] for c in site["changes"] if c["kind"] == "remove"]
    without_a_rule = removed[0] if len(set(removed)) == 1 else min(r for r in removed if r)
    chargers = next(c["carried_with_it"] for c in site["changes"] if c["change"] == "a quarter more chargers")
    return [
        _claim(
            "power_rule",
            (f"{_points(gain['median'])} points", f"{_points(gain['p10'])} to {_points(gain['p90'])}"),
            DOCUMENTS,
            value=gain["median"],
            low=gain["p10"],
            high=gain["p90"],
            share_of_usable_power_drawn=capacity["power_rule_grid_share_used"],
            gain_at_planned_fleets={
                size: row["gain"] for size, row in capacity["power_rule_at_planned_fleets"].items()
            },
            unit="share of rides served, charging in order of arrival less emptiest battery first",
            conditions=(
                f"1,000 vehicles on one feeder, a site short of power; {setting}; median and 10th to 90th "
                f"percentile of {runs}. Where power is not short the two rules serve the same rides"
            ),
            source="E23, data/derived/e23_capacity.json",
        ),
        _claim(
            "planned_fleet",
            (f"{planned} vehicles", f"{planned * rides:,.0f} rides a day", f"{margin['margin'] - 1:.0%} more energy"),
            DOCUMENTS,
            value=planned,
            rides_per_day=planned * rides,
            figures=[
                f"{at_estimate['by_size'][str(planned)]['grid_share_used']:.0%} of usable power at the estimate",
                f"{above['grid_share_used']:.0%} with more energy use",
            ],
            share_of_usable_power_drawn_at_the_estimate=at_estimate["by_size"][str(planned)]["grid_share_used"],
            share_of_usable_power_drawn_with_more_energy_use=above["grid_share_used"],
            low_battery_arrivals_with_more_energy_use=above["arrived_at_floor_share"],
            carried_in_each_fortnight_with_more_energy_use=above["carried_by_fortnight"],
            registered_rule_gives=margin["planned_fleet"],
            unit="vehicles to plan one 2.75 MW feeder for",
            conditions=(
                f"the largest fleet carried at the estimated energy use and, in each of the four fortnights taken "
                f"alone, with driving energy and the always-on load {margin['margin'] - 1:.0%} higher. E26's registered "
                f"rule, the largest fleet carried at both levels over all forty runs, gives {margin['planned_fleet']}; "
                f"{rides:.0f} rides offered a vehicle a day; a vehicle is called in once a charger is free for it; "
                f"{setting}; {runs}"
            ),
            source="E26, data/derived/e26_margin.json",
        ),
        _claim(
            "capacity_one_feeder",
            (f"{carried} vehicles", f"{limit} vehicles"),
            DOCUMENTS,
            value=carried,
            rides_per_day=carried * rides,
            figures=[f"{at_limit['arrived_at_floor_share']:.0%} of visits start on a low battery at the limit"],
            served_at_the_limit=limit,
            rides_per_day_at_the_limit=limit * rides,
            low_battery_arrivals_at_the_limit=at_limit["arrived_at_floor_share"],
            grid_share_used={size: row["grid_share_used"] for size, row in sorted(at_estimate["by_size"].items())},
            carried_on_hundred_vehicle_steps=capacity["capacity"],
            by_fortnight=capacity["capacity_by_fortnight"],
            by_rule_on_hundred_vehicle_steps={rule: row["capacity"] for rule, row in capacity["rules"].items()},
            unit="vehicles on one 2.75 MW feeder at the estimated energy use",
            conditions=(
                f"carried: the largest fleet serving {capacity['floor']:.0%} of rides in nine runs in ten with no more "
                "than half its depot visits arriving at the low-battery level; the largest fleet run that was carried, "
                "in steps of 25 vehicles. Served at the limit: the largest fleet "
                f"serving {capacity['floor']:.0%} in nine runs in ten on any terms. {rides:.0f} rides offered a vehicle "
                f"a day; a vehicle is called in once a charger is free for it; {setting}; {runs}"
            ),
            source="E23, E25 and E26, data/derived/e23_capacity.json, e25_between.json and e26_margin.json",
        ),
        _claim(
            "capacity_by_energy_use",
            (f"{margin['carried']['0.9']} vehicles", f"{margin['carried'][more]} vehicles"),
            ("README.md", "docs/BRIEF.md"),
            carried=margin["carried"],
            carried_times_energy_use=margin["carried_times_energy_use"],
            feeder_kwh_per_vehicle_day=at_estimate["by_size"][str(carried)]["feeder_kwh_per_vehicle_day"],
            usable_kwh_a_day=margin["usable_kwh_a_day"],
            unit="vehicles carried on one feeder with the vehicles' energy use 10% lower and 10% higher than estimated",
            conditions=f"driving energy and the always-on load both multiplied; the capacity test's setting; {runs}",
            source="E26, data/derived/e26_margin.json",
        ),
        _claim(
            "calling_rule",
            (f"{same['waits_for_a_charger']} vehicles", f"{same['plain']} vehicles"),
            DOCUMENTS,
            waits_for_a_charger=same["waits_for_a_charger"],
            plain=same["plain"],
            figures=[f"steps of {same['steps'][1] - same['steps'][0]} vehicles"],
            steps=same["steps"],
            plain_runs_at_the_floor={
                size: row["runs_at_floor"] for size, row in margin["plain_rule"]["by_size"].items()
            },
            unit="largest fleet carried on one feeder, by calling rule, on the same steps",
            conditions=(
                "both rules on steps of 50 vehicles at the estimated energy use; the rule that waits was not "
                f"run above the last shared step here, where finer steps carry {carried}; {runs}"
            ),
            source="E26, data/derived/e26_margin.json",
        ),
        _claim(
            "power_rule_served",
            (f"{_points(served['slot_power']['median'])}%", f"{_points(served['need_first']['median'])}%"),
            ("README.md", "docs/BRIEF.md"),
            in_order=served["slot_power"],
            emptiest_first=served["need_first"],
            unit="share of rides served at 1,000 vehicles on one feeder, by power rule",
            conditions=f"a plain threshold; {setting}; median of {runs}",
            source="E23, data/derived/e23_capacity.json",
        ),
        _claim(
            "second_feeder",
            (f"{settled_months[0]} to {settled_months[-1]} months", f"{low} to {faster_high} months"),
            DOCUMENTS,
            low=low,
            high=high,
            figures=[
                f"{settled['growth_per_month']:.1%} a month since the footprint last changed",
                f"{settled['months_fitted']} months fitted",
            ],
            on_the_growth_since_the_footprint_settled=settled,
            by_level_and_reading_of_growth={
                level: row["months_until_second_feeder_by_estimate"] for level, row in area["by_level"].items()
            },
            unit="months until the 20 km area needs more vehicles than one feeder is planned for",
            conditions=(
                f"against the {planned} vehicles planned; a scenario, not a test. Today's level read two ways (the "
                "last four quarters, centred on January 2026, and the latest quarter, centred on May 2026), so the "
                "months count from the first half of 2026. Growth: the fit to monthly trips since the served "
                f"footprint last changed ({settled['from']} to {settled['to']}), which agrees with the slowest of "
                "E21's three readings; the two faster readings span the quarter the footprint was enlarged and "
                "are quoted as what such a jump would do again. Statewide trips a resident applied to the East "
                "Bay's residents, with no adjustment for density"
            ),
            source="E21 and the account study, data/derived/e21_demand.json and account_study.json",
        ),
        _claim(
            "feeder_timing",
            (
                f"${millions(late[0])} to ${millions(late[1])} million",
                f"${early[0]:,.0f} to ${early[1]:,.0f}",
                f"${millions(timing['a_year_late_across_fleet_costs'][1])} million",
            ),
            DOCUMENTS,
            figures=[
                f"{timing['scenarios']} scenarios",
                f"${millions(min(slow_by_lead[longest]))} to ${millions(max(slow_by_lead[longest]))} million at a lead of {longest // 12} years",
                f"${account['feeder_timing']['added_contribution_per_vehicle_day']['base']:.0f} a vehicle a day added",
            ],
            a_year_late_on_the_growth_since_the_footprint_settled_by_lead_months={
                str(lead): [min(values), max(values)] for lead, values in slow_by_lead.items()
            },
            base_cost_scenarios_at_the_cap=[timing["base_cost_scenarios_at_the_cap"], timing["base_cost_scenarios"]],
            a_year_late_at_base_costs_on_the_faster_growth_readings=late,
            a_year_late_at_base_costs_on_the_slowest_growth_reading=timing[
                "a_year_late_at_base_costs_on_the_slowest_growth_reading"
            ],
            a_year_late_across_fleet_costs=timing["a_year_late_across_fleet_costs"],
            carrying_cost_of_applying_a_year_early=early,
            capital=timing["capital_at_risk_if_the_second_feeder_is_never_needed"],
            added_contribution_per_vehicle_day=account["feeder_timing"]["added_contribution_per_vehicle_day"],
            scenarios=timing["scenarios"],
            unit="dollars of contribution not earned by applying a year after signing, present value",
            conditions=(
                "a table of scenarios with no bars: two readings of today, three of growth, lead times of two, three "
                "and four years, discount rates of 8% and 10%, and the two unsourced vehicle costs at the cheap end, "
                "the base and the dear end of their ranges; a vehicle the first feeder cannot carry is valued at "
                "what a second feeder would add for it, the land and first connection being paid already; capped "
                "at one feeder's worth of vehicles; every vehicle assumed to find its rides"
            ),
            source="account study, data/derived/account_study.json",
        ),
        _claim(
            "parked_load",
            (f"{both['carried_in_every_fortnight']} vehicles", f"{both['carried']} vehicles"),
            ("README.md", "docs/BRIEF.md"),
            carried_with_the_parked_load={energy: group["carried"] for energy, group in parked["by_energy"].items()},
            carried_in_every_fortnight_with_the_parked_load={
                energy: group["carried_in_every_fortnight"] for energy, group in parked["by_energy"].items()
            },
            feeder_kwh_per_vehicle_day_added=parked["feeder_kwh_per_vehicle_day_added_by_the_parked_load"],
            figures=[
                f"{carried - both['carried_in_every_fortnight']} vehicles between the two",
                f"{sensitivity['rows'][0]['kwh_per_mile']:.2f} kWh a mile all in",
            ],
            unit="vehicles carried on one feeder with the always-on load counted while a vehicle is in the depot, and with 10% more energy use on the road as well",
            conditions=(
                "the always-on load charged to a vehicle's battery for every minute between arriving at the depot "
                f"and leaving it; the capacity test's setting; {runs}. Carried in every fortnight applies the rule "
                "to each fortnight alone"
            ),
            source="E27, data/derived/e27_parked.json",
        ),
        _claim(
            "further_from_the_estimate",
            (f"{further['energy']['1.2']['carried']} vehicles", f"{further['energy']['1.3']['carried']} vehicles"),
            ("README.md",),
            carried_by_energy_use={level: arm["carried"] for level, arm in further["energy"].items()},
            carried_by_rides_a_vehicle={level: arm["carried"] for level, arm in further["rides"].items()},
            carried_with_a_sharper_peak={
                level: arm["carried"] for level, arm in further["peak"].items() if isinstance(arm, dict)
            },
            carried_under_other_cadence_settings={name: arm["carried"] for name, arm in further["cadence"].items()},
            figures=[
                "20%",
                "30%",
                f"{busier['rides_per_vehicle_day']:.1f} rides",
                f"{busier['carried']} vehicles",
                f"{further['rides']['1.2']['rides_per_vehicle_day']:.0f} rides",
                f"{len(further['cadence'])} settings",
            ],
            unit="vehicles carried on one feeder with one input moved further than the earlier tests moved it",
            conditions=(
                "the capacity test's setting and the rule that waits for a free charger, on its four fortnights "
                "with three of its ten seeds, twelve runs a fleet; one input moved at a time; at 30 rides a vehicle "
                "a day no fleet from 525 to 600 is carried and smaller fleets were not run"
            ),
            source="E28, data/derived/e28_further.json",
        ),
        _claim(
            "plan_at_the_planned_fleet",
            (
                f"{100 * (1 - as_tested['by_size']['600']['cost_per_kwh'] / _mean_cost(capacity, 600, steer['seeds'])):.1f}%",
            ),
            ("README.md",),
            energy_saving_at_500_by_peak_level={
                level: arm["energy_saving_at_500"] for level, arm in steer["by_peak_level"].items()
            },
            low_battery_visits_at_600_by_peak_level={
                level: arm["by_size"]["600"]["arrived_at_floor_share"] for level, arm in steer["by_peak_level"].items()
            },
            charge_on_the_road_at_600=as_tested["by_size"]["600"]["charge_on_the_road"],
            served_at_650=as_tested["by_size"]["650"]["served_median"],
            carried_with_the_peak_level_raised=raised["carried_in_every_fortnight"],
            figures=[f"{100 * as_tested['by_size']['600']['charge_on_the_road']:.0f}%"],
            unit="what the hourly plan pays for energy at 600 vehicles, less than the rule that waits for a free charger",
            conditions=(
                "the capacity test's setting under the plan on 30-minute slots, four fortnights with three of its "
                "ten seeds; the rule that waits is read from E23 on the same fortnights and seeds"
            ),
            source="E29, data/derived/e29_steer.json",
        ),
        _claim(
            "site_planner",
            (f"{site['fleet_by_arithmetic']} vehicles", f"{without_a_rule} vehicles"),
            ("README.md",),
            arithmetic=site["fleet_by_arithmetic"],
            carried={name: case["carried"] for name, case in site["cases"].items()},
            planned=site["planned"],
            changes={change["change"]: change["carried_with_it"] for change in site["changes"]},
            carried_on_other_demand=other_demand,
            figures=[
                f"{chargers - site['carried']} vehicles added by a quarter more chargers",
                f"{len(site['windows']) + sum(len(plan['windows']) for name, plan in shapes.items() if 'hourly' not in name)} fortnights in three cities",
            ],
            unit="vehicles: the planner's arithmetic for East Oakland, and the largest fleet carried with an operating rule taken away",
            conditions=(
                "`depot-twin plan` on sites/east_oakland.toml and sites/shape_*.toml: four windows a site, two "
                "draws a window, a search in steps of 25, carried in every window. A check of the planner "
                "against the study and of the fleet against other demand, with no bars"
            ),
            source="sites/plans/*.json",
        ),
        _claim(
            "what_the_runs_are_worth",
            ("four fortnights",),
            DOCUMENTS,
            share_of_variance_between_fortnights=moving["share_of_variance_between_fortnights"],
            runs_worth=moving["runs_worth"],
            figures=[f"about {moving['runs_worth'][0]:.0f} independent runs"],
            unit="how many independent runs the forty runs of a capacity figure are worth",
            conditions=(
                "a one-way split of the spread of rides served between the fortnight replayed and the draw within "
                "it, at every fleet and rule where rides served moves; each fortnight is scaled to the same rides "
                "a vehicle a day, and all four are from March to May 2024 in San Francisco"
            ),
            source="spread study, data/derived/capacity_spread.json",
        ),
        _claim(
            "area_today",
            (f"{fewest} to {most} vehicles",),
            DOCUMENTS,
            low=fewest,
            high=most,
            unit="vehicles the 20 km area would keep busy today",
            conditions=(
                "San Francisco's rides a resident, as the average of the last four quarters and as the latest "
                "quarter, applied to the East Bay's residents at 25 rides a vehicle a day; an upper reading, "
                "with no adjustment for lower density"
            ),
            source="E21, data/derived/e21_demand.json",
        ),
        _claim(
            "plan_energy_saving",
            (f"{_points(saving['median'])}%", f"{_points(saving['p10'])}% to {_points(saving['p90'])}%"),
            DOCUMENTS,
            value=saving["median"],
            low=saving["p10"],
            high=saving["p90"],
            unit="energy cost a kWh, the hourly plan less the threshold rule",
            conditions=f"500 vehicles, rides served level; {setting}; median and 10th to 90th percentile of {runs}",
            source="E23, data/derived/e23_capacity.json",
        ),
        _claim(
            "forecast_one_hour",
            (
                f"{_points(chicago['error']['trained_here']['mean'])}%",
                f"{_points(chicago['error']['last_week']['mean'])}%",
            ),
            ("README.md", "docs/BRIEF.md"),
            figures=[
                f"{_points(chicago['error']['pretrained']['mean'])}% for the pretrained model",
                f"{-100 * chicago['difference']['pretrained_less_trained_here']['mean']:.2f} points ahead",
                f"{_points(chicago_base['error']['mean'])}% for an average of past weeks scaled by the day so far",
                f"{-100 * chicago_base['difference']['trained_here_less_baseline']['mean']:.1f} points ahead of it in Chicago",
                f"about {round(-100 * sum(ny) / len(ny)):.0f} points ahead of it in New York",
                "90% range",
            ],
            against_a_stronger_naive_forecast={
                name: series["1h"]["difference"] | {"baseline": series["1h"]["error"]}
                for name, series in baseline["series"].items()
            },
            trained_here=chicago["error"]["trained_here"],
            same_hour_last_week=chicago["error"]["last_week"],
            pretrained=chicago["error"]["pretrained"],
            pretrained_less_trained_here=chicago["difference"]["pretrained_less_trained_here"],
            unit="total absolute error over total rides, one hour ahead, mean of weekly figures",
            conditions=(
                f"Chicago ride-hail, {backtest['weeks']} weeks each forecast from the days before it; ranges "
                "are the 5th to 95th percentile of the mean when whole weeks are resampled"
            ),
            source="E24, data/derived/e24_backtest.json",
        ),
        _claim(
            "fleet_cost_share",
            (f"{account['split'][base]['fleet_cost_share_of_revenue']:.0%}",),
            ("docs/BRIEF.md",),
            figures=[
                f"{account['split'][base]['energy_share_of_revenue']:.1%} of revenue is energy",
                f"under {int(account['split'][base]['energy_share_of_revenue'] * 100) + 1}%",
            ],
            value=account["split"][base]["fleet_cost_share_of_revenue"],
            energy_share_of_revenue=account["split"][base]["energy_share_of_revenue"],
            unit="share of fare revenue spent on owning and running the vehicles",
            conditions=(
                f"{base} vehicles on one feeder, the account of the capacity test's runs; both inputs are assumed "
                "($60,000 a vehicle a year and $100 a vehicle a day) and have no public source"
            ),
            source="account study on E23, data/derived/account_study.json",
        ),
    ]


# Inputs and settings the documents name, each with its unit. They are not results: each is set in the place given.
STATED = {
    "2.75 MW": "published headroom a feeder (docs/METHOD.md, section 1)",
    "20 km": "the radius of the service area quoted (E21)",
    "25 rides": "rides offered a vehicle a day (docs/METHOD.md, section 5)",
    "18 rides": "rides a vehicle a day, a moved input (E23)",
    "21.5 rides": "rides a vehicle a day, a moved input (E23)",
    "23 minutes": "a ride (docs/METHOD.md, section 5)",
    "28 minutes": "a ride, a moved input (E23)",
    "24 hours": "how far the plan looks ahead",
    "26 weeks": "weekly forecast origins (E24)",
    "99%": "the service floor (E23)",
    "500 vehicles": "a fleet size run (E23)",
    "600 vehicles": "a fleet size run (E23)",
    "650 vehicles": "a fleet size run (E25, E26)",
    "700 vehicles": "a fleet size run (E23)",
    "800 vehicles": "a fleet size run (E23)",
    "1,000 vehicles": "a fleet size run (E23)",
    "10%": "how far energy use was moved either way (E26)",
    "12%": "the charge at or under which a visit counts as starting on a low battery (dispatch.HARD_FLOOR_SOC)",
    "0.27": "kWh a mile, driving, one vehicle type (scenarios/v2, estimated)",
    "0.30 kWh": "a mile, driving, the other vehicle type (scenarios/v2, estimated)",
    "1.8": "kW always on, one vehicle type (scenarios/v2, estimated)",
    "2.0 kW": "always on, the other vehicle type (scenarios/v2, estimated)",
    "$550,000": "the second connection: $200 a kW for 2.75 MW, assumed (docs/METHOD.md, section 5)",
}
# Where every number must be in the ledger: the README, and the brief's statement of the decision.
SCANNED = (("README.md", None), ("docs/BRIEF.md", "## The decision"))
UNITS = (
    "million|vehicles|rides|months|points|runs|weeks|MW|MWh|kWh|kW|km|bars|tests|scenarios|cases|fortnights|draws"
    "|years|minutes|hours|people"
)
_NUMBER = re.compile(rf"(?<![A-Za-z\d.,])(\$?\d[\d,]*(?:\.\d+)?%?)(?:(?:th)?[ -]({UNITS})\b)?")
_NOT_PROSE = re.compile(r"```.*?```|`[^`\n]*`|\]\([^)]*\)|https?://\S+", re.S)


def numbers(text: str) -> list[str]:
    """The figures a passage quotes, each with the unit that follows it: "675 vehicles", "8.5 points", "61%".

    Code and link targets are left out; the words of a link and of a picture's caption are read like any
    other. A bare count under ten with no sign and no unit is a list number or a word's worth of detail.
    """
    found = []
    for raw, unit in _NUMBER.findall(_NOT_PROSE.sub(" ", text)):
        atom = raw.rstrip(",")
        bare = atom.strip("$%").replace(",", "")
        if not unit and atom == bare and "." not in bare and (float(bare) < 10 or 1990 <= float(bare) <= 2100):
            continue  # a small count, or a year
        found.append(f"{atom} {unit}" if unit else atom)
    return found


def listed_numbers(facts: dict) -> set[str]:
    """Every figure the ledger holds, with its unit: what its claims say, the figures beside them, the counts, the stated inputs."""
    listed = set(STATED) | {f"{facts['tests_run']} tests", f"{facts['bars_total']} bars", str(facts["bars_passed"])}
    for claim in facts["claims"]:
        for phrase in (*claim["says"], *claim.get("figures", [])):
            listed.update(numbers(phrase))
    return listed


def unlisted(text: str, listed: set[str]) -> list[str]:
    """The figures a passage quotes that are in no claim and are not a stated input, in order, once each.

    A figure with a unit must be listed with that unit. A figure without one ("600 and 650 vehicles" gives
    a bare 600) passes when the ledger holds that number under any unit.
    """
    bare = {phrase.split(" ")[0] for phrase in listed}
    wrong = [phrase for phrase in numbers(text) if phrase not in listed and (" " in phrase or phrase not in bare)]
    if _NOT_PROSE.sub(" ", text).count("`") % 2:
        wrong.append("an unclosed code mark, which hides what follows it")
    return list(dict.fromkeys(wrong))


def _section(text: str, heading: str | None) -> str:
    if heading is None:
        return text
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end > 0 else len(text)]


def public_facts() -> dict:
    """The count of bars and the claim ledger."""
    table = rows()
    scored = [r for r in table if r["bars"]]
    return {
        "tests_run": len(table),
        "bars_passed": sum(r["passed"] for r in scored),
        "bars_total": sum(r["bars"] for r in scored),
        "claims": claims(),
    }


def statements(facts: dict | None = None) -> dict[str, list[str]]:
    """What each headline document must say, word for word: the count of bars and every claim stated in it."""
    f = facts or public_facts()
    wanted = {name: [f"{f['bars_passed']} of {f['bars_total']} bars"] for name in DOCUMENTS}
    for claim in f["claims"]:
        for name in claim["stated_in"]:
            wanted[name] += claim["says"]
    return wanted


# The count of bars is quoted in many places. Wherever a public file says "N of M bars", it is this count.
BARS_QUOTED = re.compile(r"\b(\d+) of (\d+) bars\b")


def _public_files(root: Path) -> list[Path]:
    files = [root / name for name in (*DOCUMENTS, *OTHER_PUBLIC)]
    for pattern in PAGE_SOURCES:
        files += sorted(root.glob(pattern))
    return [path for path in files if path.exists()]


def problems(root: Path = Path(".")) -> list[str]:
    """Every headline a document should state and does not, and every other count of bars than the scoreboard's."""
    facts = public_facts()
    wrong = []
    for name, wanted in statements(facts).items():
        text = (root / name).read_text()
        wrong += [f"{name}: does not say {phrase!r}" for phrase in wanted if phrase not in text]
    listed = listed_numbers(facts)
    for name, heading in SCANNED:
        passage = _section((root / name).read_text(), heading)
        wrong += [f"{name}: quotes {atom}, which is in no claim" for atom in unlisted(passage, listed)]
    for path in _public_files(root):
        for passed, total in BARS_QUOTED.findall(path.read_text()):
            # A single test's own score ("4 of 4 bars") is not the project's count.
            if int(total) > 20 and (int(passed), int(total)) != (facts["bars_passed"], facts["bars_total"]):
                wrong.append(f"{path.relative_to(root)}: says {passed} of {total} bars")
    return wrong


def write(path: str | Path = "docs/FACTS.json") -> Path:
    """Write the facts beside the documents that quote them."""
    target = Path(path)
    from depot_twin import provenance

    payload = public_facts() | {"code": provenance.page_stamp("docs/FACTS.json")}
    target.write_text(json.dumps(payload, indent=1) + "\n")
    return target
