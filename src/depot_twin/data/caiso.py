"""How hard the California grid is working, five minutes at a time, from the system operator's public record.

A depot's power limit is a local fact. Whether the wider grid is strained at the hour the depot charges is
a second one, and the front end shows both. Two series are taken for each five minutes: net demand, which
is demand less wind and solar and is what dispatchable plants must cover, and the carbon given off per
kilowatt-hour delivered. Net demand is the usual measure of strain: it is lowest at midday when solar is
plentiful and highest in the evening.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta

from depot_twin.data import fetch

HISTORY_URL = "https://www.caiso.com/outlook/history/{day:%Y%m%d}/{table}.csv"
STEPS_PER_DAY = 288


def parse_demand(text: str) -> list[tuple[float, float]]:
    """Parse a day's demand table into (demand, net demand) in MW for each five minutes.

    The table carries a few rows past midnight and blanks where a reading is missing; a blank takes the
    value before it.
    """
    rows, last = [], (0.0, 0.0)
    for row in list(csv.DictReader(text.splitlines()))[:STEPS_PER_DAY]:
        demand, net = row.get("Current demand") or "", row.get("Net demand") or ""
        last = (float(demand) if demand else last[0], float(net) if net else last[1])
        rows.append(last)
    return rows


def parse_carbon(text: str) -> list[float]:
    """Parse a day's emissions table into tonnes of CO2 an hour, summed over sources, for each five minutes."""
    totals = []
    for row in list(csv.DictReader(text.splitlines()))[:STEPS_PER_DAY]:
        values = [float(value) for name, value in row.items() if name != "Time" and value]
        totals.append(sum(values) if values else (totals[-1] if totals else 0.0))
    return totals


def fetch_week(monday: date, days: int = 7) -> dict:
    """Return net demand (MW) and carbon intensity (grams of CO2 per kWh) for some days from a Monday."""
    net_demand, intensity = [], []
    for offset in range(days):
        day = monday + timedelta(days=offset)
        demand = parse_demand(
            fetch(HISTORY_URL.format(day=day, table="netdemand"), f"caiso/{day}_netdemand.csv").read_text()
        )
        carbon = parse_carbon(fetch(HISTORY_URL.format(day=day, table="co2"), f"caiso/{day}_co2.csv").read_text())
        for (load, net), tonnes in zip(demand, carbon, strict=True):
            net_demand.append(round(net))
            # Tonnes an hour over megawatts is kilograms per MWh, which is grams per kWh.
            # Exports are booked as negative emissions and can push a midday total under zero; the floor is zero.
            intensity.append(max(0, round(1000.0 * tonnes / load)) if load else 0)
    return {"net_demand_mw": net_demand, "co2_g_per_kwh": intensity}
