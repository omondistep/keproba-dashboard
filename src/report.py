"""Generate the KEPROBA quarterly export-performance DOCX report.

Data-agnostic: point it at any year/month range present in the canonical KRA
Parquet and it recomputes every figure, table, chart and narrative sentence.
When prior-year KRA data has not been supplied, comparisons are omitted rather
than reported as zero, and a data-quality banner is inserted.

Usage
-----
    PYTHONPATH=src python3 src/report.py \
        --year 2026 --from 7 --to 9 --prev-year 2025 \
        --output "reports/kenya-export-performance-jul-sep-2025-2026.docx"
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "data" / "canonical"
MANIFEST = ROOT / "site" / "data" / "manifest.json"
RECONCILIATION = ROOT / "data" / "reconciliation_report.csv"

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
SHORT = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COLORS = ["#1267a8", "#d9a441", "#1c9087", "#b43a2b", "#6d5ba3",
          "#4a7c59", "#c76b8e", "#4d6d9a", "#a8863c", "#5f8b93"]
NAVY = RGBColor(0x0B, 0x2D, 0x4D)


# ---------------------------------------------------------------------------
# data helpers
# ---------------------------------------------------------------------------
def load_kra() -> pd.DataFrame:
    p = CANONICAL / "fact_kra.parquet"
    if not p.exists():
        raise SystemExit("Missing canonical data — run `src/pipeline.py ingest` first")
    return pd.read_parquet(p)


def period(df: pd.DataFrame, year: int | None, lo: int, hi: int, flow: str | None = None) -> pd.DataFrame:
    out = df[df.period_month.between(lo, hi)]
    if year is not None:
        out = out[out.period_year == year]
    if flow:
        out = out[out.flow == flow]
    return out


def total_b(df: pd.DataFrame) -> float:
    return float(df.value_kes.sum()) / 1e9


def by_key(df: pd.DataFrame, key: str, limit: int | None = None) -> pd.DataFrame:
    """Aggregate to KSh billions, ranked by the current period."""
    g = (df.groupby(key, dropna=False).value_kes.sum() / 1e9)
    g = g[g > 0].sort_values(ascending=False)
    return g.head(limit).reset_index().rename(columns={key: "item", "value_kes": "kes_b"})


def monthly_totals(df: pd.DataFrame, lo: int, hi: int) -> pd.DataFrame:
    rows = []
    for m in range(lo, hi + 1):
        sl = df[df.period_month == m]
        rows.append({
            "month": SHORT[m],
            "Exports": total_b(sl[sl.flow == "Exports"]),
            "Imports": total_b(sl[sl.flow == "Imports"]),
        })
    return pd.DataFrame(rows)


def comparison_table(cur: pd.DataFrame, prev: pd.DataFrame | None, key: str,
                     lo: int, hi: int, limit: int = 25, label: str = "item") -> pd.DataFrame:
    """Monthly split + prior/current totals + change, mirroring the workbook."""
    rows = []
    for r in by_key(cur, key, limit).itertuples():
        row = {label: r.item}
        for m in range(lo, hi + 1):
            row[SHORT[m]] = total_b(cur[(cur[key] == r.item) & (cur.period_month == m)])
        row["Current"] = r.kes_b
        if prev is not None:
            p = total_b(prev[prev[key] == r.item])
            row["Prior"] = p
            row["Change"] = r.kes_b - p
            row["%"] = (r.kes_b / p - 1) if p > 0 else None
        rows.append(row)
    return pd.DataFrame(rows)


def data_quality_warning() -> str | None:
    if MANIFEST.exists():
        m = json.loads(MANIFEST.read_text())
        if m.get("warning"):
            return m["warning"]
    if RECONCILIATION.exists():
        r = pd.read_csv(RECONCILIATION)
        half = r[(r.Side == "Exports") & (r.ratio.round(4) == 0.5)]
        if not half.empty:
            months = ", ".join(f"month {m}" for m in sorted(half.Month.unique()))
            return (f"The supplied KRA export extract is a 50% sample for {months}. "
                    "Figures are indicative only — request the complete extract before publication.")
    return None


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------
def pie_chart(items: pd.DataFrame, title: str, path: Path) -> None:
    if items.empty:
        fig, ax = plt.subplots(figsize=(8, 5.2))
        ax.text(0.5, 0.5, "No data for this period", ha="center", va="center")
        ax.set_title(title, fontsize=11, fontweight="bold", color="#0b2d4d")
        fig.savefig(path, dpi=170, bbox_inches="tight")
        plt.close(fig)
        return
    vals = items.head(10).copy()
    if len(items) > 10:
        other = float(items.kes_b.iloc[10:].sum())
        vals = pd.concat([vals, pd.DataFrame([{"item": "Other", "kes_b": other}])], ignore_index=True)
    fig, ax = plt.subplots(figsize=(8, 5.2))
    wedges, _labels, autotexts = ax.pie(
        vals.kes_b, colors=COLORS[:len(vals)], startangle=140,
        autopct=lambda p: f"{p:.1f}%", pctdistance=0.78,
        wedgeprops={"edgecolor": "white", "linewidth": 0.8},
        textprops={"fontsize": 8},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontweight("bold")
    ax.legend(wedges, [f"{i} — KSh {v:.1f}B" for i, v in zip(vals.item, vals.kes_b)],
              loc="center left", bbox_to_anchor=(1, 0.5), fontsize=7.5, frameon=False)
    ax.set_title(title, fontsize=11, fontweight="bold", color="#0b2d4d", pad=12)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def balance_chart(bot: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.4))
    x = range(len(bot))
    ax.bar([i - 0.18 for i in x], bot.Exports, width=0.36, label="Exports", color="#1267a8")
    ax.bar([i + 0.18 for i in x], bot.Imports, width=0.36, label="Imports", color="#d9a441")
    ax.set_xticks(list(x), bot.month, fontsize=8)
    ax.set_ylabel("KSh billion", fontsize=8)
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# DOCX helpers
# ---------------------------------------------------------------------------
def setup_document() -> Document:
    d = Document()
    s = d.sections[0]
    s.page_width, s.page_height = Inches(8.5), Inches(11)
    s.left_margin = s.right_margin = s.top_margin = s.bottom_margin = Inches(1)
    normal = d.styles["Normal"]
    normal.font.name = "Century Gothic"
    normal.font.size = Pt(11)
    for name, size in [("Heading 1", 14), ("Heading 2", 12)]:
        st = d.styles[name]
        st.font.name = "Century Gothic"
        st.font.size = Pt(size)
        st.font.color.rgb = NAVY
    return d


def para(d: Document, text: str, *, bold=False, size=None, align=None, style=None, color=None):
    p = d.add_paragraph(style=style)
    r = p.add_run(text)
    r.bold = bold
    if size:
        r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    if align is not None:
        p.alignment = align
    return p


def source(d: Document) -> None:
    para(d, "Source: KNBS and KRA Database; Compiled by KEPROBA", size=8)


def add_table(d: Document, df: pd.DataFrame, widths: list[float] | None = None,
              number_cols: set[str] | None = None) -> None:
    """Add a compact, styled table. Values in number_cols are formatted."""
    number_cols = number_cols or set()
    t = d.add_table(rows=1, cols=len(df.columns))
    t.style = "Table Grid"
    t.autofit = True
    for i, c in enumerate(df.columns):
        cell = t.rows[0].cells[i]
        cell.text = str(c)
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(7.5)
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _shade(cell, "0B2D4D")
    for rec in df.to_dict("records"):
        cells = t.add_row().cells
        for i, c in enumerate(df.columns):
            v = rec[c]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                s = "—"
            elif c in number_cols and isinstance(v, (int, float)):
                s = f"{v:,.2f}"
            elif c == "%":
                s = "—" if v is None or pd.isna(v) else f"{v * 100:+.1f}%"
            elif isinstance(v, float):
                s = f"{v:,.2f}"
            else:
                s = str(v)
            cells[i].text = s
            for p in cells[i].paragraphs:
                for r in p.runs:
                    r.font.size = Pt(7.5)
                if i > 0:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if widths:
        for row in t.rows:
            for cell, w in zip(row.cells, widths):
                cell.width = Inches(w)
    d.add_paragraph()


def _shade(cell, hex_color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def signed(v: float | None) -> str:
    return "—" if v is None or pd.isna(v) else f"{v:+,.1f}"


def pcts(v: float | None) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:+.1f}%"


# ---------------------------------------------------------------------------
# main report builder
# ---------------------------------------------------------------------------
def build_report(year: int, lo: int, hi: int, prev_year: int | None, output: Path) -> None:
    df = load_kra()
    years = sorted(df.period_year.unique().tolist())
    if year not in years:
        raise SystemExit(f"Year {year} not in canonical data — available: {years}")
    if prev_year is not None and prev_year not in years:
        prev_year = None  # never report a comparison as zero

    cur_all = period(df, year, lo, hi)
    if cur_all.empty:
        available = sorted(df[df.period_year == year].period_month.unique().tolist())
        raise SystemExit(
            f"No KRA rows for {SHORT[lo]}-{SHORT[hi]} {year}. "
            f"Months available that year: {available}. "
            "Drop the correct extract into inbox/ and re-run `src/pipeline.py ingest`."
        )
    prev_all = period(df, prev_year, lo, hi) if prev_year else None
    cur_x = cur_all[cur_all.flow == "Exports"]
    cur_m = cur_all[cur_all.flow == "Imports"]
    prev_x = prev_all[prev_all.flow == "Exports"] if prev_all is not None else None
    prev_m = prev_all[prev_all.flow == "Imports"] if prev_all is not None else None

    ex, im = total_b(cur_x), total_b(cur_m)
    px = total_b(prev_x) if prev_x is not None else None
    pm = total_b(prev_m) if prev_m is not None else None
    growth = (ex / px - 1) if px else None
    imgrowth = (im / pm - 1) if pm else None
    bal, pbal = ex - im, ((px - pm) if px is not None and pm is not None else None)

    plabel = f"{SHORT[lo]}-{SHORT[hi]}"
    plong = f"{MONTHS[lo].upper()}-{MONTHS[hi].upper()}"
    cmp_years = f"{prev_year}-{year}" if prev_year else str(year)
    heading_period = f"{plabel} {cmp_years}"

    # Aggregations -----------------------------------------------------------
    destinations = comparison_table(cur_x, prev_x, "partner", lo, hi, 25, "Destination")
    products = comparison_table(cur_x, prev_x, "group_label", lo, hi, 25, "Product")
    suppliers = comparison_table(cur_m, prev_m, "partner", lo, hi, 25, "Source")
    import_products = comparison_table(cur_m, prev_m, "group_label", lo, hi, 25, "Product")
    bot = monthly_totals(df[(df.period_year == year)], lo, hi)
    market_shares = by_key(cur_x, "partner")
    product_shares = by_key(cur_x, "group_label")

    def movers(tbl: pd.DataFrame, name: str, threshold: float = 1.0) -> pd.DataFrame:
        if "Change" not in tbl:
            return pd.DataFrame([{name: "Prior-period data not supplied", "KSh B": "—"}])
        t = tbl.rename(columns={tbl.columns[0]: name}).copy()
        t["KSh B"] = t["Change"]
        t = t[t["KSh B"].abs() >= threshold].sort_values("KSh B", ascending=False)
        if t.empty:
            return pd.DataFrame([{name: "No markets exceeded the threshold", "KSh B": "—"}])
        return t[[name, "KSh B"]].head(20)

    movers_dest = movers(destinations, "Market")
    movers_prod = movers(products, "Product", 0.2)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        p_market, p_product, p_bot = tmp / "markets.png", tmp / "products.png", tmp / "bot.png"
        pie_chart(market_shares, f"Share of Exports by Markets, {heading_period}", p_market)
        pie_chart(product_shares, f"Share of Exports by Products, {heading_period}", p_product)
        balance_chart(bot, p_bot)

        d = setup_document()

        # Cover --------------------------------------------------------------
        for text, size in [("KENYA", 36), (f"EXPORT PERFORMANCE IN {plong} {cmp_years}", 24),
                           ("REPORT", 48)]:
            para(d, text, bold=True, size=size, align=WD_ALIGN_PARAGRAPH.CENTER)
        for _ in range(4):
            d.add_paragraph()
        for text in ["Prepared by", "KENYA EXPORT PROMOTION", "& BRANDING AGENCY"]:
            para(d, text, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        para(d, f"November {year}", align=WD_ALIGN_PARAGRAPH.CENTER)
        d.add_page_break()

        # Contents -----------------------------------------------------------
        para(d, "List of Tables", bold=True, size=13)
        for i, t in enumerate([
            f"Table 1: Top Destination Markets in {heading_period}",
            f"Table 2: Top Export Products in {heading_period}",
            "Table 3: Monthly balance of trade",
            "Table 4: Leading import sources",
        ], 1):
            para(d, t, style="List Bullet", size=9)
        para(d, "List of Figures", bold=True, size=13)
        for i, t in enumerate([
            f"Figure 1: Share of Exports by Markets, {heading_period}",
            f"Figure 2: Share of Top Exports by Products, {heading_period}",
            f"Figure 3: Monthly exports and imports, {heading_period}",
        ], 1):
            para(d, t, style="List Bullet", size=9)
        d.add_page_break()

        # Quality warning ----------------------------------------------------
        warning = data_quality_warning()
        if warning:
            w = d.add_table(rows=1, cols=1)
            w.style = "Table Grid"
            cell = w.rows[0].cells[0]
            cell.text = "DATA QUALITY WARNING — " + warning
            _shade(cell, "FFF2CC")
            for p in cell.paragraphs:
                for r in p.runs:
                    r.bold = True
                    r.font.size = Pt(9)
            d.add_paragraph()

        # 1 ------------------------------------------------------------------
        d.add_heading(f"1 KENYA'S TRADE PERFORMANCE IN {plong.upper()} ({cmp_years})", 1)
        if px is not None:
            para(d, f"Kenya's merchandise exports in {plabel} {year} were valued at KSh {ex:,.1f} billion, "
                    f"compared with KSh {px:,.1f} billion in the same period of {prev_year} — "
                    f"a change of {signed(ex - px)} billion ({pcts(growth)}).")
        else:
            para(d, f"Kenya's merchandise exports in {plabel} {year} were valued at KSh {ex:,.1f} billion. "
                    f"Prior-period KRA data was not supplied, so year-on-year comparisons are not available.")
        if pm is not None:
            para(d, f"Total imports were valued at KSh {im:,.1f} billion, compared with KSh {pm:,.1f} billion "
                    f"in {plabel} {prev_year} ({signed(im - pm)} billion, {pcts(imgrowth)}). The balance of trade "
                    f"stood at KSh {bal:,.1f} billion versus KSh {pbal:,.1f} billion in the prior period.")
        else:
            para(d, f"Total imports were valued at KSh {im:,.1f} billion, giving a balance of trade of "
                    f"KSh {bal:,.1f} billion for the period.")
        para(d, "This report provides a comparative analysis of Kenya's trade performance, examining destination "
                "markets, export commodities, the balance of trade and the policy implications of the observed shifts.")
        source(d)

        # 2 ------------------------------------------------------------------
        d.add_heading(f"2 Comparative Perspectives of Kenya's Trade in {heading_period}", 1)
        para(d, f"Table 3: Monthly balance of trade, {heading_period}", bold=True, size=9)
        add_table(d, bot.assign(Balance=bot.Exports - bot.Imports),
                  number_cols={"Exports", "Imports", "Balance"})
        source(d)
        d.add_picture(str(p_bot), width=Inches(6.4))
        para(d, f"Figure 3: Monthly exports and imports, {heading_period}", size=9)
        source(d)

        # 3 ------------------------------------------------------------------
        d.add_heading(f"3 Lead Destination Markets {heading_period}", 1)
        para(d, f"Table 1: Top Destination Markets in {heading_period}", bold=True, size=9)
        add_table(d, destinations, number_cols=set(destinations.columns) - {"Destination"})
        source(d)
        para(d, "Export markets that registered the largest changes are shown below.", bold=True, size=9)
        add_table(d, movers_dest, number_cols={"KSh B"})
        if not destinations.empty and "Change" in destinations:
            top = destinations.iloc[0]
            para(d, f"{top.Destination} remained the leading destination with exports of KSh {top.Current:,.1f} billion, "
                    f"a change of {signed(top.Change)} billion ({pcts(top['%'])}).")
        elif not destinations.empty:
            top = destinations.iloc[0]
            para(d, f"{top.Destination} was the leading destination with exports of KSh {top.Current:,.1f} billion.")
        source(d)
        d.add_heading(f"3.1 Comparative Perspective on Shares of Lead Export Markets {heading_period}", 2)
        d.add_picture(str(p_market), width=Inches(6.5))
        para(d, f"Figure 1: Share of Exports by Markets, {heading_period}", size=9)
        source(d)

        # 4 ------------------------------------------------------------------
        d.add_heading("4 Composition of Kenya's Export Commodities", 1)
        para(d, f"Table 2: Top Export Products in {heading_period}", bold=True, size=9)
        add_table(d, products, number_cols=set(products.columns) - {"Product"})
        source(d)
        para(d, "Higher and weaker performing products are highlighted below.", bold=True, size=9)
        add_table(d, movers_prod, number_cols={"KSh B"})
        source(d)
        d.add_heading(f"4.1 Share of Lead Export Products in {heading_period}", 2)
        d.add_picture(str(p_product), width=Inches(6.5))
        para(d, f"Figure 2: Share of Top Exports by Products, {heading_period}", size=9)
        source(d)

        # 5 ------------------------------------------------------------------
        d.add_heading(f"5 Deduction from the {plabel} {year} Performance", 1)
        if px is not None:
            para(d, f"Total exports changed by {signed(ex - px)} billion ({pcts(growth)}), while imports changed by "
                    f"{signed(im - pm)} billion ({pcts(imgrowth)}). The balance of trade "
                    f"{'widened' if pbal is not None and bal < pbal else 'narrowed'} to KSh {bal:,.1f} billion.")
        else:
            para(d, f"The period recorded KSh {ex:,.1f} billion in exports and KSh {im:,.1f} billion in imports, "
                    f"a deficit of KSh {abs(bal):,.1f} billion.")
        if "Change" in destinations:
            gainers = int((destinations.Change > 1).sum())
            para(d, f"{gainers} of the top {len(destinations)} export destinations recorded increases exceeding "
                    "KSh 1 billion, indicating both resilience in traditional markets and gains in emerging ones.")
        if not product_shares.empty:
            lead = product_shares.iloc[0]
            para(d, f"The leading product group, {lead['item']}, accounted for KSh {lead['kes_b']:,.1f} billion, "
                    f"or {lead['kes_b'] / max(ex, 1e-9) * 100:.1f}% of total exports in the period.")
        d.add_heading("5.1 Implication for the country", 1)
        for text in [
            "Market Intelligence — maintain the trade intelligence dashboard and commission diagnostic studies "
            "on declines in strategic markets.",
            "Diplomatic Engagement — reactivate trade dialogues with markets registering declines and align "
            "compliance efforts with priority markets.",
            "Diversification — expand into fast-growing markets and promote higher-value product lines.",
            "Trade Facilitation — streamline customs and logistics, and expand export credit and trade finance.",
        ]:
            para(d, text, style="List Bullet", size=10)

        # 6 Annexes -----------------------------------------------------------
        d.add_heading("6 Annex", 1)
        d.add_heading("Annex 1: Kenya's imports by supplying countries", 1)
        para(d, f"Table 4: Leading import sources, {heading_period}", bold=True, size=9)
        add_table(d, suppliers, number_cols=set(suppliers.columns) - {"Source"})
        source(d)
        for r in suppliers.head(5).itertuples():
            chg = signed(getattr(r, "Change", None))
            para(d, f"{r.Source} recorded imports of KSh {r.Current:,.1f} billion in the period "
                    f"(change {chg} billion).", style="List Bullet", size=10)
        d.add_heading("Annex 2: Kenya's imports by products", 1)
        add_table(d, import_products, number_cols=set(import_products.columns) - {"Product"})
        source(d)
        if not import_products.empty:
            r = import_products.iloc[0]
            para(d, f"{r['Product']} remained the leading import with KSh {r['Current']:,.1f} billion "
                    f"in {plabel} {year}.", style="List Bullet", size=10)

        output.parent.mkdir(parents=True, exist_ok=True)
        d.save(output)

    print(f"Wrote {output} ({output.stat().st_size / 1024:.0f} KB)")
    print(f"  Period: {plabel} {year}" + (f" vs {prev_year}" if prev_year else " (no prior-year data)"))
    print(f"  Exports KSh {ex:,.1f}B · Imports KSh {im:,.1f}B · Balance KSh {bal:,.1f}B")
    if warning:
        print("  WARNING:", warning)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=None, help="report year (default: latest in data)")
    ap.add_argument("--from", dest="lo", type=int, default=1, help="first month (1-12)")
    ap.add_argument("--to", dest="hi", type=int, default=12, help="last month (1-12)")
    ap.add_argument("--prev-year", type=int, default=None, help="comparison year (default: year-1)")
    ap.add_argument("--output", type=Path, default=None, help="output .docx path")
    a = ap.parse_args()

    df = load_kra()
    year = a.year or int(df.period_year.max())
    prev = a.prev_year if a.prev_year is not None else year - 1
    if a.lo < 1 or a.hi > 12 or a.lo > a.hi:
        raise SystemExit("Invalid month range — use 1 <= from <= to <= 12")
    output = a.output or ROOT / "reports" / f"kenya-export-performance-{year}-m{a.lo:02d}-m{a.hi:02d}.docx"
    build_report(year, a.lo, a.hi, prev, output)


if __name__ == "__main__":
    main()
