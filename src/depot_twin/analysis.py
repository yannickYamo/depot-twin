"""What the account says once its guesses are moved: read from recorded runs, with nothing run again.

The account prices every run with one value for each input. Several of those inputs have no public
source, and two of them, what a vehicle costs and what running it costs, are larger than everything the
depot itself decides. This module reads the capacity test's runs (E23), which carry their own account,
and answers four questions a reader of the account should ask before trusting a ranking:

- what the depot contributes before the fleet's own cost, which is the part the twin models;
- how dear a lost ride has to be before a larger, shorter fleet stops out-earning a smaller one;
- which input moves the result most, each moved alone across a stated range;
- what it costs to apply for the second feeder late, across the growth readings and connection lead times.

Every parameter here is labelled as measured, published or assumed, with its range. The output is a study
with no bars: `data/derived/account_study.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from depot_twin import provenance
from depot_twin.data import data_dir

DEPOT_LINES = ("energy_tariff", "subscription", "chargers", "buffer", "staff", "land", "connection")
FLEET_LINES = ("vehicles", "vehicle_operations")
DAYS_PER_MONTH = 365.0 / 12.0

# Each input the account takes: its value, the range it is moved over, and where the value comes from.
ASSUMPTIONS = (
    ("fare", "Fare a ride, $", 19.69, (17.72, 21.66), "published price survey; moved 10% each way"),
    ("lost_ride", "A lost ride beyond its fare, $", 20.0, (0.0, 60.0), "assumed; no public source"),
    ("vehicle_year", "A vehicle, $ a year", 60_000.0, (30_000.0, 100_000.0), "assumed; no public source"),
    ("operations_day", "Running a vehicle, $ a day", 100.0, (50.0, 250.0), "assumed; no public source"),
    ("energy_price", "Energy price, against the tariff", 1.0, (0.8, 1.2), "published tariff; moved 20% each way"),
    ("connection_kw", "Grid connection, $ a kW", 200.0, (100.0, 400.0), "assumed, inside published ranges"),
    ("land_month", "Land, $ a month", 217_500.0, (150_000.0, 300_000.0), "assumed for 14.5 industrial acres"),
    ("staff_hour", "A person on site, $ an hour", 40.0, (30.0, 55.0), "assumed loaded cost"),
)
LEAD_MONTHS = (24, 36, 48)  # assumed: a new feeder takes two to four years from application
APPLY_AT = (0, 12, 24)  # months after lease signing
DISCOUNT = (0.08, 0.10)  # assumed cost of capital, a year


def _mean(rows: list[dict], key: str) -> float:
    return float(np.mean([row[key] for row in rows]))


def designs(sweep: dict) -> dict[tuple, dict]:
    """The sweep's designs with their seeds averaged: lines a day, rides lost, rides served."""
    groups: dict[tuple, list[dict]] = {}
    for row in sweep["rows"]:
        groups.setdefault((row["feeder"], row["fleet"], row["chargers"], row["control"]), []).append(row)
    out = {}
    for key, rows in groups.items():
        lines = {name: float(np.mean([row["per_day"][name] for row in rows])) for name in rows[0]["per_day"]}
        out[key] = {
            "lines": lines,
            "contribution": _mean(rows, "contribution_per_day"),
            "lost": _mean(rows, "rides_lost_per_day"),
            "served": _mean(rows, "rides_served_share"),
            "fleet": key[1],
        }
    return out


def split(design: dict) -> dict:
    """The depot's contribution before the fleet's own cost, the fleet's cost, and the lost-ride charge, a day."""
    lines = design["lines"]
    depot = lines["revenue"] - sum(lines[name] for name in DEPOT_LINES)
    fleet = sum(lines[name] for name in FLEET_LINES)
    return {
        "depot_contribution": round(depot, 0),
        "fleet_cost": round(fleet, 0),
        "lost_ride_charge": round(lines["reliability"], 0),
        "contribution": round(depot - fleet - lines["reliability"], 0),
        "energy_share_of_revenue": round(lines["energy_tariff"] / lines["revenue"], 4),
        "fleet_cost_share_of_revenue": round(fleet / lines["revenue"], 4),
    }


