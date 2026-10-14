"""Loaders for the public data the twin is built on.

Each loader has a network half that fetches and caches the source file, and a pure half that parses it. The
pure half is what the tests cover, so the test suite never needs the network. Raw third-party files are
cached under data/raw and never committed; the small derived tables under data/derived are.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

USER_AGENT = "depot-twin/0.1 (research; public data)"


def data_dir() -> Path:
    """Return the data directory: $DEPOT_TWIN_DATA when set, otherwise ./data."""
    return Path(os.environ.get("DEPOT_TWIN_DATA", "data"))


def fetch(url: str, cache_as: str, timeout: float = 120.0) -> Path:
    """Download a file once and return its cached path under data/raw."""
    target = data_dir() / "raw" / cache_as
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        target.write_bytes(response.read())
    return target
