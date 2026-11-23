-- Executive summary: exports, imports, balance and year-on-year change.
-- Variables: year (Number), prev_year (Number), month_start (Number), month_end (Number)
WITH totals AS (
    SELECT period_year,
           SUM(value_kes) FILTER (WHERE flow = 'Exports') / 1e9 AS exports_ksh_b,
           SUM(value_kes) FILTER (WHERE flow = 'Imports') / 1e9 AS imports_ksh_b
    FROM trade.fact_trade_flow
    WHERE source_system = 'KRA'
      AND period_year IN ({{year}}, {{prev_year}})
      AND period_month BETWEEN {{month_start}} AND {{month_end}}
    GROUP BY period_year
)
SELECT {{year}} AS year,
       COALESCE(c.exports_ksh_b, 0) AS exports_ksh_b,
       COALESCE(c.imports_ksh_b, 0) AS imports_ksh_b,
       COALESCE(c.exports_ksh_b, 0) - COALESCE(c.imports_ksh_b, 0) AS balance_ksh_b,
       COALESCE(c.exports_ksh_b, 0) - COALESCE(p.exports_ksh_b, 0) AS export_change_ksh_b,
       (COALESCE(c.exports_ksh_b, 0) / NULLIF(p.exports_ksh_b, 0) - 1) AS export_change_pct,
       COALESCE(c.imports_ksh_b, 0) - COALESCE(p.imports_ksh_b, 0) AS import_change_ksh_b,
       (COALESCE(c.imports_ksh_b, 0) / NULLIF(p.imports_ksh_b, 0) - 1) AS import_change_pct
FROM (SELECT 1) x
LEFT JOIN totals c ON c.period_year = {{year}}
LEFT JOIN totals p ON p.period_year = {{prev_year}};
