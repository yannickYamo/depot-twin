"""The split registry: which days of which series serve which purpose, written once and read everywhere.

Every experiment that scores a forecast or runs the depot on replayed days takes its window from here,
so that a window used for development cannot later be presented as a test, and a test window is scored
once. The file is data/splits.json; this module reads it and answers questions about it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[3] / "data" / "splits.json"


@dataclass(frozen=True)
class Window:
    """A span of one series set aside for one purpose."""

    ident: str
    series: str
    start: date
    end: date
    purpose: str  # "development", "test" or "reserved"
    used_by: tuple[str, ...]
    accepted_overlap: str | None = None  # another window this one may overlap, with the reason in the file

    def covers(self, day: date) -> bool:
        """Whether a day falls inside the window."""
        return self.start <= day <= self.end


def windows(path: Path = REGISTRY) -> list[Window]:
    """Read every window in the registry."""
    out = []
    for entry in json.loads(path.read_text())["windows"]:
        out.append(
            Window(
                entry["id"],
                entry["series"],
                date.fromisoformat(entry["from"]),
                date.fromisoformat(entry["to"]),
                entry["purpose"],
                tuple(entry["used_by"]),
                (entry.get("accepted_overlap") or {}).get("with"),
            )
        )
    return out


def window(ident: str) -> Window:
    """Return one window by its name."""
    return next(w for w in windows() if w.ident == ident)


def purpose_of(series: str, day: date) -> str | None:
    """Return what a day of a series is set aside for, or None when it is not listed."""
    family = series.split("_")[0]
    for w in windows():
        if (w.series == series or w.series.split("_")[0] == family) and w.covers(day):
            return w.purpose
    return None


def conflicts(path: Path = REGISTRY) -> list[str]:
    """Return every pair of windows of one series that overlap with different purposes."""
    found = []
    listed = windows(path)
    for a in listed:
        for b in listed:
            same_series = a.series == b.series or a.series.split("_")[0] == b.series.split("_")[0]
            accepted = b.ident in (a.accepted_overlap,) or a.ident in (b.accepted_overlap,)
            if (
                a.ident < b.ident
                and same_series
                and a.purpose != b.purpose
                and a.start <= b.end
                and b.start <= a.end
                and not accepted
            ):
                found.append(f"{a.ident} ({a.purpose}) overlaps {b.ident} ({b.purpose})")
    return found
