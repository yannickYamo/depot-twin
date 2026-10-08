"""What every series must satisfy before a model sees it, and the audit that says whether it does.

A bad series corrupts everything downstream, quietly. So the rules are written as code, run on every
series the models train on, and run again in CI on small cases. Three kinds of rule:

- Shape: a regular index with no duplicate moments; gaps marked, never silently filled.
- Provenance: rows are real or generated, and generated rows may only ever be trained on. A model is
  never stopped, calibrated or scored on something a generator made.
- Known artefacts, flagged rather than hidden: the two daylight-saving hours each year, runs of zeros
  that are outages or missing files rather than quiet nights, and jumps in the level of a series.

The audit's findings for each source are in docs/DATA.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

SYNTHETIC_PREFIX = "generated_"
ZERO_RUN_HOURS = 6  # a quiet night has a few zero hours; six in a row is a gap or an outage
LEVEL_SHIFT = 0.25  # a four-week mean that moves by more than this against the four weeks before is flagged


def is_synthetic(name: str) -> bool:
    """Whether a series name marks rows a generator made."""
    return name.startswith(SYNTHETIC_PREFIX)


def assert_real(rows: pd.DataFrame, purpose: str) -> None:
    """Refuse rows from a generator wherever a model is stopped, calibrated or scored."""
    if "series" in rows and rows["series"].map(is_synthetic).any():
        raise ValueError(f"generated rows reached the {purpose} set; they may only be trained on")


def dst_hours(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Return the local hours in the index that a US daylight-saving change makes odd.

    Clocks go forward at 02:00 on the second Sunday of March (the hour does not exist) and back at
    02:00 on the first Sunday of November (the 01:00 hour happens twice and is summed into one).
    """
    found = []
    for year in sorted(set(index.year)):
        march = pd.Timestamp(year=year, month=3, day=1)
        forward = march + pd.Timedelta(days=(6 - march.dayofweek) % 7 + 7, hours=2)
        november = pd.Timestamp(year=year, month=11, day=1)
        back = november + pd.Timedelta(days=(6 - november.dayofweek) % 7, hours=1)
        found += [moment for moment in (forward, back) if index.min() <= moment <= index.max()]
    return found


@dataclass
class Audit:
    """What an audit found about one series."""

    name: str
    start: str
    end: str
    step_minutes: float
    regular: bool
    unique: bool
    rows: int
    zero_runs: list[tuple[str, int]] = field(default_factory=list)  # (start, hours)
    dst_hours: int = 0
    level_shifts: list[tuple[str, float]] = field(default_factory=list)  # (week, ratio to the four weeks before)

    @property
    def sound(self) -> bool:
        """Whether the series can be trained on as it is: regular, unique, and free of long zero runs."""
        return self.regular and self.unique and not self.zero_runs


def _zero_runs(series: pd.Series, step_minutes: float) -> list[tuple[str, int]]:
    """Return runs of zeros at least ZERO_RUN_HOURS long: gaps or outages, not quiet nights."""
    zero = (series.fillna(0.0) == 0.0).to_numpy()
    runs, start = [], None
    for k, flag in enumerate([*zero, False]):
        if flag and start is None:
            start = k
        elif not flag and start is not None:
            hours = (k - start) * step_minutes / 60.0
            if hours >= ZERO_RUN_HOURS:
                runs.append((str(series.index[start]), int(round(hours))))
            start = None
    return runs


def _level_shifts(series: pd.Series) -> list[tuple[str, float]]:
    """Return weeks where the four-week mean moved by more than LEVEL_SHIFT against the four weeks before."""
    weekly = series.resample("W-MON", label="left", closed="left").mean()
    if len(weekly) < 9:
        return []
    before = weekly.rolling(4).mean().shift(1)
    after = weekly.rolling(4).mean().shift(-3)
    ratio = (after / before).dropna()
    flagged = ratio[(ratio > 1 + LEVEL_SHIFT) | (ratio < 1 - LEVEL_SHIFT)]
    # Keep the first week of each run of flagged weeks, so one shift is reported once.
    out, last = [], None
    for week, value in flagged.items():
        if last is None or (week - last) > pd.Timedelta(weeks=1):
            out.append((str(week.date()), round(float(value), 2)))
        last = week
    return out


def audit(name: str, series: pd.Series) -> Audit:
    """Audit one series on a time index: shape, gaps, daylight-saving hours and level shifts."""
    index = pd.DatetimeIndex(series.index)
    gaps = index.to_series().diff().dropna()
    step = float(gaps.mode().iloc[0].total_seconds() / 60.0) if len(gaps) else float("nan")
    return Audit(
        name=name,
        start=str(index.min()),
        end=str(index.max()),
        step_minutes=step,
        regular=bool((gaps == gaps.mode().iloc[0]).all()) if len(gaps) else True,
        unique=bool(index.is_unique),
        rows=int(len(series)),
        zero_runs=_zero_runs(series, step),
        dst_hours=len(dst_hours(index)),
        level_shifts=_level_shifts(series.astype(float)),
    )


def audit_table(series: dict[str, pd.Series]) -> str:
    """Return the audits of several series as a Markdown table, for docs/DATA.md."""
    lines = [
        "| Series | From | To | Step | Regular | Zero runs of 6 h or more | Daylight-saving hours | Level shifts (week, ratio) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, values in series.items():
        a = audit(name, values)
        runs = "; ".join(f"{start[:10]} ({hours} h)" for start, hours in a.zero_runs[:3]) or "none"
        if len(a.zero_runs) > 3:
            runs += f" and {len(a.zero_runs) - 3} more"
        shifts = "; ".join(f"{week} ({ratio})" for week, ratio in a.level_shifts) or "none"
        step = f"{a.step_minutes:.0f} min"
        lines.append(
            f"| {name} | {a.start[:10]} | {a.end[:10]} | {step} | {'yes' if a.regular and a.unique else 'no'} | {runs} | {a.dst_hours} | {shifts} |"
        )
    return "\n".join(lines)
