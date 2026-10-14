"""The figures the documents show, drawn from the result files.

Five pictures carry the findings: what one feeder carries as the fleet grows, how that moves with the
vehicles' energy use, why the order of feeding matters, when the area outgrows a feeder, and which input
moves the money most. Each is an SVG written
here from a record, so a figure cannot show a number the record does not hold. No plotting library: the
shapes are few, and the files stay small and readable in a diff.
"""

from __future__ import annotations

import json
from pathlib import Path

from depot_twin import analysis
from depot_twin.data import data_dir

INK, SLATE, LINE = "#050f1e", "#5d6e83", "#e5e9f0"
BLUE, GREEN, RED, AMBER = "#006fee", "#00a372", "#d92626", "#b76e00"
FONT = "font-family='Outfit, Inter, system-ui, sans-serif'"
WIDTH, HEIGHT = 880, 440
LEFT, RIGHT, TOP, BOTTOM = 72, 28, 56, 64


def _record(name: str) -> dict:
    return json.loads((data_dir() / "derived" / name).read_text())


def _text(
    x: float, y: float, words: str, size: int = 13, fill: str = SLATE, anchor: str = "start", weight: int = 400
) -> str:
    safe = words.replace("&", "&amp;").replace("<", "&lt;")
    return f"<text x='{x:.1f}' y='{y:.1f}' {FONT} font-size='{size}' font-weight='{weight}' fill='{fill}' text-anchor='{anchor}'>{safe}</text>"


def _frame(title: str, note: str, body: list[str], height: int = HEIGHT) -> str:
    """An SVG with a title, a line under it saying what it is drawn from, and the marks."""
    head = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {WIDTH} {height}' role='img' aria-label='{title}'>",
        f"<rect width='{WIDTH}' height='{height}' fill='#ffffff'/>",
        _text(LEFT, 26, title, 17, INK, weight=600),
        _text(LEFT, 44, note, 12),
    ]
    return "\n".join([*head, *body, "</svg>"]) + "\n"


class _Plot:
    """Scales for a plot inside the frame, and the axes that go with them."""

    def __init__(self, x: tuple[float, float], y: tuple[float, float], height: int = HEIGHT):
        self.x0, self.x1, self.y0, self.y1 = x[0], x[1], y[0], y[1]
        self.bottom = height - BOTTOM

    def px(self, value: float) -> float:
        return LEFT + (value - self.x0) / (self.x1 - self.x0) * (WIDTH - LEFT - RIGHT)

    def py(self, value: float) -> float:
        return self.bottom - (value - self.y0) / (self.y1 - self.y0) * (self.bottom - TOP)

    def axes(
        self, x_ticks: list[tuple[float, str]], y_ticks: list[tuple[float, str]], x_label: str, y_label: str
    ) -> list[str]:
        out = []
        for value, label in y_ticks:
            out.append(
                f"<line x1='{LEFT}' x2='{WIDTH - RIGHT}' y1='{self.py(value):.1f}' y2='{self.py(value):.1f}' stroke='{LINE}'/>"
            )
            out.append(_text(LEFT - 8, self.py(value) + 4, label, 12, anchor="end"))
        for value, label in x_ticks:
            out.append(_text(self.px(value), self.bottom + 18, label, 12, anchor="middle"))
        out.append(f"<line x1='{LEFT}' x2='{WIDTH - RIGHT}' y1='{self.bottom}' y2='{self.bottom}' stroke='{INK}'/>")
        out.append(_text((LEFT + WIDTH - RIGHT) / 2, self.bottom + 40, x_label, 12, anchor="middle"))
        if y_label:
            out.append(_text(LEFT, TOP + 12, y_label, 12))
        return out

    def line(self, points: list[tuple[float, float]], colour: str, width: float = 2.5, dash: str = "") -> str:
        path = " ".join(f"{'M' if k == 0 else 'L'}{self.px(x):.1f},{self.py(y):.1f}" for k, (x, y) in enumerate(points))
        return f"<path d='{path}' fill='none' stroke='{colour}' stroke-width='{width}' stroke-dasharray='{dash}'/>"

    def band(self, low: list[tuple[float, float]], high: list[tuple[float, float]], colour: str) -> str:
        edge = [*high, *reversed(low)]
        path = " ".join(f"{'M' if k == 0 else 'L'}{self.px(x):.1f},{self.py(y):.1f}" for k, (x, y) in enumerate(edge))
        return f"<path d='{path} Z' fill='{colour}' fill-opacity='0.16'/>"


