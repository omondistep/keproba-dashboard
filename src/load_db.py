"""Build dimensions from REG MAP, emit psql-ready load files, and preview dashboards."""
from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

from normalize import normalize_partner

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "data" / "canonical"
LOAD = ROOT / "data" / "load"
PREVIEW = ROOT / "data" / "preview"
FINISHED = ROOT / "sample reports and excel"

# Exclusive market segments. Verified against the published DATA MARKET sheet:
# 7 of 9 segments matched to 4 decimals on raw June data; the remaining two
# differ only due to partner-name aliases (now fixed in normalize.py).
SEGMENT_PRECEDENCE = [
    "African Growth and Opportunity Act (AGOA) - United States",
    "United Kingdom (UK-Kenya EPA)",
    "European Union (EU-27)",
    "East African Community (EAC) Customs Union",
    "Common Market for Eastern and Southern Africa (COMESA)",
    "African Continental Free Trade Area (AFCFTA)",
    "Generalized System of Preferences (GSP) Markets",
    "Bilateral Trade Agreement Partners",
]
OTHER = "Other markets"


def _finished_book() -> Path:
    hits = list(FINISHED.glob("MEAT AND HORTICULTURE*.xlsx"))
    if not hits:
        raise SystemExit("Finished Jan-Jun workbook not found")
    return hits[0]


def _split_countries(text: str) -> list[str]:
    # Two country names in REG MAP contain commas and must not be split.
    text = (str(text)
            .replace("Korea, Republic of", "Korea Republic")
            .replace("Congo, Democratic Republic of the", "Democratic Republic of the Congo"))
    return [normalize_partner(c)[0] for c in text.split(",") if c.strip()]


def read_blocs() -> tuple[pd.DataFrame, dict[str, set[str]]]:
    wb = pd.ExcelFile(_finished_book())
    df = pd.read_excel(wb, sheet_name="REG MAP")
    bloc_rows, members = [], {}
    for _, r in df.iterrows():
        market, btype = r.get("Market"), r.get("Type")
        if not isinstance(market, str) or not isinstance(btype, str):
            continue
        # NB: the sheet's headers are misleading -- "Countries" holds the count,
        # "Coverage" holds the comma-separated country list.
        coverage = str(r.get("Coverage", ""))
        if btype.lower() == "other":
            bloc_rows.append({"bloc": OTHER, "bloc_type": "other", "member_count": None, "coverage": coverage})
            continue
        try:
            count = int(r["Countries"])
        except (TypeError, ValueError):
            count = None
        bloc_rows.append({"bloc": market, "bloc_type": btype, "member_count": count, "coverage": coverage})
        members[market] = _split_countries(coverage)
    return pd.DataFrame(bloc_rows), members


def build_dimensions() -> dict[str, pd.DataFrame]:
    kra = pd.read_parquet(CANONICAL / "fact_kra.parquet")
    itc = pd.read_parquet(CANONICAL / "fact_itc.parquet")
    allrows = pd.concat([kra, itc], ignore_index=True)

    # dim_partner: preferred name + every raw spelling seen as an alias
    iso = (itc.dropna(subset=["partner_raw"])
              .groupby("partner")["partner_raw"].first().to_dict())
    partner_rows = []
    for partner, grp in allrows.groupby("partner"):
        aliases = sorted({str(v) for v in grp["partner_raw"].dropna().unique()})
        partner_rows.append({
            "partner": partner,
            "iso_code": None,  # ITC partnerCd is source-specific; kept in raw column
            "is_country": bool(grp["is_country"].iloc[0]),
            "aliases": "{" + ",".join(a.replace('"', '') for a in aliases) + "}",
        })
    dim_partner = pd.DataFrame(partner_rows)

    dim_group = (allrows[["group_code", "group_label"]].drop_duplicates()
                 .dropna(subset=["group_code"]).sort_values("group_code"))

    dim_bloc, members = read_blocs()
    # `priority` reproduces the exclusive-segment precedence verified against
    # the published DATA MARKET sheet. Lower number = higher precedence.
    bridge = pd.DataFrame([
        {"partner": p, "bloc": bloc, "segment": bloc,
         "priority": SEGMENT_PRECEDENCE.index(bloc) if bloc in SEGMENT_PRECEDENCE else 99}
        for bloc, partners in members.items() for p in partners
    ]).drop_duplicates()
    # keep only partners present in the fact data
    bridge = bridge[bridge.partner.isin(set(allrows.partner))]

    ingest = pd.DataFrame([{
        "file_hash": h, "source_file": f, "source": s,
        "status": "LOADED", "row_count": int(n), "error": None,
    } for s, df in (("KRA", kra), ("ITC", itc))
      for h, f, n in df.groupby(["file_hash", "source_file"]).size().reset_index(name="n")
        .itertuples(index=False, name=None)])

    return {
        "dim_partner": dim_partner,
        "dim_product_group": dim_group,
        "dim_bloc": dim_bloc,
        "bridge_partner_bloc": bridge,
        "ingest_log": ingest,
        "fact_trade_flow": allrows,
    }


