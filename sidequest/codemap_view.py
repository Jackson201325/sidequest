"""One self-contained HTML page for a sidequest.codemap scan. No network, no build step."""
import json

PAGE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sidequest code map</title>
<style>
:root { --bg:#fbfbfa; --panel:#ffffff; --ink:#1f2328; --muted:#6b7280; --line:#e5e7eb; --edge:#c9ced6;
  --out:#2563eb; --in:#d97706; --bad:#dc2626; --warn:#b45309; --pick:#eef2ff; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181d; --panel:#1d2027; --ink:#e6e6e6; --muted:#9aa1ad;
  --line:#2c313a; --edge:#3a404b; --out:#60a5fa; --in:#fbbf24; --bad:#f87171; --warn:#fbbf24; --pick:#262b36; } }
* { box-sizing:border-box; }
body { margin:0; font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg);
  height:100vh; display:grid; grid-template-rows:auto 1fr; }
header { display:flex; gap:16px; align-items:center; padding:8px 14px; border-bottom:1px solid var(--line); background:var(--panel); }
header h1 { font-size:14px; margin:0; }
nav button { border:0; background:none; color:var(--muted); padding:6px 10px; border-radius:6px; cursor:pointer; font:inherit; }
nav button.on { background:var(--pick); color:var(--ink); font-weight:600; }
#stats { margin-left:auto; color:var(--muted); }
main { display:grid; grid-template-columns:240px 1fr 380px; min-height:0; }
main.wide { grid-template-columns:1fr; }
aside, section { overflow:auto; min-height:0; }
#left { border-right:1px solid var(--line); padding:10px; background:var(--panel); }
#right { border-left:1px solid var(--line); padding:12px 14px; background:var(--panel); }
input[type=search] { width:100%; padding:6px 8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--ink); font:inherit; }
.hits div, .list div { padding:3px 6px; border-radius:4px; cursor:pointer; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.hits div:hover, .list div:hover { background:var(--pick); }
.layers label { display:flex; gap:6px; align-items:center; padding:2px 0; }
.swatch { width:10px; height:10px; border-radius:2px; display:inline-block; }
h2 { font-size:14px; margin:0 0 2px; word-break:break-all; }
h3 { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:14px 0 4px; }
.muted { color:var(--muted); }
.tag { display:inline-block; font-size:10px; padding:0 5px; border-radius:8px; border:1px solid var(--line); margin-left:4px; color:var(--muted); }
.tag.w { color:var(--bad); border-color:var(--bad); } .tag.c { color:var(--out); border-color:var(--out); }
.tag.p { color:var(--warn); border-color:var(--warn); }
a { color:var(--out); cursor:pointer; text-decoration:none; } a:hover { text-decoration:underline; }
svg { width:100%; height:100%; display:block; cursor:grab; }
svg text { font-size:11px; fill:var(--ink); pointer-events:none; }
svg .col { font-size:11px; font-weight:600; fill:var(--muted); text-transform:uppercase; }
.box rect { fill:var(--panel); stroke:var(--line); rx:4; cursor:pointer; }
.box.sel rect { stroke:var(--ink); stroke-width:2; }
.box.out rect { stroke:var(--out); stroke-width:2; } .box.in rect { stroke:var(--in); stroke-width:2; }
.box.dim { opacity:.25; }
path.e { fill:none; stroke:var(--edge); stroke-width:1; }
path.e.out { stroke:var(--out); stroke-width:1.6; } path.e.in { stroke:var(--in); stroke-width:1.6; } path.e.dim { opacity:.08; }
table { border-collapse:collapse; width:100%; } td, th { text-align:left; padding:4px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:11px; text-transform:uppercase; }
.page { padding:16px 20px; max-width:1100px; }
.bad { color:var(--bad); } .warn { color:var(--warn); }
.legend { color:var(--muted); font-size:12px; margin-top:12px; }
</style>
</head>
<body>
<header><h1>Sidequest code map</h1>
<nav><button data-tab="map" class="on">Map</button><button data-tab="config">Config</button>
<button data-tab="writes">File writes</button><button data-tab="programs">Programs</button></nav>
<span id="stats"></span></header>
<main id="main">
<aside id="left">
  <input id="q" type="search" placeholder="Find module or function…" autocomplete="off">
  <div id="hits" class="hits"></div>
  <h3>Layers</h3><div id="layers" class="layers"></div>
  <div class="legend"><div><span class="swatch" style="background:var(--out)"></span> uses (calls, imports, runs)</div>
  <div><span class="swatch" style="background:var(--in)"></span> used by</div>
  <div style="margin-top:6px">Tags: <span class="tag w">W</span> writes files <span class="tag c">C</span> reads config
  <span class="tag p">P</span> runs programs</div><div style="margin-top:6px">Drag to pan, scroll to zoom.</div></div>
</aside>
<section id="center"></section>
<aside id="right"><p class="muted">Click a module box or search for a function.</p></aside>
</main>
<script>
const DATA = __DATA__;
const COLORS = {entry:'#7c3aed', ui:'#db2777', workspace:'#0891b2', core:'#16a34a', services:'#ea580c', storage:'#ca8a04', config:'#2563eb', tests:'#6b7280'};
const fn = new Map(DATA.functions.map(f => [f.id, f]));
const mod = new Map(DATA.modules.map(m => [m.id, m]));
const callers = new Map();
for (const f of DATA.functions) for (const c of f.calls) { if (!callers.has(c)) callers.set(c, []); callers.get(c).push(f.id); }
const deps = new Map(DATA.modules.map(m => [m.id, new Map()]));
function dep(a, b, kind) { if (a === b || !deps.has(a) || !mod.has(b)) return; const k = deps.get(a); k.set(b, (k.get(b) || new Set()).add(kind)); }
for (const [a, b] of DATA.imports) dep(a, b, 'imports');
for (const f of DATA.functions) { for (const c of f.calls) dep(f.module, fn.get(c).module, 'calls'); for (const r of f.runs) dep(f.module, r, 'runs'); }
const usedBy = new Map(DATA.modules.map(m => [m.id, new Map()]));
for (const [a, k] of deps) for (const [b, kinds] of k) usedBy.get(b).set(a, kinds);
const byModule = new Map(DATA.modules.map(m => [m.id, DATA.functions.filter(f => f.module === m.id)]));
const shown = new Set(DATA.layers);
let selected = null;

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const short = id => id.split('/').pop();
const fname = id => { const f = fn.get(id); return f ? short(f.module) + ' · ' + f.name : id; };
const flink = id => `<a data-f="${esc(id)}">${esc(fname(id))}</a>`;
const mlink = id => `<a data-m="${esc(id)}">${esc(id)}</a>`;
function tags(fs) {
  const w = fs.some(f => f.writes.length), c = fs.some(f => f.config.length || f.env.length), p = fs.some(f => f.programs.length);
  return (w ? '<span class="tag w">W</span>' : '') + (c ? '<span class="tag c">C</span>' : '') + (p ? '<span class="tag p">P</span>' : '');
}
document.getElementById('stats').textContent = `${DATA.modules.length} modules · ${DATA.functions.length} functions · ` +
  `${DATA.functions.reduce((n, f) => n + f.calls.length, 0)} calls`;

// ---------- map ----------
const W = 200, H = 24, GAP = 6, COLW = 250, TOP = 40;
let view = null;
function layout() {
  const pos = new Map(); let col = 0;
  for (const layer of DATA.layers) {
    const ms = DATA.modules.filter(m => m.layer === layer && shown.has(layer)).sort((a, b) => a.id.localeCompare(b.id));
    if (!ms.length) continue;
    ms.forEach((m, i) => pos.set(m.id, {x: col * COLW, y: TOP + i * (H + GAP), layer}));
    col++;
  }
  return pos;
}
function drawMap() {
  const center = document.getElementById('center');
  const pos = layout();
  if (!view) fit(pos);
  const heads = new Map();
  for (const [id, p] of pos) if (!heads.has(p.layer)) heads.set(p.layer, p.x);
  let edges = '', boxes = '';
  const out = selected && deps.get(selected), inn = selected && usedBy.get(selected);
  for (const [a, k] of deps) for (const b of k.keys()) {
    const p = pos.get(a), q = pos.get(b); if (!p || !q) continue;
    const cls = !selected ? '' : a === selected ? 'out' : b === selected ? 'in' : 'dim';
    const x1 = p.x + W, y1 = p.y + H / 2, x2 = q.x, y2 = q.y + H / 2;
    const [sx, ex] = x2 > x1 ? [x1, x2] : x2 + W < p.x ? [p.x, x2 + W] : [x1, x2 + W];
    const bend = Math.max(40, Math.abs(ex - sx) / 2), dir = ex >= sx ? 1 : -1;
    const loop = x2 <= x1 && !(x2 + W < p.x);
    const d = loop ? `M${x1},${y1} C${x1 + 60},${y1} ${x2 + W + 60},${y2} ${x2 + W},${y2}`
                   : `M${sx},${y1} C${sx + bend * dir},${y1} ${ex - bend * dir},${y2} ${ex},${y2}`;
    edges += `<path class="e ${cls}" d="${d}"/>`;
  }
  for (const [id, p] of pos) {
    const cls = !selected ? '' : id === selected ? 'sel' : out.has(id) ? 'out' : inn.has(id) ? 'in' : 'dim';
    const fs = byModule.get(id);
    const marks = [fs.some(f => f.writes.length) && 'W', fs.some(f => f.config.length || f.env.length) && 'C', fs.some(f => f.programs.length) && 'P'].filter(Boolean).join(' ');
    boxes += `<g class="box ${cls}" data-m="${esc(id)}" transform="translate(${p.x},${p.y})"><rect width="${W}" height="${H}"/>` +
      `<rect width="4" height="${H}" style="fill:${COLORS[p.layer]};stroke:none"/>` +
      `<text x="10" y="16">${esc(short(id))}</text><text x="${W - 8}" y="16" text-anchor="end" style="fill:var(--muted);font-size:10px">${marks}</text></g>`;
  }
  let titles = '';
  for (const [layer, x] of heads) titles += `<text class="col" x="${x}" y="22">${layer}</text>`;
  center.innerHTML = `<svg id="svg" viewBox="${view.x} ${view.y} ${view.w} ${view.h}">${titles}${edges}${boxes}</svg>`;
  const svg = document.getElementById('svg');
  svg.querySelectorAll('.box').forEach(g => g.addEventListener('click', e => { e.stopPropagation(); showModule(g.dataset.m); }));
  panZoom(svg);
}
function panZoom(svg) {
  let drag = null;
  svg.onmousedown = e => { drag = {x: e.clientX, y: e.clientY, vx: view.x, vy: view.y}; svg.style.cursor = 'grabbing'; };
  window.onmouseup = () => { drag = null; svg.style.cursor = ''; };
  svg.onmousemove = e => { if (!drag) return; const s = view.w / svg.clientWidth;
    view.x = drag.vx - (e.clientX - drag.x) * s; view.y = drag.vy - (e.clientY - drag.y) * s; svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`); };
  svg.onwheel = e => { e.preventDefault(); const k = e.deltaY > 0 ? 1.1 : 1 / 1.1, r = svg.getBoundingClientRect();
    const mx = view.x + (e.clientX - r.left) / r.width * view.w, my = view.y + (e.clientY - r.top) / r.height * view.h;
    view = {x: mx - (mx - view.x) * k, y: my - (my - view.y) * k, w: view.w * k, h: view.h * k};
    svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`); };
  svg.onclick = () => { if (selected) { selected = null; drawMap(); } };
}
function fit(pos) {
  const r = document.getElementById('center').getBoundingClientRect();
  let w = 0, h = 0;
  for (const p of pos.values()) { w = Math.max(w, p.x + W); h = Math.max(h, p.y + H); }
  w += 40; h += 20;
  const aspect = r.height / Math.max(r.width, 1);
  view = h / w > aspect ? {x: -20, y: 0, w: h / aspect, h} : {x: -20, y: 0, w, h: w * aspect};
}
function kindList(m) {
  return [...m].sort((a, b) => a[0].localeCompare(b[0])).map(([id, kinds]) => `<div>${mlink(id)} <span class="muted">${[...kinds].join(', ')}</span></div>`).join('') || '<div class="muted">none</div>';
}
function showModule(id) {
  selected = id; tab('map', true); drawMap();
  const m = mod.get(id), fs = byModule.get(id);
  document.getElementById('right').innerHTML = `<h2>${esc(id)}</h2>
    <div class="muted"><span class="swatch" style="background:${COLORS[m.layer]}"></span> ${m.layer} · ${m.lines} lines</div>
    ${m.doc ? `<p>${esc(m.doc)}</p>` : ''}
    <h3 style="color:var(--out)">Uses</h3><div class="list">${kindList(deps.get(id))}</div>
    <h3 style="color:var(--in)">Used by</h3><div class="list">${kindList(usedBy.get(id))}</div>
    <h3>Functions (${fs.length})</h3><div class="list">${fs.map(f => `<div data-f="${esc(f.id)}">${esc(f.name)} <span class="muted">:${f.line}</span>${tags([f])}</div>`).join('')}</div>`;
}
function section(title, rows) { return rows.length ? `<h3>${title}</h3><div class="list">${rows.join('')}</div>` : ''; }
function showFunction(id) {
  const f = fn.get(id); if (!f) return;
  if (selected !== f.module) { selected = f.module; if (current === 'map') drawMap(); }
  document.getElementById('right').innerHTML = `<h2>${esc(f.name)}</h2>
    <div>${mlink(f.module)}<span class="muted">:${f.line}</span></div>${f.doc ? `<p>${esc(f.doc)}</p>` : ''}
    ${section('Calls', f.calls.map(c => `<div>${flink(c)}</div>`))}
    ${section('Called by', (callers.get(id) || []).map(c => `<div>${flink(c)}</div>`))}
    ${section('Writes files', f.writes.map(w => `<div class="bad">${esc(w.op)} <span class="muted">line ${w.line}</span></div>`))}
    ${section('Reads config', f.config.map(([s, k]) => `<div>${esc(s + '.' + k)}</div>`))}
    ${section('Reads environment', f.env.map(e => `<div>${esc(e)}</div>`))}
    ${section('Runs programs', f.programs.map(p => `<div class="warn">${esc(p)}</div>`))}
    ${section('Runs scripts', f.runs.map(r => `<div>${mlink(r)}</div>`))}`;
}
document.body.addEventListener('click', e => {
  const t = e.target.closest('[data-f],[data-m]'); if (!t || t.closest('svg')) return;
  if (t.dataset.f) showFunction(t.dataset.f); else showModule(t.dataset.m);
});

