"""Folder watcher: detect new raw files, ingest, reconcile, and reload Postgres.

Designed to run as a systemd user service on the VPS. New files are dropped into
inbox/kra or inbox/itc; this script hashes them, skips ones already archived, and
only triggers a reload when something actually changed.

Usage:
    PYTHONPATH=src python3 src/watch.py --once     # single check
    PYTHONPATH=src python3 src/watch.py            # poll every 60s
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import time
from pathlib import Path

from pipeline import CANONICAL, FINISHED, INBOX, RAW, ingest, reconcile
from load_db import emit_load_files, build_previews

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "watch_state.sha256"


def archive_hashes() -> set[str]:
    out = set()
    for source in ("kra", "itc"):
        d = RAW / source
        if d.exists():
            out |= {p.name[:12] for p in d.glob("*_*.xls*")}
    return out


def inbox_hashes() -> dict[str, Path]:
    out = {}
    for source in ("kra", "itc"):
        d = INBOX / source
        if not d.exists():
            continue
        for p in d.glob("*.xls*"):
            if not p.name.startswith("~$"):
                out[hashlib.sha256(p.read_bytes()).hexdigest()[:12]] = p
    return out


def run_pipeline() -> None:
    print("[watch] change detected — running ingest")
    ingest()
    print("[watch] reconciling against published workbooks")
    reconcile()
    print("[watch] regenerating load files and dashboard previews")
    emit_load_files()
    build_previews()
    if (ROOT / ".env").exists():
        print("[watch] reloading Postgres via data/load/load.sql")
        # psql reads .env-style vars via the shell; the operator runs the
        # connection string through WATCH_PSQL_CMD if reload is desired.
        cmd = __import__("os").environ.get("WATCH_PSQL_CMD")
        if cmd:
            subprocess.run(cmd, shell=True, cwd=ROOT, check=True)
    STATE.write_text("\n".join(sorted(inbox_hashes())) + "\n")
    print("[watch] done")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    while True:
        current = set(inbox_hashes())
        seen = set(STATE.read_text().split()) if STATE.exists() else set()
        new = current - seen
        if new:
            for h in new:
                print(f"[watch] new file: {inbox_hashes()[h].name}")
            run_pipeline()
        elif not (CANONICAL / "fact_kra.parquet").exists():
            run_pipeline()
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
