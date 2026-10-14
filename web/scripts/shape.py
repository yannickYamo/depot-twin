"""Write web/src/shape.ts from data/derived/weekly_shape_sf.json: the week the browser's depot draws rides from.

Run from the repository root:  python web/scripts/shape.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    """Write the weekly demand shape as a TypeScript constant."""
    shares = json.loads((ROOT / "data" / "derived" / "weekly_shape_sf.json").read_text())["shares"]
    body = ", ".join(f"{share:.6f}".rstrip("0").rstrip(".") if share else "0" for share in shares)
    text = (
        "// Share of a week's rides in each hour, Monday 00:00 first. From San Francisco taxi trips over the\n"
        "// forecasts' training days, December 2022 to early February 2024 (city open data, public domain).\n"
        "// Generated from data/derived/weekly_shape_sf.json by web/scripts/shape.py.\n"
        f"export const WEEKLY_SHAPE: number[] = [{body}];\n"
    )
    (ROOT / "web" / "src" / "shape.ts").write_text(text)
    print(f"wrote web/src/shape.ts: {len(shares)} hours, sum {sum(shares):.6f}")


if __name__ == "__main__":
    main()
