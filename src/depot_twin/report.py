"""Build the one-page HTML report from the derived results.

The page is self-contained: the numbers are embedded as JSON and drawn as SVG in the browser, with no
external scripts. Every chart has a table view, so no value is reachable by hover alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from depot_twin.data import data_dir
from depot_twin.fleet import FleetSim, load_fleet_scenario, load_weekly_shape

OPTION_NAMES = {
    "one_feeder": "One feeder, 2.75 MW",
    "one_feeder_with_buffer": "One feeder plus 4 MWh battery",
    "two_feeders": "Two feeders, 5.5 MW",
}
SCENARIO = "scenarios/v2/east_oakland_500.toml"


def depot_days(days: int = 3, seed: int = 11) -> dict:
    """Run a few days of the current controller and return hourly power, occupancy and the ledger."""
    from depot_twin.heartbeat import Heartbeat

    fleet, depot = load_fleet_scenario(SCENARIO)
    shape = load_weekly_shape(data_dir() / "derived" / "weekly_shape_sf.json")
    rule = Heartbeat(ledger_adapt=0.2, ledger_level=0.975, ledger_from_state=True)
    series = FleetSim(fleet, depot, shape, rule, depot_policy="slot_power", seed=seed).run(days).depot.series
    # Skip the first day: the fleet starts with random charge levels and needs a day to settle.
    hours = (series[:, 0] // 60).astype(int)
    keep = sorted(set(hours[hours >= 24].tolist()))
    mean = {h: series[hours == h].mean(axis=0) for h in keep}
    ledger = {entry["hour"]: entry for entry in rule.ledger}
    return {
        "fleet": fleet.size,
        "limit_kw": depot.site_limit_kw,
        "chargers": sum(bank.count for bank in depot.chargers),
        "hours": [h - 24 for h in keep],
        "grid_kw": [round(float(mean[h][1])) for h in keep],
        "charging": [round(float(mean[h][3]), 1) for h in keep],
        "promised": [round(float(ledger[h]["committed"])) if h in ledger else None for h in keep],
        "delivered": [round(float(ledger[h]["actual"])) if h in ledger else None for h in keep],
    }


def _load(name: str) -> dict | None:
    path = data_dir() / "derived" / name
    return json.loads(path.read_text()) if path.exists() else None


def _growth(study: dict) -> dict:
    """Return the growth study as series of rides served by fleet size, for the current controller."""
    sizes = sorted({row["size"] for row in study["rows"]})

    def served(option: str, rule: str) -> list[float]:
        return [
            next(
                r["rides_served_share"]
                for r in study["rows"]
                if (r["option"], r["rule"], r["size"]) == (option, rule, size)
            )
            for size in sizes
        ]

    series = [{"name": name, "served": served(option, "heartbeat")} for option, name in OPTION_NAMES.items()]
    limits = {option: study["limits"][f"{option}_heartbeat"]["serves_99pct_up_to"] for option in OPTION_NAMES}
    return {"sizes": sizes, "series": series, "limits": limits}


def build(out: str | Path = "out/report.html") -> Path:
    """Write the report and return its path."""
    study = _load("growth_v2.json")
    if study is None:
        raise FileNotFoundError("run `depot-twin eval growth-v2` first")
    payload = {
        "growth": _growth(study),
        "days": depot_days(),
        "apart": _load("e11_apart.json"),
        "cost": _load("e12_cost.json"),
        "ledger": _load("e9_ledger.json"),
        "sessions": _load("session_length.json"),
        "planner": _load("e4_planner.json"),
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, default=lambda v: float(np.asarray(v))))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Depot twin: East Oakland</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 28px; line-height: 1.2; margin: 0 0 8px; }
h2 { font-size: 18px; margin: 0 0 4px; }
p { margin: 0 0 12px; color: var(--ink2); max-width: 70ch; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-top: 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 20px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.tile .label { color: var(--ink2); font-size: 13px; }
.tile .value { font-size: 30px; font-weight: 600; line-height: 1.2; }
.tile .note { color: var(--muted); font-size: 12px; }
.legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; color: var(--ink2); margin: 8px 0; }
.legend i { display: inline-block; width: 16px; height: 0; border-top: 2px solid; vertical-align: middle; margin-right: 6px; }
.chart { position: relative; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { font: 12px system-ui, sans-serif; fill: var(--muted); font-variant-numeric: tabular-nums; }
svg text.end { fill: var(--ink2); }
.tip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); display: none; white-space: nowrap; z-index: 2; }
.tip b { color: var(--ink); font-size: 13px; }
.tip i { display: inline-block; width: 12px; border-top: 2px solid; vertical-align: middle; margin-right: 6px; }
.tip .head { color: var(--muted); margin-bottom: 4px; }
details { margin-top: 12px; font-size: 13px; }
summary { cursor: pointer; color: var(--ink2); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; margin-top: 8px; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 4px 12px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--ink2); font-weight: 600; }
footer { margin-top: 32px; color: var(--muted); font-size: 12px; }
</style>
</head>
<body>
<main>
<h1>What one depot carries, and what to change first</h1>
<p>A simulated depot at 7825 San Leandro Street, East Oakland, on the grid connection the public capacity map shows there today. Demand is replayed from real days. The fleet grows from 200 to 2,000 vehicles; chargers, bays and staff grow with it; the grid connection does not.</p>
<div class="tiles" id="tiles"></div>

<div class="card">
<h2>Sharing power in order of plugging in is worth more than anything that can be bought quickly</h2>
<p>Share of offered rides served, by how vehicles are called in and how power is shared among those plugged in. Mean of three seeds on the same days.</p>
<div class="scroll" id="apart-table"></div>
</div>

<div class="card">
<h2>One feeder carries about 700 vehicles; two carry about 1,500</h2>
<p>Share of offered rides served over a week, by fleet size, with in-order feeding.</p>
<div class="legend" id="growth-legend"></div>
<div class="chart" id="growth"></div>
<details><summary>Table</summary><div class="scroll" id="growth-table"></div></details>
</div>

<div class="card">
<h2>The depot states how many vehicles it will have on the road, and delivers</h2>
<p id="days-sub"></p>
<div class="legend" id="ledger-legend"></div>
<div class="chart" id="ledger"></div>
<h2 style="margin-top:20px">Grid draw stays under the site limit</h2>
<p>Hourly average over the same two days.</p>
<div class="chart" id="grid"></div>
<details><summary>Table</summary><div class="scroll" id="days-table"></div></details>
</div>

<div class="card" id="cost-card">
<h2>Told the price of energy, the plan buys it 13% cheaper without losing rides</h2>
<p>500 vehicles, mean of five seeds on days not used before. Energy costs $0.36 per kWh from 4 pm to 9 pm and $0.13 to $0.15 otherwise. Fares less energy is per vehicle per day.</p>
<div class="scroll" id="cost-table"></div>
</div>

<div class="card" id="sessions-card">
<h2>Short charging sessions need fast chargers</h2>
<p>Share of rides served at 500 vehicles, by length of charging slot, drive to the depot and charger power.</p>
<div class="scroll" id="sessions-table"></div>
</div>

<div class="card" id="planner-card">
<h2>An earlier result: a depot sized for the average week fails most weeks</h2>
<p>From the first version of the simulator, before in-order feeding and replayed demand. The direction is likely to stand; the charger counts and battery sizes are first-version figures.</p>
<div class="scroll" id="robust-table"></div>
</div>

<footer>An independent project built on public data. Not affiliated with or endorsed by Waymo. Method, sources and every registered test are in the repository.</footer>
</main>
<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const COLORS = ["var(--s1)", "var(--s2)", "var(--s3)"];
const el = (tag, attrs = {}, text) => {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
};
const html = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const pct = v => (v * 100).toFixed(1) + "%";
const num = v => Math.round(v).toLocaleString("en-US");
const usd = v => "$" + v.toFixed(2);

function legend(id, series) {
  const box = document.getElementById(id);
  series.forEach((s, i) => {
    const item = html("span");
    const key = html("i");
    key.style.borderColor = COLORS[i];
    item.append(key, document.createTextNode(s.name));
    box.append(item);
  });
}

function lineChart(id, cfg) {
  const host = document.getElementById(id);
  const W = 900, H = 320, m = { l: 52, r: cfg.endLabels ? 96 : 16, t: 12, b: 32 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": cfg.label });
  const xs = cfg.x, x0 = xs[0], x1 = xs[xs.length - 1];
  const X = v => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r);
  const Y = v => H - m.b - (v - cfg.yMin) / (cfg.yMax - cfg.yMin) * (H - m.t - m.b);
  cfg.yTicks.forEach(t => {
    svg.append(el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: "var(--grid)", "stroke-width": 1 }));
    svg.append(el("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, cfg.yFmt(t)));
  });
  svg.append(el("line", { x1: m.l, x2: W - m.r, y1: Y(cfg.yMin), y2: Y(cfg.yMin), stroke: "var(--axis)", "stroke-width": 1 }));
  cfg.xTicks.forEach(t => svg.append(el("text", { x: X(t), y: H - m.b + 18, "text-anchor": "middle" }, cfg.xFmt(t))));
  if (cfg.ref) {
    svg.append(el("line", { x1: m.l, x2: W - m.r, y1: Y(cfg.ref.value), y2: Y(cfg.ref.value), stroke: "var(--ink2)", "stroke-width": 1 }));
    svg.append(el("text", { x: W - m.r, y: Y(cfg.ref.value) - 6, "text-anchor": "end", class: "end" }, cfg.ref.label));
  }
  cfg.series.forEach((s, i) => {
    const d = s.values.map((v, k) => `${k ? "L" : "M"}${X(xs[k]).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    svg.append(el("path", { d, fill: "none", stroke: COLORS[i], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = s.values[s.values.length - 1];
    svg.append(el("circle", { cx: X(x1), cy: Y(last), r: 4, fill: COLORS[i], stroke: "var(--surface)", "stroke-width": 2 }));
  });
  if (cfg.endLabels) {
    // Series that end within a line of text of each other share one label instead of overprinting.
    const ends = cfg.series.map(s => s.values[s.values.length - 1]).sort((a, b) => b - a);
    const groups = [];
    ends.forEach(v => {
      const g = groups[groups.length - 1];
      if (g && Math.abs(Y(g[0]) - Y(v)) < 14) g.push(v); else groups.push([v]);
    });
    groups.forEach(g => {
      const low = cfg.yFmt(g[g.length - 1]), high = cfg.yFmt(g[0]);
      const text = low === high ? high : low + " to " + high;
      svg.append(el("text", { x: X(x1) + 10, y: Y(g[0]) + 4, class: "end" }, text));
    });
  }
  const cross = el("line", { y1: m.t, y2: H - m.b, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
  svg.append(cross);
  const dots = cfg.series.map((s, i) => {
    const dot = el("circle", { r: 4, fill: COLORS[i], stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" });
    svg.append(dot);
    return dot;
  });
  const tip = html("div", undefined, "tip");
  host.append(svg, tip);
  const show = k => {
    cross.setAttribute("x1", X(xs[k])); cross.setAttribute("x2", X(xs[k])); cross.setAttribute("visibility", "visible");
    tip.replaceChildren(html("div", cfg.xTip(xs[k]), "head"));
    cfg.series.forEach((s, i) => {
      dots[i].setAttribute("cx", X(xs[k])); dots[i].setAttribute("cy", Y(s.values[k])); dots[i].setAttribute("visibility", "visible");
      const row = html("div");
      const key = html("i"); key.style.borderColor = COLORS[i];
      row.append(key, html("b", cfg.yFmt(s.values[k])), document.createTextNode(" " + s.name));
      tip.append(row);
    });
    tip.style.display = "block";
    const px = X(xs[k]) / W * host.clientWidth;
    tip.style.left = Math.min(Math.max(0, px + 12), host.clientWidth - tip.offsetWidth) + "px";
    tip.style.top = "8px";
  };
  const hide = () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); };
  svg.addEventListener("pointermove", e => {
    const box = svg.getBoundingClientRect();
    const v = x0 + ((e.clientX - box.left) / box.width * W - m.l) / (W - m.l - m.r) * (x1 - x0);
    let best = 0;
    xs.forEach((x, k) => { if (Math.abs(x - v) < Math.abs(xs[best] - v)) best = k; });
    show(best);
  });
  svg.addEventListener("pointerleave", hide);
}

function table(id, head, rows) {
  const t = html("table");
  const tr = html("tr");
  head.forEach(h => tr.append(html("th", h)));
  t.append(tr);
  rows.forEach(r => { const row = html("tr"); r.forEach(c => row.append(html("td", c))); t.append(row); });
  document.getElementById(id).append(t);
}
function tile(label, value, note) {
  const node = html("div", undefined, "tile");
  node.append(html("div", label, "label"), html("div", value, "value"), html("div", note, "note"));
  document.getElementById("tiles").append(node);
}

// Tiles.
const G = DATA.growth;
tile("One feeder, 2.75 MW", num(G.limits.one_feeder) + " vehicles", "largest simulated fleet with 99% of rides served");
tile("Two feeders, 5.5 MW", num(G.limits.two_feeders) + " vehicles", "largest simulated fleet with 99% of rides served");
if (DATA.apart) {
  const t = DATA.apart.table;
  // Difference of the rounded figures, so the tile agrees with the table under it.
  const gain = (Math.round(t["threshold+slot_power_1000"].served * 1000) - Math.round(t["threshold+need_first_1000"].served * 1000)) / 10;
  tile("In-order feeding", "+" + gain.toFixed(1) + " points", "rides served at 1,000 vehicles on one feeder, against emptiest-first; about 2 points at a well-staffed depot");
}
if (DATA.cost) {
  const c = DATA.cost.table;
  const saving = 1 - c.plan_with_prices_500.cost_per_kwh / c.threshold_500.cost_per_kwh;
  tile("Price-aware plan", Math.round(saving * 100) + "% cheaper", "energy per kWh at 500 vehicles, with no loss of rides");
}

if (DATA.apart) {
  const t = DATA.apart.table;
  const names = { threshold: "Fixed threshold", headroom: "Fill every free charger", heartbeat: "Day-ahead plan" };
  const rows = [];
  [1000, 500].forEach(size => Object.keys(names).forEach(r => rows.push([num(size), names[r],
    pct(t[`${r}+need_first_${size}`].served), pct(t[`${r}+slot_power_${size}`].served)])));
  table("apart-table", ["Fleet", "Vehicles called in by", "Power to the emptiest first", "Power in order of plugging in"], rows);
}

legend("growth-legend", G.series);
lineChart("growth", {
  label: "Share of rides served by fleet size under three grid options",
  x: G.sizes, series: G.series.map(s => ({ name: s.name, values: s.served })),
  yMin: 0.4, yMax: 1.0, yTicks: [0.4, 0.6, 0.8, 1.0], yFmt: v => Math.round(v * 100) + "%",
  xTicks: G.sizes.filter(s => s % 400 === 0 || s === 200), xFmt: num, xTip: v => num(v) + " vehicles", endLabels: true,
});
table("growth-table", ["Fleet", ...G.series.map(s => s.name)], G.sizes.map((s, k) => [num(s), ...G.series.map(g => pct(g.served[k]))]));

const d = DATA.days;
document.getElementById("days-sub").textContent =
  `Vehicles on the road each hour against what the depot committed at the start of that hour. ${num(d.fleet)} vehicles, ${d.chargers} chargers, two days.`;
const hourLabel = h => `Day ${Math.floor(h / 24) + 1}, ${String(h % 24).padStart(2, "0")}:00`;
const clock = h => String(h % 24).padStart(2, "0") + ":00";
const held = d.hours.map((h, k) => k).filter(k => d.promised[k] !== null);
const ledgerSeries = [{ name: "Delivered", values: held.map(k => d.delivered[k]) }, { name: "Promised", values: held.map(k => d.promised[k]) }];
legend("ledger-legend", ledgerSeries);
const hx = held.map(k => d.hours[k]);
const roadTop = Math.ceil(d.fleet / 100) * 100;
lineChart("ledger", {
  label: "Vehicles on the road: promised and delivered", x: hx, series: ledgerSeries,
  yMin: 0, yMax: roadTop, yTicks: [0, roadTop / 2, roadTop], yFmt: num,
  xTicks: hx.filter(h => h % 6 === 0), xFmt: clock, xTip: hourLabel,
});
lineChart("grid", {
  label: "Grid draw by hour", x: d.hours, series: [{ name: "Grid draw", values: d.grid_kw }],
  yMin: 0, yMax: 3000, yTicks: [0, 1000, 2000, 3000], yFmt: v => num(v) + " kW",
  xTicks: d.hours.filter(h => h % 6 === 0), xFmt: clock, xTip: hourLabel,
  ref: { value: d.limit_kw, label: "Site limit " + num(d.limit_kw) + " kW" },
});
table("days-table", ["Hour", "Grid kW", "Charging", "Promised on the road", "Delivered"],
  d.hours.map((h, k) => [hourLabel(h), num(d.grid_kw[k]), d.charging[k].toFixed(1), d.promised[k] === null ? "" : num(d.promised[k]), d.delivered[k] === null ? "" : num(d.delivered[k])]));

if (DATA.cost) {
  const c = DATA.cost.table;
  const arms = [["threshold", "Fixed threshold"], ["threshold_steered", "Threshold that knows the clock"], ["plan", "Day-ahead plan"], ["plan_with_prices", "Plan told the price"]];
  table("cost-table", ["Rule", "Rides served", "Bought at the peak", "Price per kWh", "Fares less energy"],
    arms.map(([key, name]) => { const r = c[key + "_500"]; return [name, pct(r.served), pct(r.peak_period_share), "$" + r.cost_per_kwh.toFixed(3), usd(r.fares_less_energy_per_vehicle_day)]; }));
} else { document.getElementById("cost-card").remove(); }

if (DATA.sessions) {
  const rows = DATA.sessions.rows.filter(r => r.size === 500 && r.leg_minutes !== 10);
  table("sessions-table", ["Drive each way", "Chargers", "20 min slot", "30 min", "45 min", "60 min"],
    rows.map(r => [r.leg_minutes + " min", r.charger_kw + " kW", pct(r.served_20min), pct(r.served_30min), pct(r.served_45min), pct(r.served_60min)]));
} else { document.getElementById("sessions-card").remove(); }

if (DATA.planner) {
  const caseName = c => num(c.size) + " vehicles, " + (c.site_limit_kw / 1000).toFixed(2) + " MW";
  const rows = [];
  DATA.planner.robust.forEach(c => {
    [["the expected week", c.expected], ["demand scenarios", c.robust]].forEach(([label, r]) => {
      rows.push(r ? [caseName(c.case), label, r.scenarios_serving_99pct + " of 20"] : [caseName(c.case), label, "no such depot"]);
    });
  });
  table("robust-table", ["Fleet and grid", "Sized for", "Weeks at 99% service"], rows);
} else { document.getElementById("planner-card").remove(); }
</script>
</body>
</html>
"""
