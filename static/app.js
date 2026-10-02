const $ = s => document.querySelector(s);
const S = {asset: null, expiry: null, depth: 5, page: 'chain', mode: 'live', metric: 'vega',
           timeline: [], timer: null, chart: null, liveSeries: [], seq: 0};
const DEPTHS = [1, 2, 3, 5, 7, 10, 15, 20];

const fmt = (v, d = 2) => v == null ? '–' : Number(v).toLocaleString('en-IN', {minimumFractionDigits: d, maximumFractionDigits: d});
const fmtInt = v => v == null ? '–' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: 0});
const sign = v => v > 0 ? 'up' : v < 0 ? 'dn' : '';
const hhmm = ms => new Date(ms).toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata'});
const expLabel = e => `${e.slice(6)}-${e.slice(4, 6)}-${e.slice(0, 4)}`;

async function api(path, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''));
  const r = await fetch(`/api/${path}?${q}`);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}
function showError(e) { const el = $('#error'); el.hidden = !e; el.textContent = e ? (e.message || e) : ''; }
function status(t) { $('#status').textContent = t; }

// ---------------------------------------------------------------- setup
async function init() {
  const a = await api('assets');
  $('#mockBadge').hidden = !a.mock;
  $('#assets').innerHTML = a.assets.map(x => `<button data-a="${x.id}">${x.label}</button>`).join('');
  $('#assets').onclick = e => e.target.dataset.a && selectAsset(e.target.dataset.a);
  $('#depth').innerHTML = DEPTHS.map(d => `<option ${d === S.depth ? 'selected' : ''}>${d}</option>`).join('');
  $('#depth').onchange = e => { S.depth = +e.target.value; S.liveSeries = []; refresh(); };
  $('#expiry').onchange = e => { S.expiry = e.target.value; S.liveSeries = []; refresh(); };
  document.querySelectorAll('.tab').forEach(b => b.onclick = () => setPage(b.dataset.page));
  $('#mode').onclick = e => e.target.dataset.mode && setMode(e.target.dataset.mode);
  $('#metric').onclick = e => { if (e.target.dataset.m) { S.metric = e.target.dataset.m;
    document.querySelectorAll('#metric button').forEach(b => b.classList.toggle('active', b === e.target)); drawChart(); } };
  $('#changeDirection').onchange = () => {
    $('#changeFormula').textContent = $('#changeDirection').value === 'opening-current' ? '1 − 2' : '2 − 1';
    if (S.mode === 'hist' && S.page === 'greeks' && S.histSelected) {
      renderGreeks(S.histOpen, S.histSelected, S.histChange, 'Historical · ' + S.histDate);
    }
    drawChart();
  };
  $('#load').onclick = () => loadHist();
  $('#histTime').onchange = () => { if (S.mode === 'hist' && S.timeline.length) loadHist(); };
  $('#day').onchange = () => { if (S.mode === 'hist') loadHist(); };
  document.querySelectorAll('[data-jump]').forEach(b => b.onclick = () => jumpHist(+b.dataset.jump));
  const y = new Date(); y.setDate(y.getDate() - 1);
  $('#day').value = `${y.getFullYear()}-${String(y.getMonth()+1).padStart(2,'0')}-${String(y.getDate()).padStart(2,'0')}`;
  selectAsset(a.assets[0].id);
}

async function selectAsset(id) {
  S.asset = id; S.liveSeries = []; S.timeline = [];
  document.querySelectorAll('#assets button').forEach(b => b.classList.toggle('active', b.dataset.a === id));
  try {
    const ex = await api('expiries', {asset: id});
    $('#expiry').innerHTML = ex.map(e => `<option value="${e}">${expLabel(e)}</option>`).join('');
    S.expiry = ex[0]; showError(null);
  } catch (e) { showError(e); return; }
  refresh();
}
function setPage(p) {
  S.page = p;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.page === p));
  $('#page-chain').hidden = p !== 'chain'; $('#page-greeks').hidden = p !== 'greeks';
  refresh();
}
function setMode(m) {
  S.mode = m;
  document.querySelectorAll('#mode button').forEach(b => b.classList.toggle('active', b.dataset.mode === m));
  $('#histControls').hidden = m !== 'hist';
  refresh();
}
function jumpHist(minutes) {
  const [h, m] = ($('#histTime').value || '09:15').split(':').map(Number);
  const next = new Date(2000, 0, 1, h, m + minutes);
  $('#histTime').value = `${String(next.getHours()).padStart(2,'0')}:${String(next.getMinutes()).padStart(2,'0')}`;
  loadHist();
}

// ---------------------------------------------------------------- data loading
function refresh() {
  clearInterval(S.timer);
  if (S.mode === 'live') { loadLive(); S.timer = setInterval(loadLive, 5000); }
  else { status('Pick a date and press Load'); }
}

