import pytest

from depot_twin.data import cpuc, pge
from depot_twin.resources import VehicleModel

MONTH_CSV = """TCPID,Year,Month,TotalTrips,TotalWaiting,TotalVMTPeriod1,TotalVMTPeriod2,TotalVMTPeriod3,TotalVMTZEV
X,2026,4,"1,000","250","2,000.50","1,000.25","5,000.25","8,001.00"
X,2026,5,"3,000","750","2,000.00","1,000.00","9,000.00","12,000.00"
"""


def test_month_csv_parses_quoted_thousands():
    rows = cpuc.parse_month_csv(MONTH_CSV)
    assert rows[0].trips == 1000
    assert rows[0].miles == pytest.approx(8001.0)


def test_targets_are_weighted_by_volume_not_averaged_by_month():
    figures = cpuc.targets(cpuc.parse_month_csv(MONTH_CSV))
    assert figures["miles_per_trip"] == pytest.approx(20001.0 / 4000)
    assert figures["waiting_minutes_per_trip"] == pytest.approx(15.0)
    shares = figures["idle_share"] + figures["to_pickup_share"] + figures["with_passenger_share"]
    assert shares == pytest.approx(1.0)


def test_month_file_pattern_matches_both_namings_and_skips_other_tables():
    assert cpuc.MONTH_FILE.search("Driverless/P_2026_02_AV_Month-Level_Part0-Deployment.csv")
    assert cpuc.MONTH_FILE.search("Driverless Deployment/P_2026_08_AV_Month_Part0-Deployment.csv")
    assert not cpuc.MONTH_FILE.search("Driverless/P_AV_Monthly_Tract_Part0-Deployment-Public.csv")
    assert not cpuc.MONTH_FILE.search("Drivered/P_2026_05_AV_Month_Part0.csv")


def test_feeders_are_grouped_and_ranked_by_headroom():
    sections = [
        {"FeederId": "1", "FeederName": "A 1101", "LoadCapacity_kW": 900, "voltage_kv": 12},
        {"FeederId": "1", "FeederName": "A 1101", "LoadCapacity_kW": 2700, "voltage_kv": 12},
        {"FeederId": "2", "FeederName": "B 1104", "LoadCapacity_kW": 4600, "voltage_kv": 12},
        {"FeederId": "3", "FeederName": "C 1105", "LoadCapacity_kW": None, "voltage_kv": 12},
    ]
    feeders = pge.summarize_feeders(sections)
    assert [f.name for f in feeders] == ["B 1104", "A 1101"]
    assert (feeders[1].min_kw, feeders[1].max_kw, feeders[1].sections) == (900, 2700, 2)


def test_measured_charge_curve_replaces_the_linear_taper():
    car = VehicleModel("c", 90, max_dc_kw=100, max_ac_kw=11, dc_curve=((0.0, 100), (0.4, 100), (0.8, 50), (1.0, 10)))
    assert car.accept_kw(0.2, "dc") == pytest.approx(100)
    assert car.accept_kw(0.6, "dc") == pytest.approx(75)
    assert car.accept_kw(0.6, "ac") == pytest.approx(11)


def test_grid_tables_parse_to_five_minute_series():
    from depot_twin.data import caiso

    demand = "Time,Hour ahead forecast,Current demand,Net demand,Net demand forecast,Demand response\n"
    demand += "00:00,20930,20000,18000,18607,\n00:05,20930,,17500,17813,\n00:10,20930,21000,,17813,\n"
    assert caiso.parse_demand(demand) == [(20000.0, 18000.0), (20000.0, 17500.0), (21000.0, 17500.0)]
    carbon = "Time,Biogas CO2,Natural Gas CO2,Imports CO2\n00:00,80,2000,3000\n00:05,80,2100,-500\n"
    assert caiso.parse_carbon(carbon) == [5080.0, 1680.0]
