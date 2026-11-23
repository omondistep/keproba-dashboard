"""Validate that the static site has all required assets and valid data."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def check() -> None:
    for name in ["index.html", "app.js", "styles.css"]:
        p = SITE / name
        assert p.exists() and p.stat().st_size > 100, f"Missing/empty {name}"
    m = json.loads((SITE / "data" / "manifest.json").read_text())
    for f in m["files"]:
        p = SITE / "data" / f["name"]
        assert p.exists() and p.stat().st_size > 0, f"Missing {f['name']}"
        if f["name"].endswith(".parquet"):
            df = pd.read_parquet(p)
            assert len(df) > 0, f"Empty {f['name']}"
            print(f"  OK  {f['name']:32s} {len(df):7,} rows")
    assert m["rows"] > 100_000
    assert m["freshness"]["latest_year"] == 2026
    assert m["freshness"]["latest_month"] == 6
    assert m["warning"] and "50% sample" in m["warning"]
    assert len(m["groups"]) > 50
    print(f"  OK  manifest: {m['rows']:,} rows, warning embedded, {len(m['groups'])} groups")
    print("Static site assets valid.")


if __name__ == "__main__":
    check()
