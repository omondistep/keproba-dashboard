-- concentration: HHI and top-10 shares (reported in the COMESA analysis).
WITH shares AS (
    SELECT 'Destination' AS dimension, partner AS item, SUM(value_kes) AS v
    FROM trade.fact_trade_flow
    WHERE source_system = 'KRA' AND flow = 'Exports' AND is_country
      AND period_year = {{year}} AND period_month BETWEEN {{month_start}} AND {{month_end}}
    GROUP BY partner
    UNION ALL
    SELECT 'Product', group_label, SUM(value_kes)
    FROM trade.fact_trade_flow
    WHERE source_system = 'KRA' AND flow = 'Exports'
      AND period_year = {{year}} AND period_month BETWEEN {{month_start}} AND {{month_end}}
    GROUP BY group_label
), ranked AS (
    SELECT *, v / NULLIF(SUM(v) OVER (PARTITION BY dimension), 0) AS s,
           ROW_NUMBER() OVER (PARTITION BY dimension ORDER BY v DESC) AS r
    FROM shares
)
SELECT dimension,
       SUM(s * s) AS hhi,
       SUM(CASE WHEN r <= 10 THEN s ELSE 0 END) AS top10_share,
       COUNT(*) AS item_count,
       1 / NULLIF(SUM(s * s), 0) AS effective_items_inverse_hhi
FROM ranked
GROUP BY dimension;
