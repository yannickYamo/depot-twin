"""What a depot is made of, and the vehicles that visit it.

Times are minutes from midnight of day zero. Power is kW, energy is kWh, and state of charge is a fraction
between 0 and 1.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DAY_MIN = 1440.0


@dataclass(frozen=True)
class VehicleModel:
    """A vehicle type: its battery and how fast it accepts charge."""

    name: str
    capacity_kwh: float
    max_dc_kw: float
    max_ac_kw: float
    taper_start_soc: float = 0.8
    taper_floor: float = 0.2
    # Measured fast-charge curve as (state of charge, kW) points. When present it replaces the linear taper.
    dc_curve: tuple[tuple[float, float], ...] = ()
    # Energy use of this vehicle type. When absent, the fleet-wide figures in the fleet configuration apply.
    drive_kwh_per_mile: float | None = None
    always_on_kw: float | None = None  # computers, sensors and climate control, whether moving or not

    def accept_kw(self, soc: float, kind: str) -> float:
        """Return the most power the battery takes at this state of charge on an "ac" or "dc" charger."""
        if kind == "ac":
            return self.max_ac_kw
        if self.dc_curve:
            points = np.array(self.dc_curve)
            return float(np.interp(soc, points[:, 0], points[:, 1]))
        if soc <= self.taper_start_soc:
            return self.max_dc_kw
        span = 1.0 - self.taper_start_soc
        fraction = max(0.0, (1.0 - soc) / span)
        return self.max_dc_kw * (self.taper_floor + (1.0 - self.taper_floor) * fraction)


@dataclass(frozen=True)
class ChargerBank:
    """A group of identical chargers."""

    kind: str  # "ac" or "dc"
    count: int
    kw: float


@dataclass(frozen=True)
class Buffer:
    """A stationary battery that charges when the site has spare power and discharges when it does not."""

    energy_kwh: float
    power_kw: float
    min_soc: float = 0.1
    efficiency: float = 0.9  # applied once, on the way in


@dataclass(frozen=True)
class DepotConfig:
    """One site: its grid connection, chargers, cleaning bays and people."""

    name: str
    site_limit_kw: float
    chargers: tuple[ChargerBank, ...]
    buffer: Buffer | None = None
    staff: int = 4
    plug_minutes: float = 2.0
    cleaning_bays: int = 2
    clean_minutes: float = 12.0
    inspect_minutes: float = 20.0
    inspect_every: int = 0  # every Nth visit gets an inspection; 0 turns inspections off
    clean_every: int = 1  # a vehicle is cleaned on every Nth of its visits; 1 is every visit
    charger_efficiency: float = 0.93
    # The share of the connection the site's load manager lets the chargers draw. The connection figure is
    # what the utility can deliver at the parcel (docs/SITE.md); the manager keeps a margin under it for
    # measurement and response. 95% is an assumption in line with practice; read the figure as an equipment
    # rating instead and the code's continuous-load rule would make it 80%.
    usable_share: float = 0.95

    @property
    def usable_kw(self) -> float:
        """The most the site draws from the grid at any moment."""
        return self.site_limit_kw * self.usable_share

    def bank(self, kind: str) -> ChargerBank | None:
        """Return the charger bank of this kind, if the site has one."""
        return next((b for b in self.chargers if b.kind == kind), None)


@dataclass
class Visit:
    """One vehicle coming in: when, how empty, and what it needs before it leaves."""

    vehicle_id: str  # the physical vehicle; the same string every time it comes back
    model: VehicleModel
    arrive_min: float
    soc_in: float
    target_soc: float
    due_min: float | None = None  # when the vehicle is wanted back in service
    max_minutes: float | None = None  # a time-boxed session: unplug after this long, charged or not
    visit_id: str | None = None  # this one visit, unique; None means the vehicle id serves, as in hand scenarios

    @property
    def key(self) -> str:
        """What tells this visit apart from every other, including the same vehicle's earlier ones."""
        return self.visit_id or self.vehicle_id

    @property
    def energy_needed_kwh(self) -> float:
        """Energy that must go into the battery to reach the target."""
        return max(0.0, self.target_soc - self.soc_in) * self.model.capacity_kwh


@dataclass
class Scenario:
    """A depot, the visits it must serve, and the control rule in force."""

    depot: DepotConfig
    visits: list[Visit]
    policy: str = "need_first"
    models: dict[str, VehicleModel] = field(default_factory=dict)


def parse_clock(text: str) -> float:
    """Turn "23:30" into minutes from midnight."""
    hours, minutes = text.split(":")
    return int(hours) * 60.0 + int(minutes)


def model_from(name: str, spec: dict) -> VehicleModel:
    """Build a vehicle model from its scenario table."""
    spec = dict(spec)
    curve = tuple((float(soc), float(kw)) for soc, kw in spec.pop("dc_curve", []))
    return VehicleModel(name=name, dc_curve=curve, **spec)


def depot_from(table: dict) -> DepotConfig:
    """Build a depot from its scenario table."""
    table = dict(table)
    banks = tuple(ChargerBank(**b) for b in table.pop("chargers", []))
    buffer = Buffer(**table.pop("buffer")) if "buffer" in table else None
    return DepotConfig(chargers=banks, buffer=buffer, **table)


def _visits_from(waves: list[dict], models: dict[str, VehicleModel], rng: np.random.Generator) -> list[Visit]:
    visits: list[Visit] = []
    for index, wave in enumerate(waves):
        arrive = parse_clock(wave["arrive"])
        due = parse_clock(wave["due"]) if "due" in wave else None
        if due is not None and due <= arrive:
            due += DAY_MIN
        low, high = wave.get("soc_in", [0.2, 0.2])
        spread = float(wave.get("spread_minutes", 0.0))
        for n in range(int(wave["count"])):
            visits.append(
                Visit(
                    vehicle_id=f"w{index}-{n}",
                    model=models[wave["model"]],
                    arrive_min=arrive + rng.uniform(0.0, spread),
                    soc_in=float(rng.uniform(low, high)),
                    target_soc=float(wave.get("target_soc", 0.8)),
                    due_min=due,
                )
            )
    return sorted(visits, key=lambda v: v.arrive_min)


def load_scenario(path: str | Path, seed: int = 0) -> Scenario:
    """Read a scenario file. The seed fixes arrival jitter and incoming state of charge."""
    data = tomllib.loads(Path(path).read_text())
    models = {name: model_from(name, spec) for name, spec in data["models"].items()}
    rng = np.random.default_rng(seed)
    return Scenario(
        depot=depot_from(data["depot"]),
        visits=_visits_from(data.get("waves", []), models, rng),
        policy=data.get("control", {}).get("policy", "need_first"),
        models=models,
    )
