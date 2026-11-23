"""Create the Metabase database, questions and dashboard via the REST API.

Run after `docker compose up -d` and after loading sql/01_schema.sql + data/load/load.sql:
    MB_URL=http://localhost:3000 MB_EMAIL=admin@... MB_PASSWORD=... \
    python3 metabase/bootstrap.py
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "metabase"

# name, file, display, size (x,y), template variable defaults
QUESTIONS = [
    ("01 Executive Summary — Balance of Trade", "01_executive_bot.sql", "scalar", (12, 4)),
    ("02 Top Destination Markets", "02_top_destinations.sql", "bar", (12, 8)),
    ("03 Top Export Products", "03_top_products.sql", "bar", (12, 8)),
    ("04 Destinations Gaining / Losing > Ksh 1B", "04_market_movers.sql", "table", (12, 8)),
    ("05 Higher / Weaker Performing Products", "05_product_movers.sql", "table", (12, 8)),
    ("06 Market Segments (exclusive)", "06_market_segments.sql", "pie", (12, 8)),
    ("07 Product x Destination Matrix", "07_partner_product_matrix.sql", "table", (12, 8)),
    ("08 Export Concentration (HHI)", "08_concentration.sql", "scalar", (6, 4)),
    ("09 Trade Blocs (overlapping — do not sum)", "09_bloc_overlap.sql", "bar", (12, 8)),
    ("10 Data Freshness", "10_data_freshness.sql", "table", (12, 4)),
]

VARIABLES = {
    "year": ("Year", 2026),
    "prev_year": ("Previous year", 2025),
    "month_start": ("Month from", 1),
    "month_end": ("Month to", 6),
    "threshold_ksh_b": ("Threshold (Ksh B)", 1),
}


def tags_for(sql: str) -> dict:
    out = {}
    for name, (display, default) in VARIABLES.items():
        if "{{" + name + "}}" in sql:
            out[name] = {
                "id": name, "name": name, "type": "number",
                "display_name": display, "default": default, "required": True,
            }
    return out


def api(session: requests.Session, base: str, method: str, path: str, **kwargs):
    r = session.request(method, base + path, timeout=60, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
    return r.json() if r.text else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only validate SQL files")
    args = ap.parse_args()

    missing = [f for _, f, _, _ in QUESTIONS if not (SQL_DIR / f).exists()]
    if missing:
        raise SystemExit(f"Missing query files: {missing}")
    if args.check:
        print(f"Validated {len(QUESTIONS)} query files in {SQL_DIR.relative_to(ROOT)}")
        return

    base = os.environ.get("MB_URL", "http://localhost:3000").rstrip("/")
    email = os.environ["MB_EMAIL"]
    password = os.environ["MB_PASSWORD"]
    s = requests.Session()
    token = api(s, base, "POST", "/api/session", json={"username": email, "password": password})["id"]
    s.headers.update({"X-Metabase-Session": token})

    db = api(s, base, "POST", "/api/database", json={
        "name": "KEPROBA Trade (Postgres)",
        "engine": "postgres",
        "details": {
            "host": os.environ.get("PG_HOST", "postgres"),
            "port": int(os.environ.get("PG_PORT", 5432)),
            "dbname": os.environ.get("PG_DB", "keproba"),
            "user": os.environ.get("PG_USER", "keproba"),
            "password": os.environ["PG_PASSWORD"],
        },
    })
    db_id = db["id"]

    dash = api(s, base, "POST", "/api/dashboard", json={
        "name": "Export Policy Performance Dashboard",
        "description": "KEPROBA trade intelligence — raw KRA + ITC data",
    })
    cards = []
    for i, (name, filename, display, size) in enumerate(QUESTIONS):
        sql = (SQL_DIR / filename).read_text()
        card = api(s, base, "POST", "/api/card", json={
            "name": name,
            "display": display,
            "database_id": db_id,
            "dataset_query": {
                "database": db_id,
                "type": "native",
                "native": {"query": sql, "template-tags": tags_for(sql)},
            },
            "visualization_settings": {},
        })
        cards.append(card["id"])
        api(s, base, "POST", f"/api/dashboard/{dash['id']}/cards", json={
            "cardId": card["id"], "row": (i // 2) * 4, "col": (i % 2) * size[0] / 2,
            "sizeX": size[0] / 2, "sizeY": size[1],
        })
        print(f"  added {name}")
    print(f"Dashboard ready: {base}/dashboard/{dash['id']}")


if __name__ == "__main__":
    main()
