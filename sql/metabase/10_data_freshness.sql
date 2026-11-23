-- Data freshness shown as a badge on every dashboard.
SELECT source_system, flow,
       MAX(period_year) AS latest_year,
       MAX(period_month) AS latest_month,
       COUNT(*) AS rows_loaded,
       COUNT(DISTINCT source_file) AS files,
       MAX(loaded_at) AS last_load
FROM trade.fact_trade_flow
GROUP BY source_system, flow
ORDER BY source_system, flow;