async function loadLive() {
  const my = ++S.seq;
  try {
    if (S.page === 'chain') {
      const ch = await api('chain/live', {asset: S.asset, expiry: S.expiry});
      if (my !== S.seq) return;
      renderChain(ch, 'Live'); status('Updated ' + new Date().toLocaleTimeString());
    } else {
      const g = await api('greeks/live', {asset: S.asset, expiry: S.expiry, depth: S.depth});
      if (my !== S.seq) return;
      renderGreeks(g.open, g.current, g.change, 'Live');
      S.liveSeries.push({t: g.current.ts, ...flat(g.change)}); S.liveSeries = S.liveSeries.slice(-500);
      drawChart(); status('Updated ' + new Date().toLocaleTimeString());
    }
    showError(null);
  } catch (e) { showError(e); }
}

async function loadHist() {
  const day = $('#day').value; if (!day) return;
  const params = {asset: S.asset, expiry: S.expiry, day, depth: S.depth, interval: $('#interval').value};
  if ($('#histTime').value) params.time = $('#histTime').value;
  const my = ++S.seq;
  status('Loading historical data…');
  try {
    const h = await api('historical', params);
    if (my !== S.seq || S.mode !== 'hist') return;
    S.timeline = h.timeline; S.histSeries = h.series;
    S.histOpen = h.open; S.histSelected = h.selected; S.histChange = h.change; S.histDate = h.date;
    $('#histTime').value = hhmm(h.selected.ts);
    if (S.page === 'chain') renderChain({...h.chain, expiry: h.expiry}, 'Historical · ' + h.date);
    else { renderGreeks(h.open, h.selected, h.change, 'Historical · ' + h.date); drawChart(); }
    showError(null); status(`${h.timeline.length} candles · selected ${hhmm(h.selected.ts)} IST`);
  } catch (e) { if (my === S.seq) { showError(e); status(''); } }
}

// ---------------------------------------------------------------- option chain
function renderChain(ch, label) {
  $('#chainSummary').innerHTML = `<div>${label}</div><div>Spot <b>${fmt(ch.spot)}</b></div><div>ATM <b>${fmt(ch.atm, 0)}</b></div><div>Expiry <b>${expLabel(String(ch.expiry))}</b></div>` +
    (ch.ts ? `<div>As of <b>${hhmm(ch.ts)} IST</b></div>` : '');
  const stats = {};
  for (const metric of ['oi', 'vol', 'oi_chg']) {
    stats[metric] = {};
    for (const side of ['ce', 'pe']) {
      const values = ch.rows.map(r => r[side]?.[metric])
        .filter(v => Number.isFinite(v)).map(v => Math.abs(v));
      const levels = [...new Set(values.filter(v => v > 0))].sort((a, b) => b - a);
      stats[metric][side] = {max: levels[0] || 0, second: levels[1] || 0};
    }
  }
  const sideLabel = side => side === 'ce' ? 'CE' : 'PE';
  const metricCell = (metric, leg, side, strike) => {
    const raw = leg?.[metric], {max, second} = stats[metric][side];
    const magnitude = Number.isFinite(raw) ? Math.abs(raw) : 0;
    const pct = max ? Math.round(magnitude / max * 100) : 0;
    const rank = magnitude && magnitude === max ? 'rank-high' : magnitude && magnitude === second ? 'rank-second' : '';
    const bar = side === 'ce' ? 'rgba(239,91,91,.25)' : 'rgba(47,191,113,.25)';
    const value = raw == null ? '–' : metric === 'oi' || metric === 'vol' ? fmtInt(raw) : `${fmt(raw, 1)}%`;
    const pctText = raw == null ? '' : `<small class="metricPct">${pct}%</small>`;
    return `<td class="metricBar ${rank}" title="${sideLabel(side)} ${strike} ${metric}: ${pct}% of highest" style="--bar:${bar};--bar-width:${pct}%"><span>${value}</span>${pctText}</td>`;
  };
  const cols = (l, side, strike) => [
    metricCell('oi_chg', l, side, strike),
    metricCell('vol', l, side, strike), `<td>${fmt(l?.iv, 1)}</td>`,
    `<td>${fmt(l?.delta, 3)}</td>`, `<td>${fmt(l?.theta, 2)}</td>`, `<td>${fmt(l?.vega, 2)}</td>`,
    `<td><b>${fmt(l?.ltp)}</b></td>`];
  const head = ['OI', 'OI chg', 'Volume', 'IV', 'Delta', 'Theta', 'Vega', 'LTP'];
  let h = `<tr><th colspan="8" style="text-align:center">CALLS (CE)</th><th class="strike">Strike</th><th colspan="8" style="text-align:center">PUTS (PE)</th></tr>
    <tr>${head.map(x => `<th>${x}</th>`).join('')}<th class="strike"></th>${[...head].reverse().map(x => `<th>${x}</th>`).join('')}</tr>`;
  for (const r of ch.rows) {
    const atm = r.strike === ch.atm;
    const cls = atm ? 'atm' : r.strike < ch.spot ? 'ce-itm' : 'pe-itm';
    const ce = [metricCell('oi', r.ce, 'ce', r.strike), ...cols(r.ce, 'ce', r.strike)].join('');
    const pe = [...cols(r.pe, 'pe', r.strike)].reverse().join('');   // mirrored: LTP first ... OI chg, then OI
    h += `<tr class="${cls}">${ce}<td class="strike">${fmt(r.strike, 0)}</td>${pe}${metricCell('oi', r.pe, 'pe', r.strike)}</tr>`;
  }
  $('#chainTable').innerHTML = h;
}

