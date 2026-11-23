"""Shared normalisation rules for KRA and ITC raw trade data."""
from __future__ import annotations

import re

# KRA uses short/upper-case names; ITC uses ISO labels. Both map to these.
PARTNER_ALIASES = {
    "UAE": "UNITED ARAB EMIRATES",
    "UK": "UNITED KINGDOM",
    "USA": "UNITED STATES OF AMERICA",
    "US": "UNITED STATES OF AMERICA",
    "UNITED STATES": "UNITED STATES OF AMERICA",
    "DRC": "DEMOCRATIC REPUBLIC OF THE CONGO",
    "DEMOCRATIC REP OF CONGO": "DEMOCRATIC REPUBLIC OF THE CONGO",
    "CONGO, DEMOCRATIC REPUBLIC OF THE": "DEMOCRATIC REPUBLIC OF THE CONGO",
    "CONGO, DEM. REP.": "DEMOCRATIC REPUBLIC OF THE CONGO",
    "RUSSIAN FEDERATION": "RUSSIA",
    "CAPE VERDE ISLANDS": "CABO VERDE",
    # Published KEPROBA segment tables place Congo-Brazzaville under EAC.
    # Kept for report parity; flag as a data-quality issue for review.
    "CONGO, BRAZZAVILLE": "DEMOCRATIC REPUBLIC OF THE CONGO",
    "KOREA, REPUBLIC OF": "KOREA REPUBLIC",
    "TANZANIA, UNITED REPUBLIC OF": "TANZANIA",
    "VIET NAM": "VIETNAM",
    "TURKIYE": "TURKEY",
    "CÔTE D'IVOIRE": "COTE D'IVOIRE",
    "COTE D'IVOIRE (IVORY) COAST": "COTE D'IVOIRE",
}

# Non-country partners that appear in KRA destination/origin lists.
NON_COUNTRY = {"AIRCRAFT & SHIPSTORES", "UNSPECIFIED AREAS", "WORLD", "OTHERS"}


def normalize_partner(value) -> tuple[str, bool]:
    """Return (canonical partner name, is_country)."""
    if value is None:
        return "UNKNOWN", False
    name = re.sub(r"\s+", " ", str(value)).strip().upper()
    name = PARTNER_ALIASES.get(name, name)
    return name, name not in NON_COUNTRY


# Ordered rules: 4/6-digit HS codes are checked before 2-digit chapters.
PRODUCT_GROUPS = [
    ("0901", "Coffee"),
    ("0902", "Tea"),
    ("0603", "Cut flowers"),
    ("06,07,08", "Horticulture"),
    ("02", "Meat and edible meat offal"),
    ("27", "Mineral fuels, oils and products of their distillation"),
    ("85", "Electrical machinery and equipment"),
    ("84", "Machinery, mechanical appliances"),
    ("60", "Textile and Apparel Accessories"),
    ("61", "Textile and Apparel Accessories"),
    ("62", "Textile and Apparel Accessories"),
    ("63", "Textile and Apparel Accessories"),
    ("72", "Iron and steel"),
    ("15", "Animal or vegetable fats and oils"),
    ("87", "Vehicles other than railway rolling stock"),
    ("39", "Plastics and articles thereof"),
    ("30", "Pharmaceutical products"),
    ("10", "Cereals"),
    ("17", "Sugar and sugar confectionery"),
]


def product_group(hs_code) -> tuple[str, str]:
    """Map an HS code to a KEPROBA group code and label."""
    code = str(hs_code).strip().lstrip("'")
    code = re.sub(r"\D", "", code)
    if not code:
        return "UNKNOWN", "Unknown"
    # Multi-chapter groups are matched first (by chapter range).
    if code[:2] in ("06", "07", "08"):
        return "06,07,08", "Horticulture"
    if code[:2] in ("60", "61", "62", "63"):
        return "60-63", "Textile and Apparel Accessories"
    for prefix, label in PRODUCT_GROUPS:
        if code.startswith(prefix):
            return prefix, label
    chapter = code[:2]
    return chapter, f"Other (chapter {chapter})"


YEAR_COL_RE = re.compile(r"^(\d{4})\s*\(([^)]+)\)$")
UNIT_MULTIPLIER = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def parse_itc_year_columns(columns) -> dict[str, tuple[int, int]]:
    """Map '2025 (USD Thousand)' -> (2025, 1000) for ITC wide files."""
    out: dict[str, tuple[int, int]] = {}
    for col in columns:
        m = YEAR_COL_RE.match(str(col).strip())
        if not m:
            continue
        year, unit = int(m.group(1)), m.group(2).lower()
        multiplier = 1
        for word, mult in UNIT_MULTIPLIER.items():
            if word in unit:
                multiplier = mult
                break
        out[col] = (year, multiplier)
    return out
