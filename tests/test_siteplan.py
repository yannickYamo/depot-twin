"""The site planner: a site file is read strictly, builds the same depot the study ran, and its verdict is the study's rule."""

import re
from pathlib import Path

import pytest

from depot_twin import cadence, siteplan

ROOT = Path(__file__).parent.parent
EAST_OAKLAND = ROOT / "sites" / "east_oakland.toml"

MINIMAL = """
[site]
name = "A test site"
[grid]
kw = 1000
[vehicles.one]
share = 1.0
capacity_kwh = 80
max_dc_kw = 100
max_ac_kw = 11
drive_kwh_per_mile = 0.3
always_on_kw = 2.0
[demand]
windows = ["2024-04-15"]
"""


def site_file(tmp_path, text: str) -> Path:
    path = tmp_path / "site.toml"
    path.write_text(text)
    return path


def test_a_minimal_site_takes_the_study_s_defaults(tmp_path):
    site = siteplan.load(site_file(tmp_path, MINIMAL))
    assert site["fleet"]["rides_per_vehicle_day"] == 25.0
    assert site["rules"]["calling"] == "threshold_waits"
    assert site["policy"]["service_floor"] == 0.99
    assert site["fleet"]["parked_load"] == "unknown"


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (("kw = 1000", "kw = 0"), "[grid] kw must be above zero"),
        (("share = 1.0", "share = 0.7"), "shares must add to 1"),
        (("[demand]", "[fleet]\nrides_per_day = 20\n[demand]"), "unknown field 'rides_per_day'"),
        (("always_on_kw = 2.0\n", ""), "[vehicles.one] needs always_on_kw"),
        (('windows = ["2024-04-15"]', "windows = []"), "at least one window"),
        (("[grid]\nkw = 1000", ""), "[grid] is missing"),
    ],
)
def test_a_wrong_site_file_is_refused_with_the_field_named(tmp_path, change, says):
    with pytest.raises(siteplan.SiteError, match=says.replace("[", r"\[").replace("]", r"\]")):
        siteplan.load(site_file(tmp_path, MINIMAL.replace(*change)))


def test_every_problem_is_reported_at_once(tmp_path):
    text = MINIMAL.replace("kw = 1000", "kw = 0").replace("share = 1.0", "share = 0.7")
    with pytest.raises(siteplan.SiteError) as caught:
        siteplan.load(site_file(tmp_path, text))
    assert "kw must be above zero" in str(caught.value) and "shares must add to 1" in str(caught.value)


@pytest.mark.parametrize("size", [500, 600, 675])
def test_the_east_oakland_file_builds_the_depot_the_study_ran(size):
    site = siteplan.load(EAST_OAKLAND)
    fleet, depot = siteplan.build(site, size)
    chosen = json.loads((DERIVED / "e22_cadence.json").read_text())["chosen"]
    was_fleet, was_depot = cadence._fleet_and_depot(size, chosen["leg"], chosen["clean_every"], chosen["chargers"])
    assert depot == was_depot.__class__(**{**was_depot.__dict__, "name": depot.name})
    for field in was_fleet.__dataclass_fields__:
        if field != "models":
            assert getattr(fleet, field) == getattr(was_fleet, field), field
    for mine, theirs in zip(fleet.models, was_fleet.models, strict=True):
        assert (mine.capacity_kwh, mine.max_dc_kw, mine.drive_kwh_per_mile, mine.always_on_kw, mine.dc_curve) == (
            theirs.capacity_kwh,
            theirs.max_dc_kw,
            theirs.drive_kwh_per_mile,
            theirs.always_on_kw,
            theirs.dc_curve,
        )