def _capacity_marks(plot: _Plot, record: dict, used: dict, fleet: int, planned: int, margin: dict | None) -> list[str]:
    """The capacity chart's annotations: power in use under the axis, the plan, and the fleet served at the limit."""
    best = record["best_rule"]
    body: list[str] = []
    # Under the axis: how much of the usable connection the better rule draws at each hundred, and at the fleet carried.
    for size, row in used.items():
        if int(size) % 100 == 0:
            body.append(_text(plot.px(int(size)), plot.bottom + 62, f"{row['grid_share_used']:.0%}", 12, INK, "middle"))
    body.append(_text(plot.px(900) + 30, plot.bottom + 62, "of the usable power in use", 12))
    if margin:
        # The fleet to plan for: the one that still fits with more energy use than estimated.
        x = plot.px(planned)
        body.append(
            f"<line x1='{x:.1f}' x2='{x:.1f}' y1='{plot.py(0.985):.1f}' y2='{plot.bottom}' stroke='{INK}' stroke-dasharray='2 4'/>"
        )
        more = f"{margin['margin'] - 1:.0%} more energy use"
        for k, (words, colour, weight) in enumerate(
            ((f"the plan: {planned}", INK, 600), ("still fits with", SLATE, 400), (more, SLATE, 400))
        ):
            body.append(_text(x - 8, plot.py(0.9) + 16 * (k - 1), words, 12, colour, "end", weight))
    # The largest fleet that still serves its rides, with the feeder at its limit: served, not carried.
    limit = record["largest_serving_the_floor"][best]
    if limit != fleet:
        x, y = plot.px(limit), plot.py(used[str(limit)]["median"])
        body.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5.5' fill='#ffffff' stroke='{BLUE}' stroke-width='2'/>")
        body.append(_text(x + 4, y - 12, f"{limit}: served, with no power to spare", 12, BLUE, "start"))
    return body


def capacity() -> str:
    """Rides served against fleet size on one feeder under two calling rules, with the spread over runs."""
    record = _record("e23_capacity.json")
    floor, low = record["floor"], 0.85
    plot = _Plot((480, 1040), (low, 1.006), HEIGHT)
    body = plot.axes(
        [(v, f"{v:,}") for v in range(500, 901, 100)],
        [(v, f"{v:.0%}") for v in (0.85, 0.90, 0.95, 1.0)],
        "Vehicles in the fleet, at 25 rides offered a vehicle a day",
        "",
    )
    body.append(plot.line([(480, floor), (1040, floor)], INK, 1, "4 4"))
    body.append(_text(LEFT + 6, plot.py(floor) + 16, f"service floor: {floor:.0%} of rides served", 12, INK))
    best = record["best_rule"]
    # The fleets between the hundred-vehicle steps, run on the same fortnights and draws (E25, E26).
    derived = data_dir() / "derived"
    fleet, between = analysis.carried_fleet(derived)
    planned, margin = analysis.planned_fleet(derived)
    finer = {
        best: between["by_size"] if between else {},
        "threshold": margin["plain_rule"]["by_size"] if margin else {},
    }
    carries = {
        best: fleet,
        "threshold": margin["plain_rule"]["capacity"] if margin else record["rules"]["threshold"]["capacity"],
    }
    names = {"threshold": ("called in at a set charge", AMBER), best: ("called in once a charger is free", BLUE)}
    for rule, (label, colour) in names.items():
        rows = record["rules"][rule]["by_size"] | {
            s: r for s, r in finer[rule].items() if s not in record["rules"][rule]["by_size"]
        }
        at = sorted((int(size), row) for size, row in rows.items())
        body.append(plot.band([(s, max(r["p10"], low)) for s, r in at], [(s, r["p90"]) for s, r in at], colour))
        body.append(plot.line([(s, r["median"]) for s, r in at], colour))
        carried = carries[rule]
        body.append(
            f"<circle cx='{plot.px(carried):.1f}' cy='{plot.py(dict(at)[carried]['median']):.1f}' r='5.5' fill='{colour}' stroke='#ffffff' stroke-width='2'/>"
        )
        last_size, last = at[-1]
        body.append(_text(plot.px(last_size) + 8, plot.py(last["median"]) + 4, label, 12, colour))
        body.append(
            _text(plot.px(last_size) + 8, plot.py(last["median"]) + 20, f"carries {carried}", 12, colour, weight=600)
        )
    used = record["rules"][best]["by_size"] | (between["by_size"] if between else {})
    body += _capacity_marks(plot, record, used, fleet, planned, margin)
    count = next(iter(used.values()))["runs"]
    tests = "E23" + (", E25 and E26" if margin else " and E25" if between else "")
    note = f"Median of {count} runs (four fortnights by ten draws); band, 10th to 90th percentile; dot, the largest fleet carried. {tests}."
    return _frame("What one feeder carries, by calling rule", note, body, HEIGHT + 26)


