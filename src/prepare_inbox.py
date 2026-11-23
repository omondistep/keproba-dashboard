"""Extract downloaded ZIP archives into inbox/kra and inbox/itc.

Kept deliberately simple: KRA ships legacy .xls exports/imports, ITC ships
.xlsx trade-map workbooks. Filenames are matched as a fallback so a future
.xlsx KRA extract is still classified correctly.

Usage: PYTHONPATH=src python3 src/prepare_inbox.py
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"

KRA_HINTS = ("epc", "kra", "by hs", "destination", "origin", "customs")
ITC_HINTS = ("itc", "trade map", "reporter", "partner", "economies", "globally")


def destination(name: str) -> str:
    low = name.lower()
    if any(h in low for h in ITC_HINTS) and not any(h in low for h in KRA_HINTS):
        return "itc"
    if any(h in low for h in KRA_HINTS):
        return "kra"
    return "kra" if low.endswith(".xls") else "itc"


def prepare() -> None:
    archives = sorted(INBOX.glob("*.zip")) if INBOX.exists() else []
    if not archives:
        print("No ZIP archives in inbox/")
        return

    total = 0
    for archive in archives:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            try:
                with zipfile.ZipFile(archive) as z:
                    z.extractall(tmp)
            except zipfile.BadZipFile:
                print(f"SKIP corrupt archive: {archive.name}")
                continue

            for path in sorted(tmp.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".xls", ".xlsx"}:
                    continue
                if path.name.startswith("~$") or "__MACOSX" in path.parts:
                    continue
                target_dir = INBOX / destination(path.name)
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / path.name
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                existing = (hashlib.sha256(target.read_bytes()).hexdigest()
                            if target.exists() else None)
                if existing == digest:
                    continue
                shutil.copy2(path, target)
                total += 1
                print(f"[{target_dir.name}] {path.name}  ({archive.name})")
    print(f"Prepared {total} new file(s) in inbox/kra and inbox/itc")


if __name__ == "__main__":
    prepare()
