-- Exclusive market segments (DATA MARKET / REG EXP in the published workbook).
-- Precedence: AGOA -> UK EPA -> EU-27 -> EAC -> COMESA -> AfCFTA -> GSP -> Bilateral -> Other.
-- Verified to reproduce all 9 published June 2026 figures exactly.
WITH tagged AS (
    SELECT f.value_kes,
           CASE
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'African Growth and Opportunity Act (AGOA) - United States')
                  THEN 'African Growth and Opportunity Act (AGOA) - United States'
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'United Kingdom (UK-Kenya EPA)')
                  THEN 'United Kingdom (UK-Kenya EPA)'
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'European Union (EU-27)')
                  THEN 'European Union (EU-27)'
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'East African Community (EAC) Customs Union')
                  THEN 'East African Community (EAC) Customs Union'
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'Common Market for Eastern and Southern Africa (COMESA)')
                  THEN 'Common Market for Eastern and Southern Africa (COMESA)'
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'African Continental Free Trade Area (AFCFTA)')
                  THEN 'African Continental Free Trade Area (AFCFTA)'
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'Generalized System of Preferences (GSP) Markets')
                  THEN 'Generalized System of Preferences (GSP) Markets'
             WHEN EXISTS (SELECT 1 FROM trade.bridge_partner_bloc b
                          WHERE b.partner = f.partner AND b.bloc = 'Bilateral Trade Agreement Partners')
                  THEN 'Bilateral Trade Agreement Partners'
             ELSE 'Other markets'
           END AS segment
    FROM trade.fact_trade_flow f
    WHERE f.source_system = 'KRA' AND f.flow = 'Exports'
      AND f.period_year = {{year}}
      AND f.period_month BETWEEN {{month_start}} AND {{month_end}}
)
SELECT segment, SUM(value_kes) / 1e9 AS exports_ksh_b,
       SUM(value_kes) / 1e9 / NULLIF(SUM(SUM(value_kes)) OVER (), 0) AS share
FROM tagged
GROUP BY segment
ORDER BY exports_ksh_b DESC;