def energy_margin() -> str:  # noqa: PLR0915
    """Depot visits arriving on a low battery against fleet size, at three levels of the vehicles' energy use."""
    record = _record("e26_margin.json")
    planned, _ = analysis.planned_fleet(data_dir() / "derived")
    sizes = sorted({size for group in record["sizes"].values() for size in group})
    plot = _Plot((sizes[0] - 20, sizes[-1] + 190), (0.0, 1.0))
    body = plot.axes(
        [(v, f"{v:,}") for v in sizes if v % 50 == 0],
        [(v, f"{v:.0%}") for v in (0.0, 0.25, 0.5, 0.75, 1.0)],
        "Vehicles in the fleet, at 25 rides offered a vehicle a day",
        "",
    )
    line = record["by_energy"]["1"]["by_size"]
    half = 0.5
    body.append(plot.line([(sizes[0] - 20, half), (sizes[-1] + 190, half)], INK, 1, "4 4"))
    body.append(
        _text(
            WIDTH - RIGHT - 6,
            plot.py(half) - 6,
            "carried: at most half of visits arrive on a low battery",
            12,
            INK,
            "end",
        )
    )
    names = {"0.9": ("10% less energy than estimated", GREEN), "1": ("as estimated", BLUE), "1.1": ("10% more", RED)}
    for k, (energy, (label, colour)) in enumerate(names.items()):
        line = record["by_energy"][energy]
        at = sorted((int(size), row["arrived_at_floor_share"]) for size, row in line["by_size"].items())
        body.append(plot.line(at, colour))
        for size, share in at:
            body.append(f"<circle cx='{plot.px(size):.1f}' cy='{plot.py(share):.1f}' r='3' fill='{colour}'/>")
        carried = line["capacity"]
        body.append(
            f"<circle cx='{plot.px(carried):.1f}' cy='{plot.py(dict(at)[carried]):.1f}' r='6' fill='{colour}' stroke='#ffffff' stroke-width='2'/>"
        )
        y = plot.py(0.42) + 20 * k
        body.append(f"<rect x='{plot.px(sizes[-1]) + 22:.1f}' y='{y - 5:.1f}' width='14' height='3' fill='{colour}'/>")
        body.append(_text(plot.px(sizes[-1]) + 42, y, f"{label}: carries {carried}", 12, INK))
    # The same test with the always-on load counted while a vehicle is parked in the depot (E27): dashed.
    parked = _record("e27_parked.json")["by_energy"]
    for k, (energy, label, colour) in enumerate((("1", "as estimated", BLUE), ("1.1", "10% more", RED))):
        group = parked[energy]
        at = sorted((int(size), row["arrived_at_floor_share"]) for size, row in group["by_size"].items())
        body.append(plot.line(at, colour, 2, "6 4"))
        carried = group["carried"]
        body.append(
            f"<circle cx='{plot.px(carried):.1f}' cy='{plot.py(dict(at)[carried]):.1f}' r='6' fill='#ffffff' stroke='{colour}' stroke-width='2'/>"
        )
        y = plot.py(0.42) + 20 * (3 + k)
        body.append(
            f"<line x1='{plot.px(sizes[-1]) + 22:.1f}' x2='{plot.px(sizes[-1]) + 36:.1f}' y1='{y - 4:.1f}' y2='{y - 4:.1f}' stroke='{colour}' stroke-width='2' stroke-dasharray='4 3'/>"
        )
        body.append(_text(plot.px(sizes[-1]) + 42, y, f"{label}, systems on while parked: {carried}", 12, INK))
    x = plot.px(planned)
    body.append(
        f"<line x1='{x:.1f}' x2='{x:.1f}' y1='{TOP + 8}' y2='{plot.bottom}' stroke='{INK}' stroke-dasharray='2 4'/>"
    )
    body.append(_text(x + 6, TOP + 20, f"the plan: {planned}", 12, INK, weight=600))
    note = "Share of depot visits starting on a low battery, median of four fortnights by ten draws; large dot, the largest fleet carried. E26, E27."
    return _frame("Energy use sets the fleet one feeder carries", note, body)