def break_even_lost_ride(smaller: dict, larger: dict, charged: float) -> float | None:
    """The value of a lost ride, beyond its fare, at which the larger fleet stops earning more than the smaller."""
    more_lost = larger["lost"] - smaller["lost"]
    if more_lost <= 0:
        return None
    return round(charged + (larger["contribution"] - smaller["contribution"]) / more_lost, 1)


def moved(design: dict, assumptions: dict, name: str, value: float) -> float:
    """The design's contribution a day with one input set to another value and everything else as recorded."""
    lines = dict(design["lines"])
    fleet = design["fleet"]
    if name == "fare":
        lines["revenue"] *= value / 19.69
    elif name == "lost_ride":
        lines["reliability"] = design["lost"] * value
    elif name == "vehicle_year":
        lines["vehicles"] = fleet * value / 365.0
    elif name == "operations_day":
        lines["vehicle_operations"] = fleet * value
    elif name == "energy_price":
        lines["energy_tariff"] *= value
    elif name == "connection_kw":
        lines["connection"] *= value / assumptions["connection_per_kw"]
    elif name == "land_month":
        lines["land"] *= value / 217_500.0
    elif name == "staff_hour":
        lines["staff"] *= value / 40.0
    costs = sum(lines[key] for key in (*DEPOT_LINES, *FLEET_LINES, "reliability"))
    return lines["revenue"] - costs


def tornado(design: dict, assumptions: dict) -> list[dict]:
    """Each input moved alone across its range, widest swing first."""
    rows = []
    for name, label, value, (low, high), source in ASSUMPTIONS:
        at_low, at_high = moved(design, assumptions, name, low), moved(design, assumptions, name, high)
        rows.append(
            {
                "input": name,
                "label": label,
                "value": value,
                "low": low,
                "high": high,
                "source": source,
                "contribution_at_low": round(at_low, 0),
                "contribution_at_high": round(at_high, 0),
                "swing": round(abs(at_high - at_low), 0),
            }
        )
    return sorted(rows, key=lambda row: -row["swing"])


def feeder_timing(
    vehicles_today: float, capacity: float, growth: float, per_vehicle_day: float, capital: float
) -> list[dict]:
    """The cost of the second feeder arriving after it is needed, by when it is applied for.

    Demand grows at a monthly rate from today's vehicles. Past one feeder's capacity, each vehicle the site
    cannot carry is a vehicle-day of contribution not earned here, up to the vehicles a second feeder would
    add: demand beyond two feeders is a third feeder's question and is not charged to this one. What such
    a vehicle would earn is what the second feeder adds for it and nothing the site pays already, so the
    caller passes the added contribution a vehicle-day (`added_per_vehicle_day`), not the site's average.
    The feeder is in service a lead time after it is applied for, and its capital is paid then. Both
    streams are discounted at a yearly rate.
    """
    out = []
    horizon = 120
    for lead in LEAD_MONTHS:
        for rate in DISCOUNT:
            monthly = (1.0 + rate) ** (1.0 / 12.0) - 1.0
            base = None
            for apply_at in APPLY_AT:
                in_service = apply_at + lead
                short = 0.0
                for month in range(min(in_service, horizon)):
                    over = min(capacity, max(0.0, vehicles_today * (1.0 + growth) ** month - capacity))
                    short += over * DAYS_PER_MONTH * per_vehicle_day / (1.0 + monthly) ** month
                paid = capital / (1.0 + monthly) ** in_service
                value = -(short + paid)
                base = value if base is None else base
                out.append(
                    {
                        "lead_months": lead,
                        "discount": rate,
                        "apply_at_month": apply_at,
                        "in_service_month": in_service,
                        "contribution_not_earned": round(short, -3),
                        "capital_paid_present_value": round(paid, -3),
                        "against_applying_at_signing": round(value - base, -3),
                    }
                )
    return out


# A second feeder serves more vehicles on the same parcel: the land is paid for already, and the new
# connection is charged as capital when it goes into service, not as a line a day.
PAID_ALREADY = ("land", "connection")


