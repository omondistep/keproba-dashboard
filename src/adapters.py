"""Source-specific adapters: raw download -> canonical long-format rows."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from normalize import normalize_partner, parse_itc_year_columns, product_group

CANONICAL_COLUMNS = [
    "source_system", "flow", "period_year", "period_month",
    "reporter", "partner", "partner_raw", "is_country",
    "product_code", "product_label", "group_code", "group_label",
    "value_original", "currency", "value_usd", "value_kes",
    "quantity", "quantity_unit", "source_file", "file_hash",
]


def _hash(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _xlsx_path(path: Path) -> Path:
    """LibreOffice converts legacy .xls; .xlsx is returned unchanged."""
    if path.suffix.lower() == ".xlsx":
        return path
    tmp = Path(tempfile.mkdtemp(prefix="kra_xls_"))
    subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "xlsx", "--outdir", str(tmp), str(path)],
        check=True, capture_output=True, timeout=300,
    )
    converted = list(tmp.glob("*.xlsx"))
    if not converted:
        raise RuntimeError(f"Could not convert {path.name} to xlsx")
    return converted[0]


def _side_from_name(name: str) -> str:
    n = name.lower()
    if "import" in n:
        return "Imports"
    if "export" in n:
        return "Exports"
    if "exporting-economies" in n:
        return "Exports"
    if "importing-economies" in n:
        return "Imports"
    raise ValueError(f"Cannot infer flow from filename: {name}")


# ---------------------------------------------------------------------------
# KRA: transaction-level monthly exports/imports (legacy .xls, KES)
# ---------------------------------------------------------------------------
def parse_kra(path: Path) -> pd.DataFrame:
    flow = _side_from_name(path.name)
    converted = _xlsx_path(path)
    wb = load_workbook(converted, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]

    idx = {name: i for i, name in enumerate(header)}
    def col(*names):
        for n in names:
            if n in idx:
                return idx[n]
        raise KeyError(f"Missing {names} in {path.name}; found {header}")

    i_year = col("Year")
    i_month = col("Month")
    i_partner = col("Destination Name", "Origin Name")
    i_hs = col("HS_C")
    i_qty = col("Quantity")
    i_unit = col("UNIT")
    i_value = col("CIF Value", "FOB Value", "Value")

    records = []
    for r in rows:
        if r[i_year] is None:
            continue
        raw_partner = r[i_partner]
        partner, is_country = normalize_partner(raw_partner)
        group_code, group_label = product_group(r[i_hs])
        hs = str(r[i_hs]).strip().lstrip("'")
        if isinstance(r[i_hs], (int, float)):
            hs = str(int(r[i_hs]))
        records.append({
            "source_system": "KRA",
            "flow": flow,
            "period_year": int(r[i_year]),
            "period_month": int(r[i_month]) if r[i_month] is not None else None,
            "reporter": "Kenya",
            "partner": partner,
            "partner_raw": str(raw_partner).strip() if raw_partner is not None else None,
            "is_country": is_country,
            "product_code": hs,
            "product_label": None,
            "group_code": group_code,
            "group_label": group_label,
            "value_original": float(r[i_value] or 0),
            "currency": "KES",
            "value_usd": None,   # FX layer applies later
            "value_kes": float(r[i_value] or 0),
            "quantity": float(r[i_qty]) if r[i_qty] is not None else None,
            "quantity_unit": str(r[i_unit]).strip() if r[i_unit] is not None else None,
            "source_file": path.name,
        })
    wb.close()
    df = pd.DataFrame(records, columns=CANONICAL_COLUMNS[:-1])
    df["file_hash"] = _hash(path)
    return df


# ---------------------------------------------------------------------------
# ITC Trade Map bulk download: flat wide table, annual, USD thousand
# ---------------------------------------------------------------------------
def parse_itc(path: Path) -> pd.DataFrame:
    flow = _side_from_name(path.name)
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    year_cols = parse_itc_year_columns(header)
    if not year_cols:
        raise ValueError(f"No year columns found in {path.name}")
    idx = {name: i for i, name in enumerate(header)}
    records = []
    for r in rows:
        if r[idx["reporterCd"]] is None:
            continue
        partner_raw = r[idx["partnerLabel"]]
        partner, is_country = normalize_partner(partner_raw)
        pc = r[idx["productCd"]]
        product_code = "TOTAL" if str(pc).upper() == "TOTAL" else str(pc).strip().lstrip("'")
        group_code, group_label = product_group(product_code) if product_code != "TOTAL" else ("TOTAL", "All Products")
        for col_name, (year, multiplier) in year_cols.items():
            value = r[idx[col_name]]
            if value is None:
                continue
            usd = float(value) * multiplier
            records.append({
                "source_system": "ITC",
                "flow": flow,
                "period_year": year,
                "period_month": None,
                "reporter": str(r[idx["reporterLabel"]]).strip(),
                "partner": partner,
                "partner_raw": str(partner_raw).strip(),
                "is_country": is_country,
                "product_code": product_code,
                "product_label": str(r[idx["productLabel"]]).strip(),
                "group_code": group_code,
                "group_label": group_label,
                "value_original": float(value),
                "currency": "USD",
                "value_usd": usd,
                "value_kes": None,
                "quantity": None,
                "quantity_unit": None,
                "source_file": path.name,
            })
    wb.close()
    df = pd.DataFrame(records, columns=CANONICAL_COLUMNS[:-1])
    df["file_hash"] = _hash(path)
    return df


def parse_file(path: Path, source: str) -> pd.DataFrame:
    return parse_kra(path) if source == "kra" else parse_itc(path)