def emit_load_files() -> None:
    LOAD.mkdir(parents=True, exist_ok=True)
    tables = build_dimensions()
    for name, df in tables.items():
        df.to_csv(LOAD / f"{name}.csv", index=False)
        print(f"  {name}: {len(df):,} rows")

    fact_cols = [
        "source_system", "flow", "period_year", "period_month", "reporter",
        "partner", "partner_raw", "is_country", "product_code", "product_label",
        "group_code", "group_label", "value_original", "currency", "value_usd",
        "value_kes", "fx_rate", "quantity", "quantity_unit", "source_file", "file_hash",
    ]
    lines = ["-- Run from project root: psql -h HOST -U USER -d keproba -f data/load/load.sql",
             "\\set ON_ERROR_STOP on", "BEGIN;"]
    for name in tables:
        cols = fact_cols if name == "fact_trade_flow" else list(tables[name].columns)
        cols_sql = ", ".join(cols)
        lines.append(f"TRUNCATE trade.{name};")
        lines.append(f"\\copy trade.{name} ({cols_sql}) FROM 'data/load/{name}.csv' WITH (FORMAT csv, HEADER true);")
    lines += ["COMMIT;"]
    (LOAD / "load.sql").write_text("\n".join(lines) + "\n")
    print(f"Wrote {LOAD.relative_to(ROOT)}/load.sql")


def build_previews() -> None:
    PREVIEW.mkdir(parents=True, exist_ok=True)
    kra = pd.read_parquet(CANONICAL / "fact_kra.parquet")
    export = kra[kra.flow == "Exports"]
    _, members = read_blocs()

    # Executive balance of payments
    bot = (kra.groupby(["period_year", "flow"])["value_kes"].sum().div(1e9)
           .unstack("flow").fillna(0).reset_index())
    bot["balance_ksh_billion"] = bot.get("Exports", 0) - bot.get("Imports", 0)
    bot.to_csv(PREVIEW / "executive_bot.csv", index=False)

    # Top destinations and top products (latest period)
    year = int(kra.period_year.max())
    cur = export[export.period_year == year]
    (cur.groupby("partner")["value_kes"].sum().div(1e9).sort_values(ascending=False)
       .head(25).rename("exports_ksh_billion").to_csv(PREVIEW / "top_destinations.csv"))
    (cur.groupby(["group_code", "group_label"])["value_kes"].sum().div(1e9)
       .sort_values(ascending=False).rename("exports_ksh_billion").to_csv(PREVIEW / "top_products.csv"))

    # Exclusive market segments (precedence rule), month 6 for validation
    m6 = cur[(cur.period_month == 6) & cur.group_code.isin(["02", "06,07,08"])]
    seg = {}
    assigned = set()
    for bloc in SEGMENT_PRECEDENCE:
        mask = m6.partner.isin(list(members[bloc])) & ~m6.partner.isin(list(assigned))
        seg[bloc] = float(m6[mask].value_kes.sum() / 1e9)
        assigned |= set(members[bloc])
    seg[OTHER] = float(m6[~m6.partner.isin(assigned)].value_kes.sum() / 1e9)
    pd.Series(seg, name="exports_ksh_billion").to_csv(PREVIEW / "market_segments_june.csv")

    # Data freshness
    fresh = (kra.groupby(["source_system", "flow"])
               .agg(latest_year=("period_year", "max"), latest_month=("period_month", "max"),
                    rows=("period_year", "size"), files=("source_file", "nunique"))
               .reset_index())
    fresh.to_csv(PREVIEW / "data_freshness.csv", index=False)
    print(f"Wrote {PREVIEW.relative_to(ROOT)}/*.csv")


if __name__ == "__main__":
    emit_load_files()
    build_previews()