def added_per_vehicle_day(design: dict, assumptions: dict, fleet_costs: str = "base") -> float:
    """What one more carried vehicle adds a day once a second feeder serves it.

    Fares less everything that grows with the fleet: energy, the feeder's subscription, chargers, any
    battery buffer, staff, the vehicle, running it, and the charge for lost rides. The parcel's land and the first connection are left out, being paid
    whether or not the vehicle is carried. `fleet_costs` puts the two unsourced fleet costs at the cheap
    or the dear end of their ranges together.
    """
    lines = dict(design["lines"])
    fleet = design["fleet"]
    if fleet_costs != "base":
        end = 2 if fleet_costs == "dear" else 1
        ranges = {name: (low, high) for name, _, _, (low, high), _ in ASSUMPTIONS}
        lines["vehicles"] = fleet * ranges["vehicle_year"][end - 1] / 365.0
        lines["vehicle_operations"] = fleet * ranges["operations_day"][end - 1]
    costs = sum(lines[key] for key in (*DEPOT_LINES, *FLEET_LINES, "reliability") if key not in PAID_ALREADY)
    return (lines["revenue"] - costs) / fleet


def timing_scenarios(
    levels: dict[str, float], growth: dict[str, float], capacity: float, added: dict[str, float], capital: float
) -> list[dict]:
    """What applying one and two years after signing costs, for every reading of today, growth, lead time, discount and fleet cost."""
    out = []
    for level, vehicles in levels.items():
        for reading, rate in growth.items():
            for costs, per_vehicle_day in added.items():
                cases = feeder_timing(vehicles, capacity, rate, per_vehicle_day, capital)
                for case in cases:
                    if case["apply_at_month"] == 0:
                        continue
                    out.append(
                        {
                            "today": level,
                            "growth": reading,
                            "fleet_costs": costs,
                            "lead_months": case["lead_months"],
                            "discount": case["discount"],
                            "applied_months_after_signing": case["apply_at_month"],
                            "cost_of_waiting": -case["against_applying_at_signing"],
                        }
                    )
    return out


def growth_since_the_footprint_settled(footprint: dict) -> dict:
    """The monthly growth of trips a day over the months after the served footprint last changed.

    The filings' quarters carry the tracts served. A quarter in which the footprint grows has trips rising
    because there are more residents to serve, and a rate read across it mixes that step with growth. This
    takes the months from the first full quarter after the last change and fits a straight line to the
    logarithm of trips a day.
    """
    import calendar

    quarters = footprint["quarters"]
    changed = max(k for k in range(len(quarters)) if k == 0 or quarters[k]["tracts"] != quarters[k - 1]["tracts"])
    months = [m for quarter in quarters[changed + 1 :] for m in quarter["months"]]
    per_day = [m["trips"] / calendar.monthrange(m["year"], m["month"])[1] for m in months]
    slope = float(np.polyfit(np.arange(len(per_day)), np.log(per_day), 1)[0])
    across = quarters[changed]["months"][0], quarters[changed + 1]["months"][0]
    step = [m["trips"] / calendar.monthrange(m["year"], m["month"])[1] for m in across]
    return {
        "footprint_last_changed_in": quarters[changed]["quarter"],
        "tracts_before_and_after": [quarters[changed - 1]["tracts"], quarters[changed]["tracts"]] if changed else None,
        "months_fitted": len(per_day),
        "from": f"{months[0]['year']}-{months[0]['month']:02d}",
        "to": f"{months[-1]['year']}-{months[-1]['month']:02d}",
        "growth_per_month": round(float(np.exp(slope) - 1.0), 4),
        "trips_a_day_first_and_last_month": [round(per_day[0]), round(per_day[-1])],
        "rise_in_trips_a_day_across_the_quarter_it_changed": round(step[1] / step[0] - 1.0, 3),
    }


def _span(values: list[float]) -> list[float]:
    return [min(values), max(values)]


def _capped_year(capacity: float, per_vehicle_day: float, lead: int, rate: float) -> float:
    """The most a year's delay can cost at one lead and discount: a feeder's worth of vehicles for the twelve months, in present value."""
    monthly = (1.0 + rate) ** (1.0 / 12.0) - 1.0
    return sum(
        capacity * DAYS_PER_MONTH * per_vehicle_day / (1.0 + monthly) ** month for month in range(lead, lead + 12)
    )


