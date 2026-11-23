// KEPROBA static dashboard — all computation happens in the browser via DuckDB-WASM.
import * as duckdb from 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm';

const $ = (id) => document.getElementById(id);
let conn, db;
const charts = {};
const state = { year: 2026, prev: 2025, from: 1, to: 6, flow: 'Exports', group: '' };

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------
async function boot() {
  try {
    const manifest = await (await fetch('data/manifest.json')).json();
    $('build-stamp').textContent = `Built ${manifest.built_at} · ${manifest.rows.toLocaleString()} rows`;
    applyFiltersFromManifest(manifest);

    const bundles = duckdb.getJsDelivrBundles();
    const bundle = await duckdb.selectBundle(bundles);
    const workerURL = URL.createObjectURL(
      new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' })
    );
    db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(), new Worker(workerURL));
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    conn = await db.connect();

    for (const f of manifest.files) {
      await db.registerFileURL(f.name, new URL('data/' + f.name, location.href).href,
        duckdb.DuckDBDataProtocol.HTTP, false);
      await conn.query(`CREATE VIEW ${f.view} AS SELECT * FROM read_parquet('${f.name}')`);
    }

    renderFreshness(manifest);
    if (manifest.warning) { $('warning').textContent = manifest.warning; $('warning').hidden = false; }

    bindUI();
    await refresh();
  } catch (err) {
    $('freshness').textContent = 'Failed to load data';
    $('freshness').className = 'badge badge-stale';
    console.error(err);
    alert('Could not initialise the dashboard. See browser console for details.\n' + err);
  }
}

function applyFiltersFromManifest(m) {
  const years = [...new Set(m.years)].sort((a, b) => b - a);
  const fill = (el, vals, sel) => {
    el.innerHTML = vals.map(v => `<option value="${v}">${v}</option>`).join('');
    el.value = sel;
  };
  fill($('f-year'), years, years[0]);
  fill($('f-prev'), years, years[1] ?? years[0]);
  state.year = years[0]; state.prev = years[1] ?? years[0];
  const months = Array.from({ length: 12 }, (_, i) => i + 1);
  fill($('f-from'), months, 1);
  fill($('f-to'), months, 6);
  $('f-group').innerHTML = '<option value="">All products</option>' +
    m.groups.map(g => `<option value="${esc(g.code)}">${esc(g.label)}</option>`).join('');
}

function renderFreshness(m) {
  const f = m.freshness || {};
  const months = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const label = f.latest_year ? `${months[f.latest_month]} ${f.latest_year}` : 'unknown';
  const el = $('freshness');
  el.textContent = `Data as of ${label}`;
  el.className = 'badge ' + (f.stale ? 'badge-stale' : 'badge-ok');
  el.title = `KRA export extract: ${f.export_months || 'n/a'}`;
}

// ---------------------------------------------------------------------------
// query helpers
// ---------------------------------------------------------------------------
async function q(sql) {
  const r = await conn.query(sql);
  const names = r.schema.fields.map(f => f.name);
  return r.toArray().map(row => {
    const o = {};
    for (const k of names) {
      const v = row[k];
      // Parquet int64 columns surface as JS BigInt; normalise so comparisons
      // like `period_year === 2026` and array indexing by month behave.
      o[k] = typeof v === 'bigint' ? Number(v) : (v ?? null);
    }
    return o;
  });
}

function filt(alias = '', includeFlow = true) {
  const p = alias ? alias + '.' : '';
  let s = `${p}period_year IN (${state.year}, ${state.prev}) AND ${p}period_month BETWEEN ${state.from} AND ${state.to}`;
  if (includeFlow && state.flow) s += ` AND ${p}flow = '${state.flow}'`;
  if (state.group) s += ` AND ${p}group_code = '${state.group.replace(/'/g, "''")}'`;
  return s;
}

