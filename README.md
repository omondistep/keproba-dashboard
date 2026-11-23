# KEPROBA Export Policy Performance Dashboard

**Zero-server, $0/year.** A static interactive dashboard that runs real SQL
queries in the visitor's browser using DuckDB-WASM. No VPS, no database server,
no Metabase licence, no SSH. Hosted free on GitHub Pages.

```
inbox/*.zip  ──unzip──▶  inbox/kra/*.xls  +  inbox/itc/*.xlsx
                              │
                    src/pipeline.py ingest     (parse, normalise, archive by hash)
                              │
                    data/canonical/*.parquet   (85,857 KRA + 37,711 ITC rows)
                              │
                    src/load_db.py             (dimensions, bloc bridge, reconciliation)
                              │
                    src/build_site.py          (copies Parquet + writes manifest.json)
                              │
                    site/  ──GitHub Actions──▶  GitHub Pages  (free HTTPS)
                              │
                    browser: DuckDB-WASM reads Parquet → charts & tables
                                                           │
                                                           ▼
                     src/report.py  (on demand) ──▶ reports/*.docx
```

## Why this architecture

| Concern | Old plan (VPS) | This plan |
|---|---|---|
| Cost | ~$50–60/year | **$0** |
| Server administration | Docker, Postgres, Caddy, HTTPS, backups | **None** |
| "Real-time" | File watcher + DB reload | Push files to GitHub → auto-rebuild (~2 min) |
| Scale | Vertical | Unlimited readers (static files + browser compute) |
| Data privacy | Private | **Public** (trade statistics — you confirmed this is fine) |

## Live dashboard features

- **Overview** — balance of trade, YoY growth, monthly flows, product-group performance
- **Destinations** — top markets, >KSh 1B movers, HHI and top-10 concentration
- **Products** — top groups, higher/weaker performers, product × destination matrix
- **Market Segments** — exclusive segments pie (AGOA → UK EPA → EU → EAC → … → Other)
  plus a separate overlapping-blocs table with an explicit "do not sum" warning
- **SQL Explorer** — type any DuckDB query against `fact_kra`, `fact_itc`, and
  `bridge_partner_bloc`; results never leave the browser
- **Data-as-of badge** and a data-quality warning banner when the sample extract
  is incomplete (present for the supplied 50% export sample)

## Quarterly DOCX report generator

`src/report.py` produces a KEPROBA-style export performance report from the same
canonical data. Every figure, table, chart and narrative sentence is recomputed
from the selected period — nothing is hard-coded.

```bash
PYTHONPATH=src python3 src/report.py \
  --year 2026 --from 7 --to 9 --prev-year 2025 \
  --output reports/kenya-export-performance-jul-sep-2025-2026.docx
```

It reproduces the published report structure (cover, list of tables/figures,
trade performance, BOT, lead destinations + Table 1 + market-share pie, export
commodities + Table 2 + product-share pie, deductions and recommendations,
plus import-source and import-product annexes) with matplotlib charts and
Century Gothic styling.

**Important:** it is data-agnostic. If the prior-year KRA extract is missing, it
says so explicitly instead of reporting zero growth. It also embeds the same
data-quality warning shown on the dashboard, so an incomplete extract cannot be
published unnoticed. Drop the Jul–Sep 2026 **and** Jul–Sep 2025 KRA files into
`inbox/` and re-run ingest to produce a real comparative report.

## Reconciliation with your published workbooks

The adapter logic was verified against `MEAT AND HORTICULTURE ... JAN JUN 2026.xlsx`:

| Check | Result |
|---|---|
| Group totals (meat + horticulture) vs `DATA GROUP` | Imports & June exports **exact (1.0000)** |
| Exports months 1, 3, 4, 5 | **0.5000** — supplied extract is a 50% sample |
| February exports | Missing entirely |
| All 9 market segments (`DATA MARKET`, June 2026) | **exact to 6 decimal places** |

The dashboard surfaces this as a warning — do not publish figures until a complete
KRA export extract is supplied.

## Raw source formats

- **KRA**: `Year | Month | Destin/Origin | Name | HS_C | SITC_C | SHORT_DESC | Net Wt | Quantity | UNIT | CIF Value` — legacy `.xls`, 8-digit HS, monthly, KES.
- **ITC**: `reporterCd | reporterLabel | partnerCd | partnerLabel | productCd | productLabel | YYYY (USD Thousand)…` — 15 `.xlsx` files, annual, wide, USD.

KRA values are KES; ITC values are USD and are never mixed without an explicit FX rate.

## Run locally

```bash
pip install -r requirements.txt
PYTHONPATH=src python3 src/pipeline.py ingest
PYTHONPATH=src python3 src/pipeline.py reconcile
PYTHONPATH=src python3 src/load_db.py
PYTHONPATH=src python3 src/build_site.py
PYTHONPATH=src python3 tests/validate_site.py
cd site && python3 -m http.server 8000
# open http://localhost:8000
```

## Deploy (one-time, ~5 minutes)

1. Create a **public** GitHub repository and push this folder to `main`.
2. Repo → **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. That's it. Every push to `main` triggers `.github/workflows/deploy.yml`, which
   re-ingests anything in `inbox/`, rebuilds the site, and publishes it.

To update data later: unzip new downloads into `inbox/kra/` or `inbox/itc/`,
commit and push. The workflow archives files by SHA-256 hash so unchanged files
are skipped, and publishes a fresh "Data as of" badge automatically.

## Cost

GitHub Pages: free (100 GB bandwidth/month, 1 GB site) · DuckDB-WASM & ECharts
CDNs: free · Domain: optional ~$10/year if you want a custom one.
**Total: $0/year, or ~$10 with a custom domain — well within the $200 budget.**

## Limitations

- All data is public — anyone with the URL can download the Parquet files.
- "Near-real-time" = triggered on file push (~2 min), not streaming.
- Large datasets (hundreds of MB) should move to a server-side engine; 123k rows
  is comfortably within browser capacity.
- The Postgres/Metabase SQL and bootstrap files in `sql/` and `metabase/` are
  kept as an optional upgrade path if you later need private or role-based access.