def timing_summary(
    scenarios: list[dict], growth: dict[str, float], capital: float, capacity: float = 0.0, per_vehicle_day: float = 0.0
) -> dict:
    """The scenarios read the way the documents quote them: a year late, by growth reading and by fleet cost."""
    slowest = min(growth, key=lambda name: growth[name])
    late = [s for s in scenarios if s["applied_months_after_signing"] == 12]
    base = [s for s in late if s["fleet_costs"] == "base"]
    early = [
        capital / (1.0 + rate) ** (lead / 12.0) - capital / (1.0 + rate) ** (lead / 12.0 + 1.0)
        for lead in LEAD_MONTHS
        for rate in DISCOUNT
    ]
    return {
        "scenarios": len(late),
        "slowest_growth_reading": slowest,
        "a_year_late_at_base_costs_on_the_faster_growth_readings": _span(
            [s["cost_of_waiting"] for s in base if s["growth"] != slowest]
        ),
        "a_year_late_at_base_costs_on_the_slowest_growth_reading": _span(
            [s["cost_of_waiting"] for s in base if s["growth"] == slowest]
        ),
        "a_year_late_across_fleet_costs": _span([s["cost_of_waiting"] for s in late]),
        # Where demand is past two feeders' worth for the whole year of delay, the loss is the cap: one
        # feeder's vehicles for twelve months. These cases say nothing more than that.
        "base_cost_scenarios_at_the_cap": sum(
            1
            for s in base
            if capacity
            and s["cost_of_waiting"]
            >= _capped_year(capacity, per_vehicle_day, s["lead_months"], s["discount"])
            # Less what paying for the feeder a year later saves, and the rounding of each case to a thousand.
            - capital / (1.0 + s["discount"]) ** (s["lead_months"] / 12.0)
            + capital / (1.0 + s["discount"]) ** (s["lead_months"] / 12.0 + 1.0)
            - 2000.0
        ),
        "base_cost_scenarios": len(base),
        "a_year_late_by_fleet_costs_on_the_faster_growth_readings": {
            costs: _span([s["cost_of_waiting"] for s in late if s["fleet_costs"] == costs and s["growth"] != slowest])
            for costs in ("cheap", "base", "dear")
        },
        # Applying a year sooner than needed pays the capital a year sooner: its carrying cost.
        "carrying_cost_of_applying_a_year_early": [round(min(early), -3), round(max(early), -3)],
        "capital_at_risk_if_the_second_feeder_is_never_needed": capital,
    }


def from_capacity_runs(capacity: dict, charged: float | None = None) -> dict[int, dict]:
    """The account of each fleet size under the rule that carried most, from the capacity test's own runs.

    These are the runs the capacity figure comes from: the filed cadence, four fortnights, ten draws. The
    lines are the mean over those runs, so the account and the capacity are read off the same depot.
    Given what a lost ride is charged, the rides lost are the mean the lines were charged for, so that
    moving an input starts from the lines' own total; without it they are the median run's.
    """
    best = capacity["rules"][capacity["best_rule"]]["by_size"]
    return {
        int(size): {
            "lines": row["per_day"],
            "contribution": row["contribution_per_day"]["median"],
            "contribution_range": [row["contribution_per_day"]["p10"], row["contribution_per_day"]["p90"]],
            "lost": row["per_day"]["reliability"] / charged if charged else row["rides_lost_per_day"]["median"],
            "served": row["median"],
            "fleet": int(size),
        }
        for size, row in best.items()
    }


def carried_fleet(derived: Path) -> tuple[int, dict | None]:
    """The largest fleet one feeder carries at the estimated energy use, with the rows of every fleet run there.

    E23 moves the fleet a hundred vehicles at a time, E25 ran the fleet halfway between two steps, and E26
    ran the fleets around it in steps of 25. The answer is the largest fleet any of them carried; the rows
    are theirs put together, by fleet size, under the rule that waits for a free charger.
    """
    capacity = json.loads((derived / "e23_capacity.json").read_text())
    carried = capacity["capacity"]
    rows: dict[str, dict] = {}
    margin = derived / "e26_margin.json"
    if margin.exists():
        record = json.loads(margin.read_text())
        for size, row in record["by_energy"]["1"]["by_size"].items():
            # E26's rows hold one figure where the capacity test's hold a spread: read both the same way.
            rows[size] = {
                **row,
                "contribution_per_day": {"median": row["contribution_per_day"]},
                "rides_lost_per_day": {"median": row["rides_lost_per_day"]},
            }
        carried = max(carried or 0, record["carried"]["1"] or 0)
    between = derived / "e25_between.json"
    if between.exists():
        record = json.loads(between.read_text())
        rows |= record.get("by_size", {})
        if record["carried"]:
            carried = max(carried or 0, record["size"])
    if not rows:
        return carried, None
    return carried, {"by_size": rows}