const num = (v) => v == null ? null : Number(v);
const fmt = (v, d = 2) => v == null ? '—' : Number(v).toLocaleString('en-KE', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v) => v == null ? '—' : (Number(v) * 100).toFixed(1) + '%';
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function table(elId, rows, cols) {
  if (!rows.length) { $(elId).innerHTML = '<p class="note">No rows in this period.</p>'; return; }
  const head = cols.map(c => `<th>${esc(c.label)}</th>`).join('');
  const body = rows.map(r => '<tr>' + cols.map(c => {
    let v = r[c.key];
    let cls = '';
    if (c.fmt === 'num') v = fmt(v);
    else if (c.fmt === 'pct') v = pct(v);
    else if (c.fmt === 'delta') { cls = Number(v) >= 0 ? 'pos' : 'neg'; v = (Number(v) >= 0 ? '+' : '') + fmt(v); }
    return `<td class="${cls}">${esc(v)}</td>`;
  }).join('') + '</tr>').join('');
  $(elId).innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function chart(id, option) {
  if (!charts[id]) charts[id] = echarts.init($(id));
  charts[id].setOption(option, true);
}
const baseBar = (extra = {}) => ({
  backgroundColor: 'transparent',
  textStyle: { fontFamily: 'inherit', fontSize: 11 },
  grid: { left: 8, right: 20, top: 10, bottom: 8, containLabel: true },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  ...extra,
});

// ---------------------------------------------------------------------------
// panel renderers
// ---------------------------------------------------------------------------
async function renderOverview() {
  const rows = await q(`
    SELECT period_year, flow, SUM(value_kes)/1e9 AS v
    FROM fact_kra WHERE ${filt('', false)} GROUP BY period_year, flow`);
  const get = (year, flow) => num(rows.find(r => r.period_year === year && r.flow === flow)?.v) || 0;
  const ex = get(state.year, 'Exports'), im = get(state.year, 'Imports');
  const pxRows = rows.filter(r => r.period_year === state.prev);
  const hasPrev = state.prev !== state.year && pxRows.length > 0;
  const px = get(state.prev, 'Exports');
  $('k-exports').textContent = fmt(ex);
  $('k-imports').textContent = fmt(im);
  $('k-balance').textContent = fmt(ex - im);
  $('k-growth').textContent = hasPrev ? pct(ex / px - 1) : 'n/a';
  $('k-growth').className = 'kpi-value ' + (!hasPrev || ex >= px ? 'pos' : 'neg');

  const monthly = await q(`
    SELECT period_month,
      SUM(value_kes) FILTER (WHERE flow='Exports')/1e9 AS ex,
      SUM(value_kes) FILTER (WHERE flow='Imports')/1e9 AS im
    FROM fact_kra WHERE ${filt('', false)} GROUP BY period_month ORDER BY period_month`);
  const m = monthly.map(r => r.period_month);
  chart('chart-monthly', baseBar({
    legend: { data: ['Exports', 'Imports'], top: 0 },
    xAxis: { type: 'category', data: m.map(x => ['', 'Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][x]) },
    yAxis: { type: 'value', name: 'KSh B' },
    series: [
      { name: 'Exports', type: 'bar', data: monthly.map(r => num(r.ex)), itemStyle: { color: '#1267a8' } },
      { name: 'Imports', type: 'bar', data: monthly.map(r => num(r.im)), itemStyle: { color: '#d9a441' } },
    ],
  }));
  chart('chart-balance', baseBar({
    xAxis: { type: 'category', data: m.map(x => ['', 'Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][x]) },
    yAxis: { type: 'value', name: 'KSh B' },
    series: [{ type: 'bar', data: monthly.map(r => num(r.ex) - num(r.im)),
      itemStyle: { color: (p) => p.value >= 0 ? '#1c9087' : '#b43a2b' } }],
  }));

  const groups = await q(`
    SELECT group_label, SUM(value_kes)/1e9 AS v
    FROM fact_kra WHERE ${filt()} GROUP BY group_label ORDER BY v DESC LIMIT 15`);
  chart('chart-groups', baseBar({
    grid: { left: 8, right: 45, top: 10, containLabel: true },
    xAxis: { type: 'value', name: 'KSh B' },
    yAxis: { type: 'category', data: groups.map(r => r.group_label).reverse(),
      axisLabel: { fontSize: 10, width: 170, overflow: 'truncate' } },
    series: [{ type: 'bar', data: groups.map(r => num(r.v)).reverse(), itemStyle: { color: '#1c9087' },
      label: { show: true, position: 'right', formatter: p => fmt(p.value, 1), fontSize: 10 } }],
  }));
}

async function renderDestinations() {
  const top = await q(`
    SELECT partner, SUM(value_kes) FILTER (WHERE period_year=${state.year})/1e9 AS cur,
           SUM(value_kes) FILTER (WHERE period_year=${state.prev})/1e9 AS prev
    FROM fact_kra WHERE ${filt()} AND is_country
    GROUP BY partner ORDER BY cur DESC LIMIT 20`);
  chart('chart-destinations', baseBar({
    grid: { left: 8, right: 45, top: 10, containLabel: true },
    xAxis: { type: 'value', name: 'KSh B' },
    yAxis: { type: 'category', data: top.map(r => r.partner).reverse(), axisLabel: { fontSize: 10 } },
    series: [{ type: 'bar', data: top.map(r => num(r.cur)).reverse(), itemStyle: { color: '#1267a8' },
      label: { show: true, position: 'right', formatter: p => fmt(p.value, 1), fontSize: 10 } }],
  }));
  const movers = top.map(r => ({ ...r, change: num(r.cur) - num(r.prev) }))
    .filter(r => Math.abs(r.change) >= 1).slice(0, 20);
  table('table-movers', movers, [
    { key: 'partner', label: 'Market' }, { key: 'prev', label: 'Prior', fmt: 'num' },
    { key: 'cur', label: 'Current', fmt: 'num' }, { key: 'change', label: 'Change', fmt: 'delta' },
  ]);
  // Concentration is computed client-side from two small aggregates.
  const destShares = (await q(`SELECT SUM(value_kes) v FROM fact_kra WHERE ${filt()} AND is_country GROUP BY partner ORDER BY v DESC`)).map(r => num(r.v));
  const prodShares = (await q(`SELECT SUM(value_kes) v FROM fact_kra WHERE ${filt()} GROUP BY group_label ORDER BY v DESC`)).map(r => num(r.v));
  const measure = (a) => { const t = a.reduce((x, y) => x + y, 0); const s = a.map(v => v / t);
    return { hhi: s.reduce((x, y) => x + y * y, 0), top10: s.slice(0, 10).reduce((x, y) => x + y, 0) }; };
  const dm = measure(destShares), pm = measure(prodShares);
  table('table-concentration', [
    { dimension: 'Destination', hhi: dm.hhi, top10: dm.top10 },
    { dimension: 'Product', hhi: pm.hhi, top10: pm.top10 },
  ], [{ key: 'dimension', label: 'Dimension' }, { key: 'hhi', label: 'HHI', fmt: 'num' },
      { key: 'top10', label: 'Top-10 share', fmt: 'pct' }]);
}

async function renderProducts() {
  const rows = await q(`
    SELECT group_code, group_label,
      SUM(value_kes) FILTER (WHERE period_year=${state.year})/1e9 AS cur,
      SUM(value_kes) FILTER (WHERE period_year=${state.prev})/1e9 AS prev
    FROM fact_kra WHERE ${filt()} GROUP BY group_code, group_label ORDER BY cur DESC LIMIT 20`);
  chart('chart-products', baseBar({
    grid: { left: 8, right: 50, top: 10, containLabel: true },
    xAxis: { type: 'value', name: 'KSh B' },
    yAxis: { type: 'category', data: rows.map(r => r.group_label).reverse(), axisLabel: { fontSize: 10, width: 160, overflow: 'truncate' } },
    series: [{ type: 'bar', data: rows.map(r => num(r.cur)).reverse(), itemStyle: { color: '#1c9087' },
      label: { show: true, position: 'right', formatter: p => fmt(p.value, 1), fontSize: 10 } }],
  }));
  table('table-product-movers', rows.map(r => ({ ...r, change: num(r.cur) - num(r.prev) }))
    .filter(r => Math.abs(r.change) > 0.05).slice(0, 20), [
    { key: 'group_label', label: 'Product group' }, { key: 'prev', label: 'Prior', fmt: 'num' },
    { key: 'cur', label: 'Current', fmt: 'num' }, { key: 'change', label: 'Change', fmt: 'delta' },
  ]);
  const matrix = await q(`
    SELECT partner, group_label, SUM(value_kes)/1e9 v
    FROM fact_kra WHERE ${filt()} GROUP BY partner, group_label
    ORDER BY v DESC LIMIT 15`);
  table('table-matrix', matrix, [
    { key: 'partner', label: 'Market' }, { key: 'group_label', label: 'Product group' },
    { key: 'v', label: 'KSh B', fmt: 'num' },
  ]);
}

async function renderSegments() {
  // Exclusive precedence is encoded in the bridge table's priority column.
  const rows = await q(`
    WITH tagged AS (
      SELECT f.value_kes, COALESCE(
        (SELECT b.segment FROM bridge_partner_bloc b
         WHERE b.partner=f.partner ORDER BY b.priority LIMIT 1), 'Other markets') segment
      FROM fact_kra f WHERE ${filt('f')}
    )
    SELECT segment, SUM(value_kes)/1e9 v FROM tagged GROUP BY segment ORDER BY v DESC`);
  chart('chart-segments', {
    backgroundColor: 'transparent', textStyle: { fontSize: 11 },
    tooltip: { trigger: 'item', formatter: p => `${p.name}<br/>KSh ${fmt(p.value)}B (${p.percent}%)` },
    legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', textStyle: { fontSize: 10 } },
    series: [{ type: 'pie', radius: ['35%', '68%'], center: ['38%', '50%'],
      data: rows.map(r => ({ name: r.segment, value: num(r.v) })),
      label: { formatter: '{b}: {d}%', fontSize: 10 } }],
  });
  const blocs = await q(`
    SELECT b.segment, SUM(f.value_kes)/1e9 v
    FROM bridge_partner_bloc b JOIN fact_kra f ON f.partner=b.partner
    WHERE ${filt('f')} GROUP BY b.segment ORDER BY v DESC`);
  table('table-blocs', blocs, [
    { key: 'segment', label: 'Bloc / segment' }, { key: 'v', label: 'KSh B', fmt: 'num' },
  ]);
}

async function refresh() {
  const jobs = [renderOverview(), renderDestinations(), renderProducts(), renderSegments()];
  await Promise.all(jobs);
  await renderTables();
}

async function renderTables() {
  const t = await q(`SELECT * FROM fact_kra LIMIT 1`);
  const i = await q(`SELECT * FROM fact_itc LIMIT 1`);
  const b = await q(`SELECT * FROM bridge_partner_bloc LIMIT 1`);
  table('table-tables', [
    { table: 'fact_kra', desc: 'KRA monthly KES flows', cols: Object.keys(t[0] || {}).length },
    { table: 'fact_itc', desc: 'ITC annual USD flows', cols: Object.keys(i[0] || {}).length },
    { table: 'bridge_partner_bloc', desc: 'Partner ↔ bloc membership', cols: Object.keys(b[0] || {}).length },
  ], [{ key: 'table', label: 'Table' }, { key: 'desc', label: 'Contents' }, { key: 'cols', label: 'Columns' }]);
}

// ---------------------------------------------------------------------------
// UI bindings
// ---------------------------------------------------------------------------
function bindUI() {
  document.querySelectorAll('.tab').forEach(btn => btn.onclick = () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $('panel-' + btn.dataset.tab).classList.add('active');
    Object.values(charts).forEach(c => c.resize());
  });
  for (const id of ['f-year', 'f-prev', 'f-from', 'f-to', 'f-flow', 'f-group']) {
    $(id).onchange = async () => {
      state.year = +$('f-year').value; state.prev = +$('f-prev').value;
      state.from = +$('f-from').value; state.to = +$('f-to').value;
      state.flow = $('f-flow').value; state.group = $('f-group').value;
      if (state.from > state.to) [state.from, state.to] = [state.to, state.from];
      await refresh();
    };
  }
  $('reset').onclick = () => { $('f-year').value = state.year; $('f-from').value = 1; $('f-to').value = 6;
    $('f-flow').value = 'Exports'; $('f-group').value = ''; $('f-group').onchange(); };
  $('sql-run').onclick = async () => {
    $('sql-error').hidden = true; $('sql-result').innerHTML = 'Running…';
    try {
      const rows = await q($('sql-input').value);
      if (!rows.length) { $('sql-result').innerHTML = '<p class="note">No rows returned.</p>'; return; }
      const cols = Object.keys(rows[0]).map(k => ({ key: k, label: k }));
      table('sql-result', rows.slice(0, 500), cols);
    } catch (e) { $('sql-error').textContent = String(e); $('sql-error').hidden = false; $('sql-result').innerHTML = ''; }
  };
  window.addEventListener('resize', () => Object.values(charts).forEach(c => c.resize()));
}

boot();
