"""Grid capacity near a site, from PG&E's public Integration Capacity Analysis.

The utility publishes, for every section of every distribution feeder, how much new load that section can
take before a limit is hit. A depot connects to one feeder, so the feeder's headroom at the parcel is the
depot's power limit until the utility builds something new.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from depot_twin.data import USER_AGENT

ICA_QUERY_URL = (
    "https://services2.arcgis.com/mJaJSax0KPHoCNB6/ArcGIS/rest/services/DRPComplianceRelProd/FeatureServer/3/query"
)
FIELDS = "FeederId,FeederName,LoadCapacity_kW,voltage_kv,ICA_Analysis_Date"


@dataclass(frozen=True)
class Feeder:
    """Load headroom on one feeder, over the line sections near a site."""

    name: str
    feeder_id: str
    voltage_kv: float
    min_kw: float
    max_kw: float
    sections: int

    def as_dict(self) -> dict:
        """Return the feeder as plain data."""
        return asdict(self)


def fetch_sections(lat: float, lon: float, radius_m: float = 250.0, timeout: float = 60.0) -> list[dict]:
    """Return the attributes of every feeder line section within radius_m of a point."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": str(radius_m),
        "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{ICA_QUERY_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"ICA query failed: {payload['error']}")
    return [feature["attributes"] for feature in payload.get("features", [])]


def summarize_feeders(sections: list[dict]) -> list[Feeder]:
    """Group line sections by feeder and return each feeder's headroom range, strongest first.

    Sections with no published capacity are skipped. The range matters: where on the feeder the depot
    connects decides which end of it applies.
    """
    by_feeder: dict[str, list[dict]] = {}
    for section in sections:
        if section.get("LoadCapacity_kW") is None:
            continue
        by_feeder.setdefault(str(section["FeederId"]), []).append(section)
    feeders = []
    for feeder_id, rows in by_feeder.items():
        capacities = [float(row["LoadCapacity_kW"]) for row in rows]
        feeders.append(
            Feeder(
                name=str(rows[0].get("FeederName") or feeder_id),
                feeder_id=feeder_id,
                voltage_kv=float(rows[0].get("voltage_kv") or 0.0),
                min_kw=min(capacities),
                max_kw=max(capacities),
                sections=len(rows),
            )
        )
    return sorted(feeders, key=lambda f: f.max_kw, reverse=True)