def test_energy_use_and_one_change_reach_the_depot_that_is_built():
    site = siteplan.load(EAST_OAKLAND)
    fleet, depot = siteplan.build(site, 600)
    more, bigger = siteplan.build(site, 600, energy=1.1, change={"chargers": 1.25, "grid": 2.0})
    assert more.models[0].drive_kwh_per_mile == pytest.approx(fleet.models[0].drive_kwh_per_mile * 1.1)
    assert more.models[0].always_on_kw == pytest.approx(fleet.models[0].always_on_kw * 1.1)
    assert depot.chargers[0].count == 80 and bigger.chargers[0].count == 99  # ceil(600 x 0.132), and a quarter more
    assert bigger.site_limit_kw == 2 * depot.site_limit_kw


def run(size: int, window: str, served: float, low: float) -> dict:
    return {
        "size": size,
        "window": window,
        "served": served,
        "arrived_at_floor_share": low,
        "grid_share_used": 0.9,
        "grid_at_limit_share": 0.5,
        "waiting_for_a_charger_share": 0.0,
        "feeder_kwh_per_vehicle_day": 90.0,
        "settled": True,
    }


POLICY = {"service_floor": 0.99, "low_battery_visits_at_most": 0.5}


def test_a_fleet_is_carried_only_when_every_window_carries_it():
    runs = [run(100, w, 1.0, 0.0) for w in ("a", "b") for _ in range(2)]
    runs += [run(125, "a", 1.0, 0.0), run(125, "a", 1.0, 0.0), run(125, "b", 0.98, 0.0), run(125, "b", 0.98, 0.0)]
    result = siteplan.verdict(runs, [100, 125], POLICY)
    assert result["carried"] == 100
    assert result["by_size"]["125"]["windows_carried"] == 1
    assert result["by_size"]["125"]["served_lowest_window"] == 0.98


def test_low_battery_visits_fail_a_window_whatever_the_rides_and_a_gap_stops_the_count():
    low = [run(100, "a", 1.0, 0.6), run(100, "a", 1.0, 0.6)]
    assert siteplan.verdict(low, [100], POLICY)["carried"] is None
    # A fleet that passes above one that fails, or above one not run, is not carried.
    runs = [run(100, "a", 0.9, 0.0), run(125, "a", 1.0, 0.0)]
    assert siteplan.verdict(runs, [100, 125], POLICY)["carried"] is None
    assert siteplan.verdict([run(125, "a", 1.0, 0.0)], [100, 125], POLICY)["carried"] is None


def test_an_hourly_file_is_spread_over_its_five_minute_steps(tmp_path):
    import pandas as pd

    counts = pd.Series(range(336), index=pd.date_range("2026-01-05", periods=336, freq="h"), name="rides")
    counts.rename_axis("time").to_csv(tmp_path / "week.csv")
    curves = siteplan.curves({"_folder": str(tmp_path)}, "week.csv")
    assert curves["counts"].shape == (14 * 288,)
    assert curves["counts"].sum() == pytest.approx(counts.sum())
    assert curves["counts"][12:24] == pytest.approx([1 / 12] * 12)
    counts.iloc[: 13 * 24].rename_axis("time").to_csv(tmp_path / "short.csv")
    with pytest.raises(siteplan.SiteError, match="fourteen days of counts, and this file holds 13"):
        siteplan.curves({"_folder": str(tmp_path)}, "short.csv")


def test_the_search_goes_up_while_fleets_are_carried_and_down_when_the_start_is_not(monkeypatch):
    site = siteplan.load(EAST_OAKLAND)

    def pretend(limit: int):
        def pool(jobs, workers, parked=False):
            return [run(job[2], w, 1.0 if job[2] <= limit else 0.9, 0.0) for job in jobs for w in [job[3]]]

        return pool

    monkeypatch.setattr(siteplan, "_pool", pretend(650))
    up, runs = siteplan.search(site, "as entered", 1.0, False, 600.0, 5)
    assert up["carried"] == 650
    assert {r["size"] for r in runs} == {600, 625, 650, 675}  # stops at the first pair that holds a failure
    monkeypatch.setattr(siteplan, "_pool", pretend(540))
    down, runs = siteplan.search(site, "as entered", 1.0, False, 600.0, 5)
    assert down["carried"] == 525
    assert {r["size"] for r in runs} == {500, 525, 550, 575, 600, 625}


