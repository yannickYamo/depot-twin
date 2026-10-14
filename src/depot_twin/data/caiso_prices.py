"""Wholesale electricity prices at the PG&E load point, from the system operator's public market archive.

Two prices for the same hours of the same week as the grid data: the day-ahead price, which is settled
the afternoon before and is what a day-ahead plan can know; and the real-time price, settled every five
minutes, which it cannot. Both are what the grid pays, in dollars a megawatt-hour, at the aggregated
PG&E load point. A depot on a tariff pays neither; the financial twin carries them as a scenario for an
operator whose supply contract passes them through.

Times come back in UTC and are turned into Pacific local time to match every other series.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime, timedelta, timezone

from depot_twin.data import fetch

NODE = "DLAP_PGAE-APND"
API = "https://oasis.caiso.com/oasisapi/SingleZip"
PACIFIC_OFFSET_HOURS = -7  # April: daylight time
STEPS_PER_HOUR = 12


def _url(query: str, market: str, start: datetime, end: datetime, version: int) -> str:
    stamp = "%Y%m%dT%H:%M-0000"
    return (
        f"{API}?queryname={query}&market_run_id={market}&startdatetime={start.strftime(stamp)}"
        f"&enddatetime={end.strftime(stamp)}&node={NODE}&resultformat=6&version={version}"
    )


def parse_prices(blob: bytes, value_column: str) -> dict[datetime, float]:
    """Parse one of the archive's zipped reports into local start time -> price, for the LMP rows only."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for name in archive.namelist():
            if not name.endswith(".csv"):
                raise ValueError(f"the archive answered with {name}, not a report")
            for row in csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8")):
                if row.get("LMP_TYPE") != "LMP":
                    continue
                moment = datetime.fromisoformat(row["INTERVALSTARTTIME_GMT"].replace("-00:00", "+00:00"))
                local = moment.astimezone(timezone(timedelta(hours=PACIFIC_OFFSET_HOURS))).replace(tzinfo=None)
                out[local] = float(row[value_column])
    return out


def _fetch_paced(url: str, cache: str, attempts: int = 6) -> bytes:
    """Fetch one report, waiting between requests: the archive refuses clients that ask too fast."""
    import time
    import urllib.error

    from depot_twin.data import data_dir

    if (data_dir() / "raw" / cache).exists():
        return fetch(url, cache).read_bytes()
    for attempt in range(attempts):
        try:
            blob = fetch(url, cache).read_bytes()
            time.sleep(6.0)
            return blob
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(30.0 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_week(monday: date, days: int = 7) -> dict:
    """Return day-ahead prices by hour and real-time prices by five minutes for some days from a local Monday midnight."""
    start_utc = datetime(monday.year, monday.month, monday.day) - timedelta(hours=PACIFIC_OFFSET_HOURS)
    day_ahead: dict[datetime, float] = {}
    real_time: dict[datetime, float] = {}
    for offset in range(days):
        begin = start_utc + timedelta(days=offset)
        blob = fetch(
            _url("PRC_LMP", "DAM", begin, begin + timedelta(days=1), 12),
            f"caiso/{monday + timedelta(days=offset)}_dam.zip",
        ).read_bytes()
        day_ahead.update(parse_prices(blob, "MW"))
        # The real-time report is large; the archive serves it in short spans.
        for hour in range(0, 24, 6):
            piece = begin + timedelta(hours=hour)
            cache = f"caiso/{monday + timedelta(days=offset)}_rtm_{hour:02d}.zip"
            blob = _fetch_paced(_url("PRC_INTVL_LMP", "RTM", piece, piece + timedelta(hours=6), 3), cache)
            real_time.update(parse_prices(blob, "VALUE"))
    first = datetime(monday.year, monday.month, monday.day)
    hours = [first + timedelta(hours=k) for k in range(days * 24)]
    steps = [first + timedelta(minutes=5 * k) for k in range(days * 24 * STEPS_PER_HOUR)]
    return {
        "node": NODE,
        "day_ahead_usd_per_mwh": [round(day_ahead.get(h, float("nan")), 2) for h in hours],
        "real_time_usd_per_mwh": [round(real_time.get(s, float("nan")), 2) for s in steps],
    }
