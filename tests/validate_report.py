"""Smoke-test the DOCX report generator against the canonical data."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check() -> None:
    from docx import Document

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.docx"
        subprocess.run(
            [sys.executable, str(ROOT / "src" / "report.py"),
             "--year", "2026", "--from", "1", "--to", "6",
             "--prev-year", "2025", "--output", str(out)],
            check=True, cwd=ROOT, capture_output=True, text=True,
        )
        assert out.exists() and out.stat().st_size > 50_000

        d = Document(out)
        text = "\n".join(p.text for p in d.paragraphs)
        text += "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)

        headings = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
        for expected in ["1 KENYA'S TRADE PERFORMANCE", "2 Comparative Perspectives",
                         "3 Lead Destination Markets", "4 Composition of Kenya's",
                         "5 Deduction from the", "6 Annex"]:
            assert any(expected in h for h in headings), f"Missing heading: {expected}"

        assert len(d.inline_shapes) == 3, "Expected 3 embedded charts"
        assert len(d.tables) >= 8, "Expected 8+ tables"
        for needle in ["530.7", "892.2", "UGANDA", "Horticulture",
                       "DATA QUALITY WARNING", "Annex 1", "Annex 2"]:
            assert needle in text, f"Missing expected content: {needle}"
        print(f"  OK  report.docx — {len(d.paragraphs)} paragraphs, "
              f"{len(d.tables)} tables, {len(d.inline_shapes)} charts")
    print("DOCX report generator valid.")


if __name__ == "__main__":
    check()