def test_the_brief_says_the_plan_and_warns_when_energy_is_assumed():
    site = siteplan.load(EAST_OAKLAND)
    row = {"grid_share_used": 0.99, "feeder_kwh_per_vehicle_day": 92.4}
    result = {
        "site": "A <site>",
        "usable_kwh_a_day": 62700.0,
        "feeder_kwh_per_vehicle_day": 93.9,
        "fleet_by_arithmetic": 667,
        "fleets_run": [525, 700],
        "windows": ["a", "b", "c", "d"],
        "draws_a_window": 2,
        "cases": {"as entered": {"carried": 675, "by_size": {"675": row}}},
        "carried": 675,
        "planned": 600,
        "planned_rides_per_day": 15000.0,
        "carried_against_arithmetic": 1.012,
        "what_binds_past_the_carried_fleet": "the feeder's energy",
        "changes": [{"change": "a quarter more chargers", "says": "carries 675", "vehicles": 0}],
        "at_the_edge_of_the_fleets_run": False,
        "runs": 100,
        "inputs": {k: v for k, v in site.items() if not k.startswith("_")},
    }
    page = siteplan.brief(result)
    assert "Plan for 600 vehicles, 15,000 rides a day." in page
    assert "A &lt;site>" in page and "<site>" not in page
    assert "meter one vehicle" in page
    assert "widen" not in page.lower()
    assert "Lower [sweep] start" in siteplan.brief(result | {"planned": None})


# ---------------------------------------------------------------------------------------------------------
# The plans kept in the repository, against the study they have to give back.

import json  # noqa: E402

from depot_twin import analysis  # noqa: E402

PLANS = ROOT / "sites" / "plans"
DERIVED = ROOT / "data" / "derived"


def test_the_east_oakland_plan_gives_the_study_back():
    plan = json.loads((PLANS / "east_oakland.json").read_text())
    margin = json.loads((DERIVED / "e26_margin.json").read_text())
    parked = json.loads((DERIVED / "e27_parked.json").read_text())
    assert plan["carried"] == analysis.carried_fleet(DERIVED)[0] == margin["carried"]["1"]
    assert plan["planned"] == analysis.planned_fleet(DERIVED)[0]
    cases = {name: case["carried"] for name, case in plan["cases"].items()}
    assert cases["10% more energy on the road"] == plan["planned"]
    assert cases["systems on while parked"] == parked["by_energy"]["1"]["carried_in_every_fortnight"]
    # The arithmetic is within one step of what the simulation carries: the feeder's energy binds.
    assert abs(plan["fleet_by_arithmetic"] - plan["carried"]) <= 25
    assert plan["at_the_edge_of_the_fleets_run"] is False


def test_each_case_of_a_plan_is_bracketed_by_a_fleet_that_failed():
    for path in sorted(PLANS.glob("*.json")):
        plan = json.loads(path.read_text())
        for name, case in plan["cases"].items():
            above = case["by_size"][str(case["carried"] + 25)]
            assert above["windows_carried"] < len(plan["windows"]), (path.name, name)


def test_the_same_depot_carries_the_same_fleet_on_other_cities_weeks():
    carried = {path.stem: json.loads(path.read_text())["carried"] for path in sorted(PLANS.glob("shape_*.json"))}
    assert set(carried) == {"shape_chicago", "shape_new_york", "shape_san_francisco_hourly"}
    assert set(carried.values()) == {json.loads((PLANS / "east_oakland.json").read_text())["carried"]}


def test_every_site_file_in_the_repository_loads_and_has_its_demand():
    for path in sorted((ROOT / "sites").glob("*.toml")):
        site = siteplan.load(path)
        for window in site["demand"]["windows"]:
            assert siteplan.curves(site, window)["counts"].shape == (14 * 288,), (path.name, window)