def power_rule() -> str:
    """Why the order of feeding matters: power drawn, vehicles standing between stations, and rides served, both ways."""
    record = _record("e23_capacity.json")
    used, standing, served = (
        record["power_rule_grid_share_used"],
        record["power_rule_between_stations"],
        record["power_rule_served"],
    )
    first, order = "need_first", "slot_power"
    panels = (
        ("Usable grid power drawn", used[first]["median"], used[order]["median"], 1.1, "{:.0%}"),
        (
            "Vehicles between stations",
            standing[first]["median"],
            standing[order]["median"],
            standing[first]["median"] * 1.25,
            "{:.0f}",
        ),
        ("Rides served", served[first]["median"], served[order]["median"], 1.1, "{:.1%}"),
    )
    body, width = [], (WIDTH - LEFT - RIGHT) / 3
    for k, (label, a, b, top, shape) in enumerate(panels):
        x = LEFT + k * width
        body.append(_text(x, TOP + 14, label, 13, INK, weight=600))
        for j, (value, colour, name) in enumerate(((a, AMBER, "Emptiest first"), (b, BLUE, "In plug order"))):
            y = TOP + 46 + j * 84
            body.append(_text(x, y - 6, name, 12))
            body.append(
                f"<rect x='{x:.1f}' y='{y}' width='{(width - 40) * value / top:.1f}' height='34' rx='4' fill='{colour}'/>"
            )
            body.append(_text(x + (width - 40) * value / top + 6, y + 23, shape.format(value), 13, INK, weight=600))
    runs = served[order]["runs"]
    note = f"1,000 vehicles on one feeder, where power is short. Median of {runs} runs (four fortnights by ten draws). E23."
    return _frame("The same power, fed two ways", note, body, 250)


def feeder_timeline() -> str:
    """Vehicles the East Bay needs over the coming months under each reading of growth, against what feeders carry."""
    demand = _record("e21_demand.json")
    study = _record("account_study.json")["feeder_timing"]
    capacity_one, _ = analysis.planned_fleet(data_dir() / "derived")
    area = analysis.demand_at(demand, capacity_one)["east_bay_20km"]
    today = area["vehicles_at_25_rides"]
    months, top = 60, capacity_one * 2
    plot = _Plot((0, months), (0, top * 1.12))
    lead = study["lead_months_assumed"]
    body = [
        f"<rect x='{plot.px(min(lead)):.1f}' y='{TOP}' width='{plot.px(max(lead)) - plot.px(min(lead)):.1f}' height='{plot.bottom - TOP}' fill='{LINE}' fill-opacity='0.55'/>",
        _text(
            (plot.px(min(lead)) + plot.px(max(lead))) / 2,
            plot.bottom - 10,
            "a feeder applied for at signing arrives here (assumed)",
            12,
            anchor="middle",
        ),
    ]
    body += plot.axes(
        [(m, "lease signed" if m == 0 else f"{m // 12} y") for m in range(0, months + 1, 12)],
        [(v, f"{v:,.0f}") for v in (0, capacity_one, top)],
        "Time from lease signing",
        "",
    )
    for level, label in ((capacity_one, "one feeder is planned for"), (top, "twice that, as a guide to two feeders:")):
        body.append(plot.line([(0, level), (months, level)], INK, 1, "4 4"))
        body.append(_text(LEFT + 6, plot.py(level) - 6, f"{label} {level:,.0f} vehicles", 12, INK))
    names = {
        "first_to_last": ("first quarter to last", RED),
        "fitted": ("line through all quarters", AMBER),
        "last_six_months": ("last six months", BLUE),
    }
    reached = area["months_until_second_feeder_by_estimate"]
    for k, (key, rate) in enumerate(demand["growth_per_month_by_estimate"].items()):
        label, colour = names[key]
        points = [(m, today * (1 + rate) ** m) for m in range(months + 1)]
        body.append(plot.line([(m, v) for m, v in points if v <= top], colour))
        row = plot.py(0.46 * capacity_one - 0.12 * capacity_one * k)
        sooner = area["by_level"]["latest_quarter"]["months_until_second_feeder_by_estimate"][key]
        body.append(f"<rect x='{plot.px(25):.1f}' y='{row - 5:.1f}' width='14' height='3' fill='{colour}'/>")
        body.append(
            _text(
                plot.px(25) + 20,
                row,
                f"{label}: {rate:.1%} a month, full in {sooner} to {reached[key]} months",
                12,
                INK,
            )
        )
        if reached[key] is not None and reached[key] <= months:
            body.append(
                f"<circle cx='{plot.px(reached[key]):.1f}' cy='{plot.py(capacity_one):.1f}' r='5.5' fill='{colour}' stroke='#ffffff' stroke-width='2'/>"
            )
    fewest, most = area["vehicles_range"]
    note = f"East Bay within 20 km: {fewest:,.0f} to {most:,.0f} vehicles today; curves start from the lower. A scenario from public filings, not a forecast. E21."
    return _frame("When the area outgrows one feeder", note, body)


