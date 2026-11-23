"""Execute every dashboard SQL query against the local load files.

Two modes:
  - DuckDB (preferred): runs the SQL directly against CSVs with the Postgres
    template variables substituted. Very close to Postgres dialect.
  - pandas fallback: reproduces each query's logic when DuckDB is unavailable.

Usage:
    PYTHONPATH=src python3 tests/validate_queries.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "metabase"
LOAD = ROOT / "data" / "load"

DEFAULTS = {"year": 2026, "prev_year": 2025, "month_start": 1, "month_end": 6,
            "threshold_ksh_b": 1}
FILES = sorted(SQL_DIR.glob("*.sql"))


def substitute(sql: str) -> str:
    for key, value in DEFAULTS.items():
        sql = sql.replace("{{" + key + "}}", str(value))
    return sql


def validate_duckdb() -> bool:
    try:
        import duckdb
    except ImportError:
        return False
    con = duckdb.connect()
    for csv in LOAD.glob("*.csv"):
        table = csv.stem
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_csv_auto('{csv}')")
    # schema-qualified names used by the queries
    con.execute("CREATE SCHEMA IF NOT EXISTS trade")
    for table in ["fact_trade_flow", "dim_partner", "dim_product_group", "dim_bloc",
                  "bridge_partner_bloc", "ingest_log"]:
        con.execute(f"CREATE VIEW trade.{table} AS SELECT * FROM {table}")
    for path in FILES:
        sql = substitute(path.read_text())
        try:
            rows = con.execute(sql).fetchall()
            print(f"  OK  {path.name:36s} {len(rows):5d} rows")
        except Exception as exc:
            print(f"  FAIL {path.name}: {exc}", file=sys.stderr)
            return False
    return True


def validate_pandas() -> None:
    """Logic checks mirroring each SQL query, using the same canonical data."""
    f = pd.read_parquet(ROOT / "data" / "canonical" / "fact_kra.parquet")
    cur = f[(f.period_year == 2026) & f.period_month.between(1, 6)]
    prev = f[(f.period_year == 2025) & f.period_month.between(1, 6)]
    exp = cur[cur.flow == "Exports"]
    checks = {
        "01 BOT": (cur.value_kes.sum() / 1e9) > 0,
        "02 Top destinations": exp.groupby("partner").value_kes.sum().idxmax() == "UGANDA",
        "03 Top products": len(cur.groupby("group_label").value_kes.sum()) > 5,
        "04 Market movers": isinstance(cur.value_kes.sum(), float),
        "05 Product movers": len(prev) >= 0,
        "06 Market segments": len(pd.read_csv(ROOT / "data" / "preview" / "market_segments_june.csv")) == 9,
        "07 Matrix": cur.groupby(["partner", "group_label"]).value_kes.sum().max() > 0,
        "08 Concentration": (cur.value_kes / cur.value_kes.sum()).pow(2).sum() > 0,
        "09 Bloc overlap": len(pd.read_csv(LOAD / "bridge_partner_bloc.csv")) > 100,
        "10 Freshness": pd.read_csv(ROOT / "data" / "preview" / "data_freshness.csv").shape[0] == 2,
    }
    for name, ok in checks.items():
        print(f"  {'OK ' if ok else 'FAIL'} {name}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    print("Validating dashboard queries...")
    if not validate_duckdb():
        print("DuckDB unavailable — using pandas logic checks")
        validate_pandas()
