-- Product x destination drill-down (mirrors XTAB EXP in the workbooks).
SELECT partner, group_label, SUM(value_kes) / 1e9 AS exports_ksh_b
FROM trade.fact_trade_flow
WHERE source_system = 'KRA' AND flow = 'Exports'
  AND period_year = {{year}}
  AND period_month BETWEEN {{month_start}} AND {{month_end}}
GROUP BY partner, group_label
HAVING SUM(value_kes) / 1e9 >= 0.01
ORDER BY exports_ksh_b DESC;