def _in_every_fortnight(row: dict) -> bool:
    return all(row.get("carried_by_fortnight", {"": True}).values())


def planned_fleet(derived: Path) -> tuple[int, dict | None]:
    """The fleet to plan one feeder for: carried at the estimated energy use and, with margin, at 10% more.

    E26 measures it. Its registered rule is the largest fleet carried at both levels of energy use. The
    plan asks one thing more of the higher level, as E25 asked of its fleet: carried in each of the four
    fortnights taken alone, so that the plan does not rest on which weeks were replayed. Without E26's
    record the plan is the carried fleet.
    """
    margin = derived / "e26_margin.json"
    if not margin.exists():
        return carried_fleet(derived)[0], None
    record = json.loads(margin.read_text())
    above = record["by_energy"][f"{record['margin']:g}"]
    at_estimate = record["by_energy"]["1"]["by_size"]
    planned = None
    # Smallest fleet first, stopping at the first that fails with more energy use: a plan is a fleet with
    # every smaller one sound. It is also a fleet run at the estimate, so that it has figures at both levels.
    for size in sorted(int(size) for size in above["by_size"]):
        row = above["by_size"][str(size)]
        if size > (above["capacity"] or 0) or size > (record["carried"]["1"] or 0) or not _in_every_fortnight(row):
            break
        if str(size) in at_estimate:
            planned = size
    if planned is None:
        raise ValueError("E26 carried no fleet in every fortnight at both levels of energy use: there is no plan")
    return planned, record


def demand_at(demand: dict, carried: int) -> dict:
    """E21's areas with their months counted against a carried fleet other than the step E21 was scored on.

    E21 counts the months until an area outgrows one feeder against E23's hundred-vehicle step. Where E25
    carried the fleet between two steps, the same arithmetic is done against that fleet: the same levels of
    demand today and the same readings of growth, and nothing else changed.
    """
    from depot_twin.cadence import months_until

    if carried == demand["capacity_one_feeder"]:
        return demand["areas"]
    growth = demand["growth_per_month_by_estimate"]
    rate = demand["growth_per_month"]

    def by_estimate(vehicles: float) -> dict:
        return {name: months_until(carried, vehicles, g) for name, g in growth.items()}

    areas = {}
    for name, area in demand["areas"].items():
        vehicles = area["vehicles_at_25_rides"]
        new = {
            **area,
            "feeders_needed": max(1, int(np.ceil(vehicles / carried))),
            "months_until_second_feeder": months_until(carried, vehicles, rate),
            "months_until_second_feeder_at_half_the_growth": months_until(carried, vehicles, rate / 2.0),
            "months_until_second_feeder_by_estimate": by_estimate(vehicles),
        }
        if "by_level" in area:
            new["by_level"] = {
                level: {**row, "months_until_second_feeder_by_estimate": by_estimate(row["vehicles_at_25_rides"])}
                for level, row in area["by_level"].items()
            }
            months = [
                m for row in new["by_level"].values() for m in row["months_until_second_feeder_by_estimate"].values()
            ]
            # E21's own rule: the range of the readings under which the area does outgrow the fleet.
            reached = [m for m in months if m is not None]
            new["months_until_second_feeder_range"] = [min(reached), max(reached)] if reached else None
        areas[name] = new
    return areas


def break_even_over_runs(capacity: dict, smaller: int, larger: int, charged: float) -> dict | None:
    """The break-even value of a lost ride between two fleets, run for run: its middle and the range most runs fall in.

    Each fortnight and draw gives one figure: what the larger fleet earns over the smaller, per extra ride
    it loses. Runs where the larger fleet loses no more rides have no break-even; when that is most runs,
    there is no trade between the two fleets to price, and nothing is returned.
    """
    mine = [r for r in capacity["runs"] if r["label"] == "base" and r["rule"] == capacity["best_rule"]]
    pick = lambda size: {(r["window"], r["seed"]): r for r in mine if r["size"] == size}  # noqa: E731
    a, b = pick(smaller), pick(larger)
    values = []
    for key in sorted(a):
        if key not in b:
            continue
        more_lost = b[key]["rides_lost_per_day"] - a[key]["rides_lost_per_day"]
        if more_lost > 0:
            values.append(charged + (b[key]["contribution_per_day"] - a[key]["contribution_per_day"]) / more_lost)
    if len(values) < len(a) / 2:
        # In most runs the larger fleet loses no more rides than the smaller: there is no trade to price.
        return None
    return {
        "median": round(float(np.median(values)), 1),
        "p10": round(float(np.quantile(values, 0.1)), 1),
        "p90": round(float(np.quantile(values, 0.9)), 1),
        "runs_where_the_larger_fleet_loses_more_rides": len(values),
        "runs": len(a),
    }