# ---------------------------------------------------------------------------------------------------------
# Inputs the planner refuses, and what it says.


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (("kw = 1000", "kw = 2.75"), "[grid] kw = 2.75"),
        (("kw = 1000", "kw = 2750000"), "[grid] kw = 2.75e+06"),
        (("drive_kwh_per_mile = 0.3", "drive_kwh_per_mile = 30"), "drive_kwh_per_mile = 30"),
        (("always_on_kw = 2.0", "always_on_kw = 2000"), "always_on_kw = 2000"),
        (("capacity_kwh = 80", "capacity_kwh = 80000"), "capacity_kwh = 80000"),
        (("[demand]", "[fleet]\nrides_per_vehicle_day = 15000\n[demand]"), "rides_per_vehicle_day = 15000"),
        (("[demand]", "[fleet]\nride_minutes = 0.4\n[demand]"), "ride_minutes = 0.4"),
        (("[demand]", "[depot]\ncharger_kw = 60000\n[demand]"), "charger_kw = 60000"),
    ],
)
def test_a_value_outside_its_usual_range_is_refused_by_name_unless_allowed(tmp_path, change, field):
    assert change[0] in MINIMAL
    path = site_file(tmp_path, MINIMAL.replace(*change))
    with pytest.raises(siteplan.SiteError) as caught:
        siteplan.load(path)
    assert field in str(caught.value) and "--allow-unusual" in str(caught.value)
    kept = siteplan.load(path, allow_unusual=True)
    assert len(kept["_unusual"]) == 1 and field in kept["_unusual"][0]


def test_a_window_that_is_neither_a_recorded_fortnight_nor_a_file_is_refused_at_load(tmp_path):
    with pytest.raises(siteplan.SiteError, match="2031-01-01.*not a recorded fortnight.*2024-03-18"):
        siteplan.load(site_file(tmp_path, MINIMAL.replace("2024-04-15", "2031-01-01")))
    with pytest.raises(siteplan.SiteError, match="no file at .*mine.csv"):
        siteplan.load(site_file(tmp_path, MINIMAL.replace("2024-04-15", "mine.csv")))


def counts_file(tmp_path, start: str = "2026-01-05", freq: str = "h", periods: int = 336):
    import pandas as pd

    return pd.DataFrame({"time": pd.date_range(start, periods=periods, freq=freq), "rides": 10.0})


@pytest.mark.parametrize(
    ("spoil", "says"),
    [
        (lambda f: f.drop(index=100), "line 102"),  # a gap: the row after it is the first out of step
        (lambda f: f.iloc[list(range(50)) + [49] + list(range(50, 336))], "line 52"),  # a repeat
        (lambda f: f.iloc[list(range(20)) + [21, 20] + list(range(22, 336))], "line 22"),  # out of order
    ],
)
def test_a_file_of_counts_with_a_gap_a_repeat_or_rows_out_of_order_is_refused_by_line(tmp_path, spoil, says):
    spoil(counts_file(tmp_path)).to_csv(tmp_path / "week.csv", index=False)
    with pytest.raises(siteplan.SiteError, match=says):
        siteplan.curves({"_folder": str(tmp_path)}, "week.csv")


def test_a_file_of_counts_starts_on_a_monday_at_midnight(tmp_path):
    counts_file(tmp_path, start="2026-01-06").to_csv(tmp_path / "week.csv", index=False)
    with pytest.raises(siteplan.SiteError, match="starts on a Monday at 00:00"):
        siteplan.curves({"_folder": str(tmp_path)}, "week.csv")
    counts_file(tmp_path, start="2026-01-05 01:00").to_csv(tmp_path / "week.csv", index=False)
    with pytest.raises(siteplan.SiteError, match="starts on a Monday at 00:00"):
        siteplan.curves({"_folder": str(tmp_path)}, "week.csv")


