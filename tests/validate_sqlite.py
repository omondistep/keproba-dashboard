"""Execute all dashboard queries in SQLite as a Postgres-dialect smoke test.

SQLite 3.30+ supports FILTER clauses and window functions, so the Metabase
queries run almost unchanged. The only adaptations are:
  - substitute {{template variables}}
  - strip the `trade.` schema qualifier
  - load CSVs into in-memory tables

Usage: PYTHONPATH=src python3 tests/validate_sqlite.py
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "metabase"
LOAD = ROOT / "data" / "load"
DEFAULTS = {"year": 2026, "prev_year": 2025, "month_start": 1, "month_end": 6,
            "threshold_ksh_b": 1}


def load(con: sqlite3.Connection) -> None:
    for csv_path in sorted(LOAD.glob("*.csv")):
        with csv_path.open(newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            table = csv_path.stem
            numeric = {"period_year", "period_month", "value_original", "value_usd",
                       "value_kes", "quantity", "member_count"}
            defs = []
            for c in header:
                typ = "NUMERIC" if c in numeric else "TEXT"
                defs.append(f'"{c}" {typ}')
            # loaded_at has a DB default in Postgres; add it for the freshness query.
            if table == "fact_trade_flow" and "loaded_at" not in header:
                defs.append('"loaded_at" TEXT')
            con.execute(f"CREATE TABLE {table} ({', '.join(defs)})")
            placeholders = ",".join("?" * len(defs))  # includes added columns
            con.executemany(
                f"INSERT INTO {table} VALUES ({placeholders})",
                (tuple(("" if v == "" else
                        (1 if v == "True" else 0 if v == "False" else v))
                       for v in row) + (None,) * (len(defs) - len(header))
                 for row in reader),
            )


def main() -> None:
    con = sqlite3.connect(":memory:")
    load(con)
    ok = True
    for path in sorted(SQL_DIR.glob("*.sql")):
        sql = path.read_text()
        for k, v in DEFAULTS.items():
            sql = sql.replace("{{" + k + "}}", str(v))
        sql = sql.replace("trade.", "")
        try:
            rows = con.execute(sql).fetchall()
            print(f"  OK   {path.name:36s} {len(rows):5d} rows  sample={rows[0][:3] if rows else ''}")
        except Exception as exc:
            ok = False
            print(f"  FAIL {path.name}: {exc}", file=sys.stderr)
    if not ok:
        raise SystemExit(1)
    print("All dashboard SQL executed successfully.")


if __name__ == "__main__":
    main()
