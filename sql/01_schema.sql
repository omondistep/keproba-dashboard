-- Canonical trade schema. Load with: psql -f sql/01_schema.sql
CREATE SCHEMA IF NOT EXISTS trade;

DROP TABLE IF EXISTS trade.fact_trade_flow CASCADE;
DROP TABLE IF EXISTS trade.bridge_partner_bloc CASCADE;
DROP TABLE IF EXISTS trade.dim_partner CASCADE;
DROP TABLE IF EXISTS trade.dim_product_group CASCADE;
DROP TABLE IF EXISTS trade.dim_bloc CASCADE;
DROP TABLE IF EXISTS trade.fx_rate CASCADE;
DROP TABLE IF EXISTS trade.ingest_log CASCADE;

CREATE TABLE trade.fact_trade_flow (
    id              BIGSERIAL PRIMARY KEY,
    source_system   TEXT NOT NULL,               -- KRA | ITC
    flow            TEXT NOT NULL,               -- Exports | Imports
    period_year     INTEGER NOT NULL,
    period_month    INTEGER,                     -- NULL for annual ITC data
    reporter        TEXT NOT NULL,
    partner         TEXT NOT NULL,
    partner_raw     TEXT,
    is_country      BOOLEAN DEFAULT TRUE,
    product_code    TEXT NOT NULL,
    product_label   TEXT,
    group_code      TEXT,
    group_label     TEXT,
    value_original  NUMERIC(20,4) NOT NULL,
    currency        TEXT NOT NULL,               -- KES | USD
    value_usd       NUMERIC(20,4),
    value_kes       NUMERIC(20,4),
    fx_rate         NUMERIC(14,8),
    quantity        NUMERIC(20,4),
    quantity_unit   TEXT,
    source_file     TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    loaded_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX fact_period_idx ON trade.fact_trade_flow (period_year, period_month, flow);
CREATE INDEX fact_partner_idx ON trade.fact_trade_flow (partner, flow);
CREATE INDEX fact_group_idx ON trade.fact_trade_flow (group_code, flow);

CREATE TABLE trade.dim_partner (
    partner       TEXT PRIMARY KEY,
    iso_code      TEXT,
    is_country    BOOLEAN DEFAULT TRUE,
    aliases       TEXT[]
);
CREATE TABLE trade.dim_product_group (
    group_code    TEXT PRIMARY KEY,
    group_label   TEXT NOT NULL,
    hs_chapters   TEXT[]
);
CREATE TABLE trade.dim_bloc (
    bloc          TEXT PRIMARY KEY,
    bloc_type     TEXT,        -- REGIONAL | PREFERENTIAL | AFRICA | BILATERAL | other
    member_count  INTEGER,
    coverage      TEXT
);
-- Countries belong to several overlapping blocs: EU-27 is inside EU-UK EPA,
-- COMESA inside AfCFTA. Never SUM across blocs without a dedup rule.
CREATE TABLE trade.bridge_partner_bloc (
    partner   TEXT REFERENCES trade.dim_partner(partner),
    bloc      TEXT REFERENCES trade.dim_bloc(bloc),
    segment   TEXT NOT NULL,
    priority  INTEGER NOT NULL DEFAULT 99,
    PRIMARY KEY (partner, bloc)
);
CREATE TABLE trade.fx_rate (
    period_year  INTEGER NOT NULL,
    period_month INTEGER NOT NULL DEFAULT 0,  -- 0 = annual
    currency     TEXT NOT NULL,
    rate_to_usd  NUMERIC(14,8) NOT NULL,
    source       TEXT,
    PRIMARY KEY (period_year, period_month, currency)
);
CREATE TABLE trade.ingest_log (
    file_hash    TEXT PRIMARY KEY,
    source_file  TEXT NOT NULL,
    source       TEXT NOT NULL,
    status       TEXT NOT NULL,
    row_count    INTEGER,
    error        TEXT,
    loaded_at    TIMESTAMPTZ DEFAULT now()
);

-- Marts shaped exactly like the published workbooks, so reports reconcile.
CREATE OR REPLACE VIEW trade.mart_group_month AS
SELECT period_year, period_month, flow, group_code, group_label,
       SUM(value_kes) / 1e9 AS value_ksh_billion,
       SUM(value_usd) / 1e6 AS value_usd_million,
       MAX(source_file) AS source_file
FROM trade.fact_trade_flow
WHERE source_system = 'KRA'
GROUP BY 1,2,3,4,5;

CREATE OR REPLACE VIEW trade.mart_partner_month AS
SELECT period_year, period_month, flow, partner,
       SUM(value_kes) / 1e9 AS value_ksh_billion
FROM trade.fact_trade_flow
WHERE source_system = 'KRA' AND is_country
GROUP BY 1,2,3,4;

CREATE OR REPLACE VIEW trade.mart_product_partner AS
SELECT period_year, flow, group_code, group_label, partner,
       SUM(value_kes) / 1e9 AS value_ksh_billion
FROM trade.fact_trade_flow
WHERE source_system = 'KRA'
GROUP BY 1,2,3,4,5;

CREATE OR REPLACE VIEW trade.mart_bot AS
SELECT period_year,
       SUM(value_kes) FILTER (WHERE flow = 'Exports') / 1e9 AS exports_ksh_billion,
       SUM(value_kes) FILTER (WHERE flow = 'Imports') / 1e9 AS imports_ksh_billion,
       (SUM(value_kes) FILTER (WHERE flow = 'Exports') -
        SUM(value_kes) FILTER (WHERE flow = 'Imports')) / 1e9 AS balance_ksh_billion
FROM trade.fact_trade_flow
WHERE source_system = 'KRA'
GROUP BY 1;