def test_a_run_that_has_not_settled_does_not_carry_its_window():
    runs = [run(100, "a", 1.0, 0.0), run(100, "a", 1.0, 0.0) | {"settled": False}]
    result = siteplan.verdict(runs, [100], POLICY)
    assert result["carried"] is None
    assert result["by_size"]["100"]["windows"]["a"]["held_back_unsettled"] is True
    assert siteplan.verdict([run(100, "a", 1.0, 0.0)] * 2, [100], POLICY)["carried"] == 100


def test_the_brief_says_why_no_change_was_tried():
    plan = json.loads((PLANS / "east_oakland.json").read_text())
    off = siteplan.brief(plan | {"changes": [], "changes_skipped": "switched off"})
    assert "switches them off" in off and "No fleet was carried" not in off
    none = siteplan.brief(plan | {"changes": [], "changes_skipped": "no fleet carried"})
    assert "No fleet was carried, so no change was tried." in none


def test_a_plan_is_held_to_the_site_file_and_demand_files_it_was_made_from(tmp_path):
    import shutil

    from depot_twin import provenance

    for path in sorted(PLANS.glob("*.json")):
        assert not provenance._inputs_moved(path, ROOT), path.name
    (tmp_path / "sites" / "plans").mkdir(parents=True)
    shutil.copy(ROOT / "sites" / "east_oakland.toml", tmp_path / "sites" / "east_oakland.toml")
    shutil.copy(PLANS / "east_oakland.json", tmp_path / "sites" / "plans" / "east_oakland.json")
    assert not provenance._inputs_moved(tmp_path / "sites" / "plans" / "east_oakland.json", tmp_path)
    file = tmp_path / "sites" / "east_oakland.toml"
    file.write_text(file.read_text().replace("drive_kwh_per_mile = 0.30", "drive_kwh_per_mile = 0.33"))
    assert provenance._inputs_moved(tmp_path / "sites" / "plans" / "east_oakland.json", tmp_path)


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (("[grid]", "[grids]"), "[grid] is missing"),
        (("[demand]", "[fleets]\nride_minutes = 20\n[demand]"), "[fleets] is not a table the planner knows"),
        (('name = "A test site"', 'name = "A test site"\nplace = "here"'), "[site] has an unknown field 'place'"),
        (("windows =", "window = 1\nwindows ="), "[demand] has an unknown field 'window'"),
        (("share = 1.0", "share = 1.0\ncapacity = 80"), "[vehicles.one] has an unknown field 'capacity'"),
        (("[demand]", '[sources]\nenergie = "metered"\n[demand]'), "[sources] has an unknown field 'energie'"),
    ],
)
def test_a_misspelt_table_or_field_is_refused_wherever_it_is(tmp_path, change, says):
    with pytest.raises(siteplan.SiteError, match=re.escape(says)):
        siteplan.load(site_file(tmp_path, MINIMAL.replace(*change)))


def test_an_unknown_field_a_slip_of_units_and_a_bad_window_are_reported_together(tmp_path):
    text = MINIMAL.replace("kw = 1000", "kw = 1000\nkilowatts = 3").replace("= 0.3", "= 30").replace("-04-15", "-04-16")
    with pytest.raises(siteplan.SiteError) as fault:
        siteplan.load(site_file(tmp_path, text))
    for part in ("unknown field 'kilowatts'", "drive_kwh_per_mile = 30", "not a recorded fortnight"):
        assert part in str(fault.value)


def test_a_file_of_counts_with_a_gap_is_refused_when_the_site_file_is_read(tmp_path):
    counts_file(tmp_path).drop(index=100).to_csv(tmp_path / "week.csv", index=False)
    with pytest.raises(siteplan.SiteError, match=r"\[demand\] window week\.csv, line 102"):
        siteplan.load(site_file(tmp_path, MINIMAL.replace("2024-04-15", "week.csv")))


