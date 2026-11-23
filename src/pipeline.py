"""CLI: raw inbox -> immutable archive -> canonical parquet -> reconciliation."""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

import pandas as pd

from adapters import parse_file

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
RAW = ROOT / "raw"
CANONICAL = ROOT / "data" / "canonical"
FINISHED = ROOT / "sample reports and excel"
REPORT = ROOT / "data" / "reconciliation_report.csv"


def ingest() -> None:
    CANONICAL.mkdir(parents=True, exist_ok=True)
    frames = []
    for source in ("kra", "itc"):
        inbox_dir = INBOX / source
        if not inbox_dir.exists():
            continue
        for path in sorted(inbox_dir.iterdir()):
            if path.suffix.lower() not in {".xls", ".xlsx"} or path.name.startswith("~$"):
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            archive_dir = RAW / source
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived = archive_dir / f"{digest[:12]}_{path.name}"
            if not archived.exists():
                shutil.copy2(path, archived)
            print(f"[{source}] {path.name} -> {digest[:12]}")
            frames.append(parse_file(path, source))

    if not frames:
        print("No files found in inbox/kra or inbox/itc")
        return

    all_rows = pd.concat(frames, ignore_index=True)
    for system, chunk in all_rows.groupby("source_system"):
        out = CANONICAL / f"fact_{system.lower()}.parquet"
        chunk.to_parquet(out, index=False)
        print(f"Wrote {len(chunk):,} rows -> {out.relative_to(ROOT)}")


def reconcile() -> None:
    """Compare raw-derived group totals with the published Jan-Jun workbook."""
    kra_path = CANONICAL / "fact_kra.parquet"
    if not kra_path.exists():
        raise SystemExit("Run `ingest` first")
    fact = pd.read_parquet(kra_path)

    finished = None
    for candidate in FINISHED.glob("MEAT AND HORTICULTURE*.xlsx"):
        finished = candidate
        break
    if finished is None:
        raise SystemExit("Finished Jan-Jun workbook not found")

    expected = pd.read_excel(
        finished, sheet_name="DATA GROUP", usecols="A:F",
        header=0, skiprows=0,
    )
    expected.columns = [str(c).strip() for c in expected.columns]
    expected = expected[expected["Year"] == 2026]
    expected = expected[expected["Side"].isin(["Exports", "Imports"])]
    expected["group_code"] = expected["Group"].astype(str)
    expected = expected[["Year", "Month", "Side", "group_code", "Value (Ksh. Billion)"]]
    expected["Month"] = expected["Month"].astype(int)

    actual = (fact.groupby(["period_year", "period_month", "flow", "group_code"])["value_kes"]
                .sum().div(1e9).reset_index())
    actual.columns = ["Year", "Month", "Side", "group_code", "raw_Ksh_B"]
    actual["Month"] = actual["Month"].astype(int)

    # Only compare groups that the published workbook actually reports.
    merged = expected.merge(actual, on=["Year", "Month", "Side", "group_code"], how="inner")
    merged["diff_Ksh_B"] = merged["raw_Ksh_B"] - merged["Value (Ksh. Billion)"]
    merged["ratio"] = merged["raw_Ksh_B"] / merged["Value (Ksh. Billion)"]
    merged = merged.sort_values(["Side", "group_code", "Month"])
    merged.to_csv(REPORT, index=False)
    print(merged.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print(f"\nWrote {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ingest", "reconcile"])
    args = parser.parse_args()
    {"ingest": ingest, "reconcile": reconcile}[args.command]()