def tornado() -> str:
    """Each unsourced or uncertain input moved alone across its range: the swing in contribution a day."""
    study = _record("account_study.json")
    rows = study["tornado"]
    base_fleet = study["base_design"]["fleet"]
    base = study["split"][str(base_fleet)]["contribution"]
    low = min(min(r["contribution_at_low"], r["contribution_at_high"]) for r in rows)
    high = max(max(r["contribution_at_low"], r["contribution_at_high"]) for r in rows)
    height = TOP + 34 * len(rows) + BOTTOM
    left = 300
    scale = lambda value: left + (value - low) / (high - low) * (WIDTH - left - RIGHT - 90)  # noqa: E731
    body = [
        f"<line x1='{scale(base):.1f}' x2='{scale(base):.1f}' y1='{TOP}' y2='{height - BOTTOM + 6}' stroke='{INK}'/>"
    ]
    body.append(_text(scale(base), height - BOTTOM + 22, f"as recorded: ${base:,.0f} a day", 12, INK, "middle"))
    for k, row in enumerate(rows):
        y = TOP + 8 + 34 * k
        a, b = sorted((row["contribution_at_low"], row["contribution_at_high"]))
        body.append(_text(left - 10, y + 16, row["label"], 12, INK, "end"))
        body.append(
            f"<rect x='{scale(a):.1f}' y='{y}' width='{max(scale(b) - scale(a), 1):.1f}' height='22' rx='3' fill='{BLUE}' fill-opacity='0.8'/>"
        )
        body.append(_text(scale(b) + 6, y + 16, f"${row['swing']:,.0f}", 12))
    note = f"{base_fleet} vehicles on one feeder. Each input moved alone over its range (docs/METHOD.md); the figure is the swing in contribution a day."
    return _frame("Which input moves the money", note, body, height)


FIGURES = {
    "capacity": capacity,
    "energy_margin": energy_margin,
    "power_rule": power_rule,
    "feeder_timeline": feeder_timeline,
    "tornado": tornado,
}


def write(folder: str | Path = "docs/images") -> list[Path]:
    """Write every figure and return the paths."""
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    out = []
    for name, draw in FIGURES.items():
        path = target / f"{name}.svg"
        path.write_text(draw())
        out.append(path)
    # The figures are pictures and cannot carry a stamp themselves; this file carries it for the folder.
    from depot_twin import provenance

    stamp = target / "stamp.json"
    stamp.write_text(
        json.dumps({"figures": sorted(FIGURES), "code": provenance.page_stamp("docs/images/stamp.json")}, indent=1)
        + "\n"
    )
    return [*out, stamp]