def test_a_change_says_when_a_fleet_met_the_bars_with_a_run_that_had_not_settled(monkeypatch):
    def pool(jobs, workers, parked=False):
        return [
            {
                "size": size,
                "window": window,
                "served": 0.995 if size <= 600 else 0.9,
                "arrived_at_floor_share": 0.1,
                "settled": size < 600,
                "grid_share_used": 0.9,
                "grid_at_limit_share": 0.5,
                "waiting_for_a_charger_share": 0.0,
                "feeder_kwh_per_vehicle_day": 94.0,
            }
            for _, _, size, window, _, _, _ in jobs
        ]

    monkeypatch.setattr(siteplan, "_pool", pool)
    site = siteplan.load(ROOT / "sites" / "east_oakland.toml")
    rows = {row["change"]: row for row in siteplan._changes(site, 600, 25, ["2024-04-15"], [1, 2], 1)}
    row = rows["feed the emptiest vehicle first"]
    assert row["carried_with_it"] == 550
    assert row["met_the_bars_unsettled"] == [600]
    assert row["says"] == "carries 550; 600 met both bars with a run that had not settled"


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("time,rides\n2026-01-05 00:00,3\n", "this file has 1 row(s)"),
        ("when,rides\n2026-01-05 00:00,3\n2026-01-05 01:00,3\n", "line 1: no time column"),
        ("time,rides\n2026-01-05 00:00,3\n2026-01-05 01:00,-2\n", "line 3: rides '-2' is below zero"),
        ("time,rides\n2026-01-05 00:00,3\nlater,2\n", "line 3: time 'later' is not a time"),
        ("time,rides\n2026-01-05 00:00,3\n2026-01-05 01:00,many\n", "line 3: rides 'many' is not a count"),
    ],
)
def test_a_malformed_file_of_counts_is_refused_with_its_line(tmp_path, text, says):
    (tmp_path / "week.csv").write_text(text)
    with pytest.raises(siteplan.SiteError, match=re.escape(says)):
        siteplan.load(site_file(tmp_path, MINIMAL.replace("2024-04-15", "week.csv")))


def test_demand_files_of_one_name_in_two_folders_are_hashed_apart(tmp_path):
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        counts_file(tmp_path).to_csv(tmp_path / folder / "week.csv", index=False)
    path = site_file(tmp_path, MINIMAL.replace('"2024-04-15"', '"a/week.csv", "b/week.csv"'))
    before = siteplan.made_from(path, siteplan.load(path))
    assert set(before) == {"site.toml", "a/week.csv", "b/week.csv"}
    frame = counts_file(tmp_path)
    frame.loc[5, "rides"] += 1
    frame.to_csv(tmp_path / "b" / "week.csv", index=False)
    after = siteplan.made_from(path, siteplan.load(path))
    assert after["a/week.csv"] == before["a/week.csv"] and after["b/week.csv"] != before["b/week.csv"]


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (("kw = 1000", 'kw = "1000"'), "[grid] kw must be a number, not '1000'"),
        (("capacity_kwh = 80", "capacity_kwh = true"), "[vehicles.one] capacity_kwh must be a number, not True"),
        (('windows = ["2024-04-15"]', 'windows = "2024-04-15"'), "[demand] windows must be a list of dates or files"),
        (("[demand]", "[sweep]\nstep = 0\n[demand]"), "[sweep] step must be at least 1"),
        (("[demand]", "[policy]\nservice_floor = 99\n[demand]"), "service_floor = 99 must be between 0.5 and 1"),
        (("[grid]", "[grid"), "not valid TOML"),
        (('[site]\nname = "A test site"', 'site = 3\n[other]\nname = "x"'), "[site] must be a table"),
    ],
)
def test_a_value_of_the_wrong_kind_is_refused_and_not_a_crash(tmp_path, change, says):
    assert change[0] in MINIMAL
    with pytest.raises(siteplan.SiteError, match=re.escape(says)):
        siteplan.load(site_file(tmp_path, MINIMAL.replace(*change)))