def account_study() -> Path:
    """Read the capacity runs, the sweep and the demand record, and write what the account says when its guesses move."""
    from depot_twin.cadence import months_until

    derived = data_dir() / "derived"
    sweep = json.loads((derived / "e19_sweet_spot.json").read_text())
    demand = json.loads((derived / "e21_demand.json").read_text())
    capacity = json.loads((derived / "e23_capacity.json").read_text())
    settled = growth_since_the_footprint_settled(json.loads((derived / "footprint.json").read_text()))
    assumptions = sweep["assumptions"]
    one = from_capacity_runs(capacity, assumptions["lost_ride_cost"])
    sizes = sorted(one)
    # The fleet between two steps, where E25 ran it on the same fortnights and draws, joins the account.
    carried, between = carried_fleet(derived)
    if between:
        # Only the fleets whose runs kept their account line by line can join it.
        lined = {"by_size": {size: row for size, row in between["by_size"].items() if "per_day" in row}}
        one |= from_capacity_runs({"rules": {"only": lined}, "best_rule": "only"}, assumptions["lost_ride_cost"])
    planned, _ = planned_fleet(derived)
    base_fleet = planned if planned in one else (carried or sizes[0])
    base = one[base_fleet]
    area = demand["areas"]["east_bay_20km"]
    capital = assumptions["connection_per_kw"] * 2750.0
    swings = tornado(base, assumptions)
    growth = demand["growth_per_month_by_estimate"]
    levels = {name: row["vehicles_at_25_rides"] for name, row in area["by_level"].items()}
    added = {costs: round(added_per_vehicle_day(base, assumptions, costs), 2) for costs in ("cheap", "base", "dear")}
    # A vehicle that would lose money is not put on the road: its absence costs nothing, not a negative sum.
    valued = {costs: max(value, 0.0) for costs, value in added.items()}
    scenarios = timing_scenarios(levels, growth, base_fleet, valued, capital)
    timing = {
        name: {
            "growth_per_month": round(rate, 4),
            "months_until_one_feeder_is_full": {
                level: months_until(base_fleet, vehicles, rate) for level, vehicles in levels.items()
            },
        }
        for name, rate in growth.items()
    }
    payload = {
        "study": "account",
        "setting": "the capacity test's runs: the filed cadence, the rule that carried most, four fortnights by ten draws",
        "base_design": {"feeder": "one_feeder", "control": capacity["best_rule"], "fleet": base_fleet},
        "carried_at_the_estimated_energy_use": carried,
        "split": {
            str(fleet): {**split(design), "contribution_range": [round(v, 0) for v in design["contribution_range"]]}
            for fleet, design in sorted(one.items())
        },
        "break_even_lost_ride": {
            f"{larger}_against_{smaller}": break_even_over_runs(
                capacity, smaller, larger, assumptions["lost_ride_cost"]
            )
            for smaller, larger in zip(sizes, sizes[1:], strict=False)
        },
        "tornado": swings,
        "feeder_timing": {
            "kind": "scenario table, no bars",
            "capital": capital,
            "one_feeder_planned_for": base_fleet,
            "site_average_contribution_per_vehicle_day": round(base["contribution"] / base_fleet, 2),
            "added_contribution_per_vehicle_day": added,
            "valued_at_per_vehicle_day": valued,
            "most_a_year_late_can_cost": round(base_fleet * valued["base"] * 365.0, -3),
            "left_out_as_paid_already": list(PAID_ALREADY),
            "vehicles_today_by_level": levels,
            "lead_months_assumed": list(LEAD_MONTHS),
            "discount_assumed": list(DISCOUNT),
            "by_growth_estimate": timing,
            # Which reading of growth the months after the footprint last changed support.
            "growth_since_the_footprint_settled": settled
            | {
                "nearest_reading": min(growth, key=lambda name: abs(growth[name] - settled["growth_per_month"])),
                "months_until_one_feeder_is_full": {
                    level: months_until(base_fleet, vehicles, settled["growth_per_month"])
                    for level, vehicles in levels.items()
                },
            },
            "summary": timing_summary(scenarios, growth, capital, base_fleet, valued["base"]),
            "scenarios": scenarios,
        },
        "code": provenance.page_stamp("data/derived/account_study.json"),
    }
    target = derived / "account_study.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