// ---------------------------------------------------------------- greeks tables
function gTable(el, t, isChange) {
  const sums = isChange ? t.sums : t.sums;
  const cell = v => isChange ? `<td class="${sign(v)}">${v > 0 ? '+' : ''}${fmt(v, 3)}</td>` : `<td>${fmt(v, 3)}</td>`;
  const rng = s => isChange ? '' : `<td>${s.strikes_used ? fmt(s.from_strike, 0) + ' → ' + fmt(s.to_strike, 0) : '–'}</td>`;
  el.innerHTML = `<tr><th></th><th>Delta</th><th>Theta</th><th>Vega</th>${isChange ? '' : '<th>Strikes</th>'}</tr>` +
    ['CE', 'PE'].map(s => `<tr><td>${s}</td>${cell(sums[s].delta)}${cell(sums[s].theta)}${cell(sums[s].vega)}${rng(sums[s])}</tr>`).join('');
}
function renderGreeks(open, cur, chg, label) {
  $('#t2title').textContent = label.startsWith('Live') ? 'Current' : 'Selected time';
  const reverse = $('#changeDirection').value === 'opening-current';
  const shownChange = reverse ? {
    ...chg,
    spot_change: -chg.spot_change,
    sums: Object.fromEntries(['CE', 'PE'].map(side => [side,
      Object.fromEntries(['delta', 'theta', 'vega'].map(g => [g, -chg.sums[side][g]]))]))
  } : chg;
  $('#changeFormula').textContent = reverse ? '1 − 2' : '2 − 1';
  gTable($('#t1'), open); gTable($('#t2'), cur); gTable($('#t3'), shownChange, true);
  $('#t1sub').textContent = `spot ${fmt(open.spot)} · ATM ${fmt(open.atm, 0)}`;
  $('#t2sub').textContent = `spot ${fmt(cur.spot)} · ATM ${fmt(cur.atm, 0)}`;
  $('#greekSummary').innerHTML = `<div>${label}</div><div>Depth <b>${cur.depth} strikes</b></div><div>Spot change <b class="${sign(shownChange.spot_change)}">${shownChange.spot_change > 0 ? '+' : ''}${fmt(shownChange.spot_change)}</b></div>` +
    (cur.ts ? `<div>As of <b>${hhmm(cur.ts)} IST</b></div>` : '');
  $('#baselineNote').textContent = open.source === 'first-live-snapshot'
    ? '⚠ Opening greeks could not be fetched from historical data, so the first live snapshot seen today is used as the baseline.' : '';
}

// ---------------------------------------------------------------- chart
const flat = c => ({CE_vega: c.sums.CE.vega, PE_vega: c.sums.PE.vega, CE_theta: c.sums.CE.theta,
  PE_theta: c.sums.PE.theta, CE_delta: c.sums.CE.delta, PE_delta: c.sums.PE.delta});
function drawChart() {
  if (typeof Chart === 'undefined') { $('.chartbox').textContent = 'Chart library failed to load (check internet access to cdnjs.cloudflare.com).'; return; }
  const m = S.metric;
  const direction = $('#changeDirection').value === 'opening-current' ? -1 : 1;
  const pts = S.mode === 'live' ? S.liveSeries : (S.histSeries || []).map(p => ({t: p.t,
    CE_vega: p.CE_vega_chg, PE_vega: p.PE_vega_chg, CE_theta: p.CE_theta_chg, PE_theta: p.PE_theta_chg,
    CE_delta: p.CE_delta_chg, PE_delta: p.PE_delta_chg}));
  const data = {labels: pts.map(p => hhmm(p.t)), datasets: [
    {label: `CE ${m}`, data: pts.map(p => direction * p['CE_' + m]), borderColor: '#2fbf71', pointRadius: 0, tension: .2},
    {label: `PE ${m}`, data: pts.map(p => direction * p['PE_' + m]), borderColor: '#ef5b5b', pointRadius: 0, tension: .2}]};
  if (S.chart) { S.chart.data = data; S.chart.update('none'); return; }
  S.chart = new Chart($('#chart'), {type: 'line', data, options: {maintainAspectRatio: false, animation: false,
    interaction: {mode: 'index', intersect: false}, scales: {x: {ticks: {maxTicksLimit: 10}}}}});
}
init();
