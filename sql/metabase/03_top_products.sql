-- Export product composition (KEPROBA HS groups), current vs previous period.
WITH vals AS (
    SELECT group_code, group_label,
           SUM(value_kes) FILTER (WHERE period_year = {{year}}) / 1e9 AS current_ksh_b,
           SUM(value_kes) FILTER (WHERE period_year = {{prev_year}}) / 1e9 AS previous_ksh_b
    FROM trade.fact_trade_flow
    WHERE source_system = 'KRA' AND flow = 'Exports'
      AND period_year IN ({{year}}, {{prev_year}})
      AND period_month BETWEEN {{month_start}} AND {{month_end}}
    GROUP BY group_code, group_label
)
SELECT group_code, group_label, current_ksh_b, previous_ksh_b,
       current_ksh_b - previous_ksh_b AS change_ksh_b,
       current_ksh_b / NULLIF(previous_ksh_b, 0) - 1 AS change_pct,
       current_ksh_b / NULLIF(SUM(current_ksh_b) OVER (), 0) AS share_of_exports
FROM vals
ORDER BY current_ksh_b DESC
LIMIT 25;
