-- Higher/weaker performing products (report §4 table).
WITH vals AS (
    SELECT group_code, group_label,
           SUM(value_kes) FILTER (WHERE period_year = {{year}}) / 1e9 AS current_ksh_b,
           SUM(value_kes) FILTER (WHERE period_year = {{prev_year}}) / 1e9 AS previous_ksh_b
    FROM trade.fact_trade_flow
    WHERE source_system = 'KRA' AND flow = 'Exports'
      AND period_year IN ({{year}}, {{prev_year}})
      AND period_month BETWEEN {{month_start}} AND {{month_end}}
    GROUP BY group_code, group_label
), delta AS (
    SELECT *, current_ksh_b - previous_ksh_b AS change_ksh_b FROM vals
)
SELECT CASE WHEN change_ksh_b > 0 THEN 'Higher performing' ELSE 'Weaker performing' END AS performance,
       group_label, previous_ksh_b, current_ksh_b, change_ksh_b,
       change_ksh_b / NULLIF(previous_ksh_b, 0) AS change_pct
FROM delta
WHERE ABS(change_ksh_b) >= {{threshold_ksh_b}}
ORDER BY ABS(change_ksh_b) DESC;