def test_a_site_file_that_is_not_there_is_refused_by_name(tmp_path):
    with pytest.raises(siteplan.SiteError, match="no site file at"):
        siteplan.load(tmp_path / "nowhere.toml")


def test_a_run_whose_rides_served_still_move_is_not_settled(monkeypatch):
    def once(site, size, window, seed, energy, change, passes):
        return {
            "size": size,
            "window": window,
            "served": 0.995,
            "served_a_pass_earlier": 0.990,
            "arrived_at_floor_share": 0.10,
            "arrived_at_floor_share_a_pass_earlier": 0.10,
            "charge_on_the_road": 0.30,
            "charge_on_the_road_a_pass_earlier": 0.30,
            "passes": passes,
        }

    monkeypatch.setattr(siteplan, "_once", once)
    site = siteplan.load(ROOT / "sites" / "east_oakland.toml")
    out = siteplan.run((site, "as entered", 600, "2024-04-15", 1, 1.0, None))
    assert out["settled"] is False and out["passes"] == siteplan.PASSES[-1]
    monkeypatch.setattr(siteplan, "_once", lambda *a: once(*a) | {"served_a_pass_earlier": 0.994})
    assert siteplan.run((site, "as entered", 600, "2024-04-15", 1, 1.0, None))["settled"] is True
    monkeypatch.setattr(
        siteplan, "_once", lambda *a: once(*a) | {"served_a_pass_earlier": 0.994, "charge_on_the_road": 0.31}
    )
    assert siteplan.run((site, "as entered", 600, "2024-04-15", 1, 1.0, None))["settled"] is False


@pytest.mark.parametrize(
    ("make", "says"),
    [
        (lambda folder: (folder / "week.csv").write_text(""), "week.csv: cannot be read as a CSV"),
        (
            lambda folder: (folder / "week.csv").write_text('time,rides\n"2026-01-05,3\n1,2,3,4\n'),
            "week.csv: cannot be read as a CSV",
        ),
        (lambda folder: (folder / "week.csv").mkdir(), "week.csv: cannot be read as a CSV"),
    ],
)
def test_a_demand_file_that_cannot_be_read_is_refused_by_name(tmp_path, make, says):
    make(tmp_path)
    with pytest.raises(siteplan.SiteError, match=re.escape(says)):
        siteplan.load(site_file(tmp_path, MINIMAL.replace("2024-04-15", "week.csv")))


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (("[vehicles.one]", "[vehicles]\ntwo = 3\n[vehicles.one]"), "[vehicles.two] must be a table"),
        (
            ("[demand]", "[policy]\nlow_battery_visits_at_most = nan\n[demand]"),
            "low_battery_visits_at_most must be a number, not nan",
        ),
        (("kw = 1000", "kw = inf"), "[grid] kw must be a number, not inf"),
        (
            ("[demand]", "[policy]\nlow_battery_visits_at_most = 1.5\n[demand]"),
            "low_battery_visits_at_most must be a share between 0 and 1",
        ),
    ],
)
def test_a_stray_vehicle_entry_or_a_value_that_is_not_finite_is_refused_by_name(tmp_path, change, says):
    assert change[0] in MINIMAL
    with pytest.raises(siteplan.SiteError, match=re.escape(says)):
        siteplan.load(site_file(tmp_path, MINIMAL.replace(*change)))


def test_the_default_drive_to_the_depot_is_the_cadence_setting_the_study_ran():
    chosen = json.loads((DERIVED / "e22_cadence.json").read_text())["chosen"]
    from depot_twin.cadence import E22_LEGS

    assert siteplan.DEFAULTS["fleet"]["depot_leg_minutes"] == chosen["leg"]
    assert siteplan.DEFAULTS["fleet"]["depot_leg_miles"] == E22_LEGS[chosen["leg"]]
