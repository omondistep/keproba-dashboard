"""Build the zero-server static dashboard from canonical Parquet files.

Produces site/data/*.parquet and site/data/manifest.json. The dashboard JS
registers each Parquet file as a DuckDB-WASM view, so all queries run locally
in the visitor's browser — no backend, database, or server required.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "data" / "canonical"
LOAD = ROOT / "data" / "load"
SITE_DATA = ROOT / "site" / "data"

FILES = [
    ("fact_kra.parquet", "fact_kra"),
    ("fact_itc.parquet", "fact_itc"),
]
RECONCILIATION = ROOT / "data" / "reconciliation_report.csv"


def build() -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)

    manifest_files = []
    for name, view in FILES:
        src = CANONICAL / name
        if not src.exists():
            raise SystemExit(f"Missing {src} — run `src/pipeline.py ingest` first")
        shutil.copy2(src, SITE_DATA / name)
        manifest_files.append({"name": name, "view": view})
        print(f"  copied {name} ({src.stat().st_size / 1e6:.1f} MB)")

    # Bloc bridge as Parquet with segment priority for the browser's CASE logic.
    bridge = pd.read_csv(LOAD / "bridge_partner_bloc.csv")
    bridge.to_parquet(SITE_DATA / "bridge_partner_bloc.parquet", index=False)
    manifest_files.append({"name": "bridge_partner_bloc.parquet", "view": "bridge_partner_bloc"})

    kra = pd.read_parquet(CANONICAL / "fact_kra.parquet")
    groups = (kra[["group_code", "group_label"]].dropna().drop_duplicates()
                .sort_values("group_code"))
    exp = kra[kra.flow == "Exports"]
    months = sorted(exp.period_month.dropna().astype(int).unique().tolist())
    latest_year = int(exp.period_year.max())
    latest_month = int(exp[exp.period_year == latest_year].period_month.max())

    warning = None
    if RECONCILIATION.exists():
        r = pd.read_csv(RECONCILIATION)
        export_rows = r[r.Side == "Exports"]
        sampled = export_rows[export_rows.ratio.round(4) == 0.5]
        if not sampled.empty:
            miss = sorted(set(range(1, max(months) + 1)) - set(months))
            warning = (
                "DATA QUALITY: The supplied KRA export extract is a 50% sample for "
                + ", ".join(f"month {m}" for m in sampled.Month.unique())
                + (f" and excludes month(s) {', '.join(map(str, miss))}" if miss else "")
                + ". Figures are indicative only — request the complete extract before publication."
            )

    manifest = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "rows": int(len(kra) + len(pd.read_parquet(CANONICAL / "fact_itc.parquet"))),
        "files": manifest_files,
        "years": sorted(kra.period_year.unique().tolist(), reverse=True),
        "groups": [{"code": str(r.group_code), "label": str(r.group_label)}
                   for r in groups.itertuples()],
        "freshness": {
            "latest_year": latest_year,
            "latest_month": latest_month,
            "export_months": ", ".join(str(m) for m in months),
            "stale": False,
        },
        "warning": warning,
    }
    (SITE_DATA / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {SITE_DATA.relative_to(ROOT)}/manifest.json ({len(manifest_files)} data files)")
    if warning:
        print("Warning embedded in dashboard:", warning)


if __name__ == "__main__":
    build()