def _between_and_within(runs: list[dict], key: str) -> dict:
    """How much of the spread of a figure over fortnights-by-draws is between fortnights: a one-way split."""
    windows = sorted({r["window"] for r in runs})
    groups = [np.array([r[key] for r in runs if r["window"] == window], dtype=float) for window in windows]
    per = len(groups[0])
    means = np.array([g.mean() for g in groups])
    within = float(np.mean([g.var(ddof=1) for g in groups]))
    between = max(float(means.var(ddof=1)) - within / per, 0.0)
    share = between / (between + within) if between + within > 0 else 0.0
    return {
        "by_fortnight": {window: round(float(mean), 4) for window, mean in zip(windows, means, strict=True)},
        "sd_between_fortnights": round(float(np.sqrt(between)), 4),
        "sd_between_draws": round(float(np.sqrt(within)), 4),
        "share_of_variance_between_fortnights": round(share, 3),
        # Forty runs that mostly repeat four fortnights are worth this many independent runs.
        "runs_worth": round(len(runs) / (1.0 + (per - 1) * share), 1),
        "runs": len(runs),
    }


def spread_study() -> Path:
    """Where the spread of the capacity runs comes from: the fortnight replayed, or the draw within it.

    Every capacity figure is quoted over four fortnights by ten draws. The draws change which vehicle is
    which and how work falls between them; the fortnights change the demand. This reads the recorded runs
    and splits the spread of rides served and of low-battery arrivals between the two, fleet by fleet,
    and writes `data/derived/capacity_spread.json`.
    """
    derived = data_dir() / "derived"
    capacity = json.loads((derived / "e23_capacity.json").read_text())
    margin = json.loads((derived / "e26_margin.json").read_text())
    best = capacity["best_rule"]
    base = [r for r in capacity["runs"] if r["label"] == "base"]
    cells: dict[str, list[dict]] = {}
    for rule in capacity["rules"]:
        for size in sorted({r["size"] for r in base}):
            cells[f"{rule}, {size} vehicles"] = [r for r in base if (r["rule"], r["size"]) == (rule, size)]
    for policy in ("slot_power", "need_first"):
        cells[f"power rule {policy}, 1000 vehicles"] = [
            r for r in capacity["runs"] if r["label"] == "power" and r["policy"] == policy
        ]
    for energy, group in margin["by_energy"].items():
        for size in group["by_size"]:
            cells[f"{best}, {size} vehicles, energy use x{energy}"] = [
                r for r in margin["runs"] if (r["label"], r["rule"], r["size"]) == (f"energy_{energy}", best, int(size))
            ]
    rows = {
        name: {
            "served": _between_and_within(runs, "served"),
            "arrived_at_floor_share": _between_and_within(runs, "arrived_at_floor_share"),
        }
        for name, runs in cells.items()
        if runs
    }
    # Only where a figure moves at all is the split worth reading.
    moving = [row["served"] for row in rows.values() if row["served"]["sd_between_fortnights"] >= 0.002]
    payload = {
        "study": "the spread of the capacity runs, split between the fortnight replayed and the draw within it",
        "fortnights": capacity["windows"],
        "draws_a_fortnight": len(capacity["seeds"]),
        "rows": rows,
        "where_rides_served_moves": {
            "cells": len(moving),
            "share_of_variance_between_fortnights": [
                min(m["share_of_variance_between_fortnights"] for m in moving),
                max(m["share_of_variance_between_fortnights"] for m in moving),
            ],
            "runs_worth": [min(m["runs_worth"] for m in moving), max(m["runs_worth"] for m in moving)],
        },
        "code": provenance.page_stamp("data/derived/capacity_spread.json"),
    }
    target = derived / "capacity_spread.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target
