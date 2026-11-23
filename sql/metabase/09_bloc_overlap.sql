-- Overlapping trade blocs (REG BLOC). WARNING: blocs overlap by design --
-- EAC is inside COMESA, both inside AfCFTA; do NOT sum the rows.
SELECT d.bloc, d.bloc_type, d.member_count,
       SUM(f.value_kes) / 1e9 AS exports_ksh_b
FROM trade.bridge_partner_bloc b
JOIN trade.dim_bloc d ON d.bloc = b.bloc
JOIN trade.fact_trade_flow f ON f.partner = b.partner
WHERE f.source_system = 'KRA' AND f.flow = 'Exports'
  AND f.period_year = {{year}}
  AND f.period_month BETWEEN {{month_start}} AND {{month_end}}
GROUP BY d.bloc, d.bloc_type, d.member_count
ORDER BY exports_ksh_b DESC;