// ---------- search and layers ----------
const items = [...DATA.modules.map(m => ({label: m.id, m: m.id})), ...DATA.functions.filter(f => f.name !== '<module>').map(f => ({label: short(f.module) + ' · ' + f.name, f: f.id}))];
document.getElementById('q').addEventListener('input', e => {
  const q = e.target.value.trim().toLowerCase();
  const hits = q ? items.filter(i => i.label.toLowerCase().includes(q)).slice(0, 40) : [];
  document.getElementById('hits').innerHTML = hits.map(i => i.f ? `<div data-f="${esc(i.f)}">${esc(i.label)}</div>` : `<div data-m="${esc(i.m)}">${esc(i.label)}</div>`).join('');
});
document.getElementById('layers').innerHTML = DATA.layers.filter(l => DATA.modules.some(m => m.layer === l)).map(l =>
  `<label><input type="checkbox" checked value="${l}"><span class="swatch" style="background:${COLORS[l]}"></span>${l}
   <span class="muted">${DATA.modules.filter(m => m.layer === l).length}</span></label>`).join('');
document.getElementById('layers').addEventListener('change', e => { e.target.checked ? shown.add(e.target.value) : shown.delete(e.target.value); view = null; drawMap(); });

// ---------- tables ----------
function readers(test) { return DATA.functions.filter(test).map(f => f.id); }
function configPage() {
  const c = DATA.config, bad = new Set(c.unused.map(p => p.join('.'))), odd = new Set(c.unknown.map(p => p.join('.')));
  const keys = [...c.declared, ...c.unknown];
  const rows = keys.map(([s, k]) => { const key = s + '.' + k, rs = readers(f => f.config.some(p => p[0] === s && p[1] === k));
    const note = bad.has(key) ? '<span class="bad">no direct read found</span> <span class="muted">(check loops and helpers)</span>' : odd.has(key) ? '<span class="warn">read, not declared in config.KEYS</span>' : '';
    return `<tr><td><b>${esc(key)}</b></td><td>${note}</td><td>${rs.map(flink).join('<br>')}</td></tr>`; }).join('');
  const env = [...new Set(DATA.functions.flatMap(f => f.env))].sort().map(v =>
    `<tr><td><b>${esc(v)}</b></td><td>${readers(f => f.env.includes(v)).map(flink).join('<br>')}</td></tr>`).join('');
  return `<div class="page"><h2>Config settings</h2><p class="muted">Each setting in config.KEYS and the functions that read it with config.get or settings[section].
    ${c.unused.length} with no direct read · ${c.unknown.length} not declared.</p>
    <table><tr><th>Setting</th><th>Check</th><th>Read by</th></tr>${rows}</table>
    <h2 style="margin-top:24px">Environment variables</h2><table><tr><th>Variable</th><th>Read by</th></tr>${env}</table></div>`;
}
function writesPage() {
  const rows = DATA.modules.map(m => { const fs = byModule.get(m.id).filter(f => f.writes.length); if (!fs.length) return '';
    return fs.map(f => `<tr><td>${mlink(m.id)}</td><td>${flink(f.id)}</td><td>${f.writes.map(w => `${esc(w.op)} <span class="muted">:${w.line}</span>`).join('<br>')}</td></tr>`).join(''); }).join('');
  return `<div class="page"><h2>File writes</h2><p class="muted">Every call that creates, replaces, moves or deletes a file or folder.</p>
    <table><tr><th>Module</th><th>Function</th><th>Operation</th></tr>${rows}</table></div>`;
}
function programsPage() {
  const progs = [...new Set(DATA.functions.flatMap(f => f.programs))].sort();
  const rows = progs.map(p => `<tr><td><b>${esc(p)}</b></td><td>${readers(f => f.programs.includes(p)).map(flink).join('<br>')}</td></tr>`).join('');
  const scripts = [...new Set(DATA.functions.flatMap(f => f.runs))].sort().map(s =>
    `<tr><td>${mlink(s)}</td><td>${readers(f => f.runs.includes(s)).map(flink).join('<br>')}</td></tr>`).join('');
  return `<div class="page"><h2>External programs</h2><table><tr><th>Program</th><th>Run by</th></tr>${rows}</table>
    <h2 style="margin-top:24px">Scripts named in code</h2><table><tr><th>Script</th><th>Named by</th></tr>${scripts}</table></div>`;
}
let current = 'map';
function tab(name, keep) {
  current = name;
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
  const main = document.getElementById('main'), wide = name !== 'map';
  main.classList.toggle('wide', wide);
  document.getElementById('left').style.display = document.getElementById('right').style.display = wide ? 'none' : '';
  if (keep) return;
  const center = document.getElementById('center');
  if (name === 'map') drawMap(); else center.innerHTML = {config: configPage, writes: writesPage, programs: programsPage}[name]();
}
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => tab(b.dataset.tab)));
document.getElementById('center').addEventListener('click', e => {
  if (current === 'map') return;
  const t = e.target.closest('[data-f],[data-m]'); if (!t) return;
  e.stopPropagation(); const f = t.dataset.f, m = t.dataset.m;
  tab('map'); f ? showFunction(f) : showModule(m);
}, true);
drawMap();
</script>
</body>
</html>
'''


def render(data):
    payload = json.dumps(data, sort_keys=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return PAGE.replace('__DATA__', payload, 1)
