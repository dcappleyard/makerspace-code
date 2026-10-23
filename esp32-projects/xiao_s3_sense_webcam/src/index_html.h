#pragma once

// The whole web UI: one page, no external assets (the camera may be on a LAN
// with no internet). Talks to the JSON API in web.cpp; the live stream is an
// <img> pointed at STREAM_PORT, and clearing its src is what turns it off.

const char INDEX_HTML[] = R"HTML(<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>XIAO Cam</title>
<style>
:root{--bg:#f6f6f4;--panel:#fff;--text:#1d1d1b;--muted:#6b6b66;--line:#e2e2dd;--accent:#2563eb;--accent-text:#fff;--warn:#b4400c;--ok:#15803d;--shadow:0 1px 3px rgba(0,0,0,.08)}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--panel:#1f1f1d;--text:#ecece8;--muted:#9a9a93;--line:#33332f;--accent:#60a5fa;--accent-text:#0b1220;--warn:#f59e0b;--ok:#4ade80;--shadow:none}}
:root{--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--grid:#e8e8e3}
@media (prefers-color-scheme:dark){:root{--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--grid:#2a2a27}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,-apple-system,sans-serif}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:.4rem 1rem;padding:.8rem 1rem;border-bottom:1px solid var(--line)}
header h1{font-size:1.15rem;margin:0}
#status{color:var(--muted);font-size:.85rem;display:flex;flex-wrap:wrap;gap:.2rem .9rem}
#status .warn{color:var(--warn);font-weight:600}
main{display:grid;grid-template-columns:minmax(0,1fr) 20rem;gap:1rem;padding:1rem;max-width:80rem;margin:0 auto}
@media (max-width:900px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);padding:1rem}
#viewer{position:relative;background:#000;border-radius:8px;aspect-ratio:4/3;display:flex;align-items:center;justify-content:center;overflow:hidden}
#viewer img{max-width:100%;max-height:100%;display:block}
#viewer .placeholder{color:#888;font-size:.95rem;text-align:center;padding:1rem}
#viewer .badge{position:absolute;top:.6rem;left:.6rem;background:rgba(0,0,0,.6);color:#fff;font-size:.75rem;padding:.15rem .5rem;border-radius:99px}
#viewer .badge.live{background:#dc2626}
#flash{position:absolute;inset:0;background:#fff;opacity:0;pointer-events:none;transition:opacity .25s}
.actions{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:.8rem;align-items:center}
button{font:inherit;padding:.5rem 1rem;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--text);cursor:pointer}
button:hover{border-color:var(--muted)}
button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-text);font-weight:600}
button:disabled{opacity:.5;cursor:default}
#msg{font-size:.85rem;color:var(--muted)}
#msg.err{color:var(--warn)}
h2{font-size:.95rem;margin:0 0 .6rem}
h3{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:1rem 0 .4rem}
h3:first-of-type{margin-top:0}
.ctl{display:grid;grid-template-columns:7.5rem 1fr 2.5rem;align-items:center;gap:.5rem;margin:.35rem 0;font-size:.9rem}
.ctl.toggle{grid-template-columns:1fr auto}
.ctl.disabled{opacity:.4}
.ctl output{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.ctl select{grid-column:2/4;font:inherit;padding:.2rem;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px}
input[type=range]{width:100%;accent-color:var(--accent)}
input[type=checkbox]{width:1.1rem;height:1.1rem;accent-color:var(--accent)}
.hint{font-size:.78rem;color:var(--muted);margin:.2rem 0 .4rem}
#gallery-wrap{grid-column:1/-1}
.gallery-head{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:.5rem}
#gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(9.5rem,1fr));gap:.6rem;margin-top:.6rem}
.thumb{background:var(--bg);border:1px solid var(--line);border-radius:8px;overflow:hidden;cursor:pointer;padding:0;text-align:left}
.thumb img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:#000}
.thumb div{font-size:.72rem;padding:.3rem .4rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.thumb .tmp{color:var(--warn);font-weight:600}
#battery-wrap{grid-column:1/-1}
.batt-now{display:flex;flex-wrap:wrap;gap:.4rem 2rem;align-items:baseline;margin:.2rem 0 .4rem}
.batt-now .big{font-size:1.6rem;font-weight:600;font-variant-numeric:tabular-nums}
.batt-now .lbl{font-size:.8rem;color:var(--muted)}
select.inline{font:inherit;padding:.3rem;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px}
#chart{position:relative;margin-top:.8rem}
#chart svg{width:100%;height:auto;display:block;overflow:visible}
#chart .axis text{fill:var(--muted);font-size:11px}
#chart .grid line{stroke:var(--grid);stroke-width:1}
#chart .series path{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
#chart .endlabel{font-size:11px;fill:var(--text)}
#chart .cross{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
#chart .dot{stroke:var(--panel);stroke-width:2}
#tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.15);padding:.4rem .6rem;font-size:.8rem;display:none;white-space:nowrap;z-index:2}
#tip .sw{display:inline-block;width:.7rem;height:.15rem;border-radius:2px;vertical-align:middle;margin-right:.35rem}
.legend{display:flex;flex-wrap:wrap;gap:.3rem 1rem;font-size:.8rem;color:var(--muted);margin-top:.4rem}
.legend .sw{display:inline-block;width:1rem;height:.2rem;border-radius:2px;vertical-align:middle;margin-right:.35rem}
table.runs{width:100%;border-collapse:collapse;margin-top:.8rem;font-size:.85rem}
table.runs th{text-align:left;font-weight:600;color:var(--muted);font-size:.75rem;border-bottom:1px solid var(--line);padding:.3rem .4rem}
table.runs td{border-bottom:1px solid var(--line);padding:.3rem .4rem;font-variant-numeric:tabular-nums}
table.runs td.act{white-space:nowrap;text-align:right}
table.runs td.act a,table.runs td.act button{font-size:.78rem;padding:.2rem .5rem;margin-left:.2rem}
table.runs a{color:var(--accent)}
.runs-wrap{overflow-x:auto}
#lightbox{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;flex-direction:column;align-items:center;justify-content:center;padding:1rem;z-index:10}
#lightbox.open{display:flex}
#lightbox img{max-width:100%;max-height:80vh;border-radius:6px}
#lightbox .bar{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;margin-top:.8rem;color:#ddd;font-size:.85rem}
#lightbox a,#lightbox button{color:#fff;background:#333;border:1px solid #555;border-radius:8px;padding:.4rem .9rem;text-decoration:none;font:inherit;cursor:pointer}
</style></head>
<body>
<header>
  <h1>XIAO Cam</h1>
  <div id="status">loading&hellip;</div>
</header>
<main>
  <section class="panel">
    <div id="viewer">
      <div class="placeholder" id="placeholder">Stream is off. Turn it on, or take a snapshot.</div>
      <img id="view" alt="" hidden>
      <span class="badge" id="badge" hidden></span>
      <div id="flash"></div>
    </div>
    <div class="actions">
      <button id="streamBtn" class="primary">Start live stream</button>
      <button id="snapBtn">Take snapshot</button>
      <span id="msg"></span>
    </div>
  </section>

  <aside class="panel" id="controls">
    <h2>Camera settings</h2>
    <div id="ctls"></div>
    <div class="actions"><button id="resetBtn">Reset to defaults</button></div>
    <p class="hint">Settings are saved on the camera and survive a reboot.</p>
  </aside>

  <section class="panel" id="gallery-wrap">
    <div class="gallery-head">
      <h2 id="galleryTitle">Snapshots</h2>
      <div class="actions" style="margin:0">
        <span id="sdNote" class="hint"></span>
        <button id="sdBtn">Re-check SD card</button>
      </div>
    </div>
    <div id="gallery"></div>
    <div class="actions"><button id="moreBtn" hidden>Show more</button></div>
  </section>

  <section class="panel" id="battery-wrap">
    <div class="gallery-head">
      <h2>Battery</h2>
      <span class="hint">Round display LiPo, read on A0</span>
    </div>
    <div class="batt-now" id="battNow"></div>
    <div class="actions">
      <label class="hint">Log every
        <select id="logInterval" class="inline">
          <option value="10">10 s</option><option value="30" selected>30 s</option>
          <option value="60">1 min</option><option value="120">2 min</option>
        </select>
      </label>
      <button id="logBtn" class="primary">Start logging</button>
      <span id="logStatus" class="hint"></span>
    </div>
    <p class="hint">To record a discharge curve: charge the battery fully, unplug USB-C, then start logging and leave it running until the board shuts off. The log is kept in the camera's flash, so it survives the battery dying. Plug back in and the run is here to plot, download or use for calibration.</p>
    <div id="chart"><div id="tip"></div></div>
    <div class="legend" id="legend"></div>
    <div class="runs-wrap"><table class="runs" id="runs"></table></div>
    <div class="actions">
      <span id="calInfo" class="hint"></span>
      <button id="calReset">Reset calibration</button>
    </div>
  </section>
</main>

<div id="lightbox">
  <img id="lbImg" alt="">
  <div class="bar">
    <span id="lbName"></span>
    <a id="lbDl" download>Download</a>
    <button id="lbDel">Delete</button>
    <button id="lbClose">Close</button>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
const FRAMESIZES = ['96x96','160x120 QQVGA','128x128','176x144 QCIF','240x176 HQVGA','240x240','320x240 QVGA','320x320','400x296 CIF','480x320 HVGA','640x480 VGA','800x600 SVGA','1024x768 XGA','1280x720 HD','1280x1024 SXGA','1600x1200 UXGA','1920x1080 FHD','720x1280 portrait','864x1536 portrait','2048x1536 QXGA'];
// on: enabled only when that control is 1; off: enabled only when it's 0.
const CONTROLS = [
  {group:'Image'},
  {key:'framesize', label:'Resolution', type:'select', options:() => FRAMESIZES.slice(0, state.max_framesize + 1)},
  {key:'quality', label:'JPEG quality', type:'range', min:4, max:63, hint:'Lower number = better quality, bigger files'},
  {group:'Exposure'},
  {key:'aec', label:'Auto exposure', type:'toggle'},
  {key:'ae_level', label:'AE level', type:'range', min:-2, max:2, on:'aec'},
  {key:'aec2', label:'Night mode (DSP AEC)', type:'toggle', on:'aec'},
  {key:'aec_value', label:'Exposure', type:'range', min:0, max:1200, off:'aec', hint:'Manual exposure — turn auto exposure off to use'},
  {group:'Gain'},
  {key:'agc', label:'Auto gain', type:'toggle'},
  {key:'gainceiling', label:'Gain ceiling', type:'select', options:() => ['2x','4x','8x','16x','32x','64x','128x'], on:'agc'},
  {key:'agc_gain', label:'Gain', type:'range', min:0, max:30, off:'agc', hint:'Manual gain — turn auto gain off to use'},
  {group:'Colour'},
  {key:'awb', label:'Auto white balance', type:'toggle'},
  {key:'awb_gain', label:'AWB gain', type:'toggle', on:'awb'},
  {key:'wb_mode', label:'WB mode', type:'select', options:() => ['Auto','Sunny','Cloudy','Office','Home'], on:'awb'},
  {key:'brightness', label:'Brightness', type:'range', min:-2, max:2},
  {key:'contrast', label:'Contrast', type:'range', min:-2, max:2},
  {key:'saturation', label:'Saturation', type:'range', min:-2, max:2},
  {group:'Orientation'},
  {key:'hmirror', label:'Mirror', type:'toggle'},
  {key:'vflip', label:'Flip', type:'toggle'},
  {key:'lenc', label:'Lens correction', type:'toggle'},
];

let state = {max_framesize: 11, settings: {}};
let streaming = false;
let photos = [];
let shown = 24;
let lbName = null;

function msg(text, err) {
  const m = $('msg');
  m.textContent = text || '';
  m.className = err ? 'err' : '';
  if (text && !err) setTimeout(() => { if (m.textContent === text) m.textContent = ''; }, 4000);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}
const post = path => api(path, {method: 'POST'});

function fmtBytes(n) {
  return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
}

// --- Status -----------------------------------------------------------------
function renderStatus() {
  const s = state, parts = [];
  parts.push(s.camera_ok ? s.sensor : '<span class="warn">camera not found</span>');
  parts.push(s.ip);
  parts.push(s.clock_set ? s.clock : '<span class="warn">clock not set — snapshots get nodate_ names</span>');
  parts.push(s.sd ? 'SD: ' + s.sd_free_mb + ' MB free'
                  : '<span class="warn">no SD card — ' + s.ram_photos + '/' + s.ram_photos_max + ' snapshots in RAM</span>');
  const b = s.battery;
  if (b && b.valid) parts.push('Battery ' + (b.battery_mv / 1000).toFixed(2) + ' V · ' + b.percent + '% est.' + (b.usb_host ? ' · USB' : ''));
  parts.push('PSRAM free ' + fmtBytes(s.psram_free));
  $('status').innerHTML = parts.map(p => '<span>' + p + '</span>').join('');
  $('sdNote').textContent = s.sd ? '' : 'Temporary snapshots move to the card when one is found.';
}

async function loadStatus() {
  try {
    state = await api('/api/status');
    renderStatus();
    syncControls();
  } catch (e) {
    $('status').innerHTML = '<span class="warn">camera unreachable</span>';
  }
}

// --- Controls ---------------------------------------------------------------
function buildControls() {
  const root = $('ctls');
  root.innerHTML = '';
  for (const c of CONTROLS) {
    if (c.group) {
      const h = document.createElement('h3');
      h.textContent = c.group;
      root.appendChild(h);
      continue;
    }
    const row = document.createElement('label');
    row.className = 'ctl' + (c.type === 'toggle' ? ' toggle' : '');
    row.id = 'row_' + c.key;
    const name = document.createElement('span');
    name.textContent = c.label;
    row.appendChild(name);
    let input;
    if (c.type === 'range') {
      input = document.createElement('input');
      input.type = 'range';
      input.min = c.min; input.max = c.max; input.step = 1;
      const out = document.createElement('output');
      input.addEventListener('input', () => { out.textContent = input.value; });
      row.appendChild(input);
      row.appendChild(out);
    } else if (c.type === 'select') {
      input = document.createElement('select');
      row.appendChild(input);
    } else {
      input = document.createElement('input');
      input.type = 'checkbox';
      row.appendChild(input);
    }
    input.id = 'ctl_' + c.key;
    input.addEventListener('change', () => setControl(c, input));
    root.appendChild(row);
    if (c.hint) {
      const p = document.createElement('div');
      p.className = 'hint';
      p.textContent = c.hint;
      root.appendChild(p);
    }
  }
}

function syncControls() {
  const st = state.settings || {};
  for (const c of CONTROLS) {
    if (c.group) continue;
    const input = $('ctl_' + c.key), v = st[c.key];
    if (v === undefined) continue;
    if (document.activeElement === input && c.type === 'range') continue; // mid-drag
    if (c.type === 'select') {
      const opts = c.options();
      if (input.options.length !== opts.length) {
        input.innerHTML = '';
        opts.forEach((label, i) => input.add(new Option(label, i)));
      }
      input.value = v;
    } else if (c.type === 'range') {
      input.value = v;
      input.nextElementSibling.textContent = v;
    } else {
      input.checked = !!v;
    }
    const enabled = (!c.on || st[c.on]) && (!c.off || !st[c.off]);
    input.disabled = !enabled;
    $('row_' + c.key).classList.toggle('disabled', !enabled);
  }
}

async function setControl(c, input) {
  const val = c.type === 'toggle' ? (input.checked ? 1 : 0) : parseInt(input.value, 10);
  try {
    state.settings = await post('/api/control?var=' + c.key + '&val=' + val);
    msg(c.label + ' set');
  } catch (e) {
    msg(c.label + ': ' + e.message, true);
  }
  syncControls();
}

$('resetBtn').onclick = async () => {
  if (!confirm('Reset all camera settings to their defaults?')) return;
  try {
    state.settings = await post('/api/reset');
    syncControls();
    msg('Settings reset');
  } catch (e) { msg(e.message, true); }
};

// --- Stream & snapshot ------------------------------------------------------
function streamUrl() {
  let u = location.protocol + '//' + location.hostname + ':' + (state.stream_port || 81) + '/stream';
  if (state.stream_token) u += '?t=' + state.stream_token;
  return u + (u.includes('?') ? '&' : '?') + '_=' + Date.now();
}

function showImage(src, badge, live) {
  const img = $('view');
  img.src = src;
  img.hidden = false;
  $('placeholder').hidden = true;
  const b = $('badge');
  b.textContent = badge;
  b.hidden = !badge;
  b.classList.toggle('live', !!live);
}

function setStreaming(on) {
  streaming = on;
  const btn = $('streamBtn');
  if (on) {
    showImage(streamUrl(), 'LIVE', true);
    btn.textContent = 'Stop live stream';
  } else {
    // Clearing src closes the connection, which ends the stream on the camera.
    const img = $('view');
    img.removeAttribute('src');
    const last = photos[0];
    if (last) showImage(photoUrl(last.name), last.name, false);
    else { img.hidden = true; $('placeholder').hidden = false; $('badge').hidden = true; }
    btn.textContent = 'Start live stream';
  }
}

$('view').onerror = () => {
  if (streaming) { msg('Stream dropped (only one viewer at a time)', true); setStreaming(false); }
};
$('streamBtn').onclick = () => setStreaming(!streaming);

$('snapBtn').onclick = async () => {
  const btn = $('snapBtn');
  btn.disabled = true;
  const f = $('flash');
  f.style.opacity = .7;
  setTimeout(() => { f.style.opacity = 0; }, 150);
  try {
    const r = await post('/api/snap');
    msg('Saved ' + r.name + (r.sd ? ' to SD card' : ' in RAM (no SD card)') + (r.dated ? '' : ' — clock not set'));
    await loadPhotos();
    if (!streaming) showImage(photoUrl(r.name), r.name, false);
    loadStatus();
  } catch (e) { msg('Snapshot failed: ' + e.message, true); }
  btn.disabled = false;
};

// --- Gallery ----------------------------------------------------------------
const photoUrl = name => '/photo?name=' + encodeURIComponent(name);

async function loadPhotos() {
  try { photos = await api('/api/photos'); } catch (e) { photos = []; }
  renderGallery();
}

function renderGallery() {
  const g = $('gallery');
  g.innerHTML = '';
  $('galleryTitle').textContent = 'Snapshots (' + photos.length + ')';
  if (!photos.length) {
    g.innerHTML = '<p class="hint">No snapshots yet.</p>';
  }
  for (const p of photos.slice(0, shown)) {
    const t = document.createElement('button');
    t.className = 'thumb';
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.src = photoUrl(p.name);
    img.alt = p.name;
    const cap = document.createElement('div');
    cap.textContent = p.name.replace(/\.jpg$/, '') + ' · ' + fmtBytes(p.size);
    if (!p.sd) {
      const tmp = document.createElement('span');
      tmp.className = 'tmp';
      tmp.textContent = ' · temporary';
      tmp.title = 'Held in RAM (no SD card) — lost on reboot';
      cap.appendChild(tmp);
    }
    t.appendChild(img);
    t.appendChild(cap);
    t.onclick = () => openLightbox(p.name);
    g.appendChild(t);
  }
  $('moreBtn').hidden = photos.length <= shown;
}
$('moreBtn').onclick = () => { shown += 24; renderGallery(); };

function openLightbox(name) {
  lbName = name;
  $('lbImg').src = photoUrl(name);
  $('lbName').textContent = name;
  $('lbDl').href = photoUrl(name);
  $('lbDl').download = name;
  $('lightbox').classList.add('open');
}
function closeLightbox() { $('lightbox').classList.remove('open'); lbName = null; }
$('lbClose').onclick = closeLightbox;
$('lightbox').onclick = e => { if (e.target.id === 'lightbox') closeLightbox(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });
$('lbDel').onclick = async () => {
  if (!lbName || !confirm('Delete ' + lbName + '?')) return;
  try {
    await post('/api/photos/delete?name=' + encodeURIComponent(lbName));
    closeLightbox();
    await loadPhotos();
    loadStatus();
  } catch (e) { msg(e.message, true); }
};

$('sdBtn').onclick = async () => {
  const btn = $('sdBtn');
  btn.disabled = true;
  try {
    const r = await post('/api/sd/mount');
    msg(r.sd ? 'SD card found' + (r.moved ? ' — moved ' + r.moved + ' snapshot(s) onto it' : '') : 'No SD card found', !r.sd);
    await loadPhotos();
    loadStatus();
  } catch (e) { msg(e.message, true); }
  btn.disabled = false;
};

// --- Battery ----------------------------------------------------------------
let batt = null;
const runCache = {};   // name -> {size, points, meta}
const plotted = [];    // run names on the chart, in the order they were added
const slotOf = {};     // name -> series slot 1-4; kept while plotted, so colours never shift
const MAX_PLOTTED = 4;
let chartGeom = null;

function fmtDuration(s) {
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return h ? h + 'h ' + String(m).padStart(2, '0') + 'm' : m + 'm ' + String(s % 60).padStart(2, '0') + 's';
}

function parseRun(text) {
  const lines = text.trim().split('\n');
  const head = lines.shift().split(',');
  const col = k => head.indexOf(k);
  const iT = col('elapsed_s'), iA = col('a0_mv'), iB = col('battery_mv_est'), iP = col('percent_est'),
        iU = col('usb_host'), iE = col('event'), iL = col('local_time');
  const points = [], meta = {usbSamples: 0, boots: 0, started: '', end: ''};
  for (const line of lines) {
    const c = line.split(',');
    const ev = c[iE] || '';
    if (ev === 'start' && !meta.started) meta.started = c[iL];
    if (ev === 'boot') meta.boots++;
    if (ev) { if (ev !== 'start' && ev !== 'boot') meta.end = ev; continue; }
    const p = {t: +c[iT], a0: +c[iA], mv: +c[iB], pct: +c[iP]};
    if (+c[iU]) meta.usbSamples++;
    if (p.a0 > 0) points.push(p);
  }
  return {points, meta};
}

async function loadRun(r) {
  const c = runCache[r.name];
  if (c && c.size === r.size) return c;
  const text = await fetch('/api/battery/run?name=' + encodeURIComponent(r.name)).then(x => x.text());
  return runCache[r.name] = Object.assign({size: r.size}, parseRun(text));
}

async function loadBattery() {
  try { batt = await api('/api/battery'); } catch (e) { return; }
  renderBatteryNow();
  // Newest run plotted by default, the first time we see any.
  if (!plotted.length && batt.runs.length && !loadBattery.seeded) {
    loadBattery.seeded = true;
    togglePlot(batt.runs[0].name, true, false);
  }
  for (const r of batt.runs.slice(0, 12)) { try { await loadRun(r); } catch (e) {} }
  for (let i = plotted.length - 1; i >= 0; i--)
    if (!batt.runs.some(r => r.name === plotted[i])) togglePlot(plotted[i], false, false);
  // Only rebuild the table and chart when something changed, so a refresh
  // doesn't wipe a tooltip someone is reading.
  const sig = JSON.stringify([batt.runs, plotted]);
  if (sig !== loadBattery.sig) {
    loadBattery.sig = sig;
    renderRuns();
    drawChart();
  }
}

function renderBatteryNow() {
  const b = batt, el = $('battNow');
  const items = [];
  if (b.valid) {
    items.push('<div><div class="big">' + (b.battery_mv / 1000).toFixed(2) + ' V</div><div class="lbl">battery (est., A0 ' + b.a0_mv + ' mV × ' + b.divider + ')</div></div>');
    items.push('<div><div class="big">' + b.percent + '%</div><div class="lbl">estimated charge</div></div>');
  } else {
    items.push('<div><div class="big">—</div><div class="lbl">no battery voltage on A0 (' + b.a0_mv + ' mV) — no battery, or the KE switch isn\'t routing it</div></div>');
  }
  items.push('<div><div class="big" style="font-size:1.1rem">' + (b.usb_host ? 'Computer on USB' : 'No USB host') + '</div><div class="lbl">' +
    (b.usb_host ? 'likely charging' : 'running on battery, or a power-only charger') + '</div></div>');
  el.innerHTML = items.join('');
  const L = b.log;
  $('logBtn').textContent = L.active ? 'Stop logging' : 'Start logging';
  $('logBtn').classList.toggle('primary', !L.active);
  $('logInterval').disabled = L.active;
  if (L.active) $('logInterval').value = String(L.interval_s);
  $('logStatus').textContent = L.active
    ? 'Logging ' + L.run + ' · ' + fmtDuration(L.elapsed_s) + ' · ' + L.samples + ' samples'
    : (b.fs ? fmtBytes(b.fs_free) + ' free for logs' : 'flash filesystem unavailable');
  $('calInfo').textContent = b.cal_source
    ? 'Percentage calibrated from ' + b.cal_source + ' (100%: ' + b.cal[0] + ' mV, 0%: ' + b.cal[10] + ' mV on A0).'
    : 'Percentage uncalibrated: linear ' + b.cal[10] + '–' + b.cal[0] + ' mV on A0.';
  $('calReset').hidden = !b.cal_source;
}

$('logBtn').onclick = async () => {
  const L = batt && batt.log;
  try {
    if (L && L.active) {
      if (!confirm('Stop logging ' + L.run + '?')) return;
      batt = await post('/api/battery/log/stop');
    } else {
      if (batt && batt.usb_host && !confirm('A computer is connected over USB, so the battery is probably charging. Start logging anyway?')) return;
      if (batt && !batt.valid && !confirm('No battery voltage is showing on A0. Start logging anyway?')) return;
      batt = await post('/api/battery/log/start?interval=' + $('logInterval').value);
      const r = batt.runs.find(r => r.active);
      if (r) togglePlot(r.name, true, false);
    }
    loadBattery();
  } catch (e) { msg(e.message, true); }
};

$('calReset').onclick = async () => {
  if (!confirm('Go back to the uncalibrated linear estimate?')) return;
  try { batt = await post('/api/battery/cal/reset'); renderBatteryNow(); msg('Calibration reset'); }
  catch (e) { msg(e.message, true); }
};

function togglePlot(name, on, redraw = true) {
  const i = plotted.indexOf(name);
  if (on && i < 0) {
    if (plotted.length >= MAX_PLOTTED) { msg('Up to ' + MAX_PLOTTED + ' runs at once — untick one first', true); redraw && renderRuns(); return; }
    const used = new Set(plotted.map(n => slotOf[n]));
    slotOf[name] = [1, 2, 3, 4].find(k => !used.has(k));
    plotted.push(name);
  } else if (!on && i >= 0) {
    plotted.splice(i, 1);
    delete slotOf[name];
  }
  if (redraw) { renderRuns(); drawChart(); }
}

function renderRuns() {
  const t = $('runs');
  if (!batt || !batt.runs.length) { t.innerHTML = '<tr><td class="hint">No runs logged yet.</td></tr>'; return; }
  let h = '<tr><th>Plot</th><th>Run</th><th>Started</th><th>Duration</th><th>Samples</th><th>Battery V</th><th>Ended</th><th></th></tr>';
  for (const r of batt.runs) {
    const c = runCache[r.name], p = c ? c.points : [];
    const on = plotted.includes(r.name);
    const dur = p.length > 1 ? fmtDuration(p[p.length - 1].t - p[0].t) : '—';
    const volts = p.length ? (p[0].mv / 1000).toFixed(2) + ' → ' + (p[p.length - 1].mv / 1000).toFixed(2) : '—';
    const ended = r.active ? 'logging…' : c ? (c.meta.end || 'power lost') + (c.meta.boots ? ' (' + c.meta.boots + ' reboot' + (c.meta.boots > 1 ? 's' : '') + ')' : '') : '';
    const sw = on ? '<span class="sw" style="display:inline-block;width:.8rem;height:.2rem;border-radius:2px;vertical-align:middle;margin-left:.3rem;background:var(--series-' + slotOf[r.name] + ')"></span>' : '';
    h += '<tr><td><input type="checkbox" data-plot="' + r.name + '"' + (on ? ' checked' : '') + '>' + sw + '</td>' +
         '<td>' + r.name.replace('.csv', '') + '</td><td>' + (c && c.meta.started || '—') + '</td><td>' + dur + '</td><td>' + p.length +
         '</td><td>' + volts + '</td><td>' + ended + '</td><td class="act">' +
         '<a href="/api/battery/run?name=' + r.name + '" download="' + r.name + '">CSV</a>' +
         '<button data-cal="' + r.name + '"' + (r.active ? ' disabled' : '') + '>Calibrate</button>' +
         '<button data-del="' + r.name + '"' + (r.active ? ' disabled' : '') + '>Delete</button></td></tr>';
  }
  t.innerHTML = h;
  t.querySelectorAll('[data-plot]').forEach(x => x.onchange = () => togglePlot(x.dataset.plot, x.checked));
  t.querySelectorAll('[data-del]').forEach(x => x.onclick = () => deleteRunUi(x.dataset.del));
  t.querySelectorAll('[data-cal]').forEach(x => x.onclick = () => calibrateFrom(x.dataset.cal));
}

async function deleteRunUi(name) {
  if (!confirm('Delete ' + name + '? This can\'t be undone.')) return;
  try {
    batt = await post('/api/battery/run/delete?name=' + encodeURIComponent(name));
    togglePlot(name, false, false);
    delete runCache[name];
    loadBattery();
  } catch (e) { msg(e.message, true); }
}

// The run's time axis becomes the % axis: assuming it went from full charge
// to shutdown at a steady load, x% of the elapsed time = (100 - x)% used.
// Each 10% point is the median A0 reading within ±2% of the run around it.
async function calibrateFrom(name) {
  const c = runCache[name];
  const p = c ? c.points : [];
  if (p.length < 20) { msg('Need at least 20 samples in a run to calibrate from it', true); return; }
  const t0 = p[0].t, T = p[p.length - 1].t - t0;
  if (T < 1800) { msg('That run is under 30 minutes — too short to calibrate from', true); return; }
  const mv = [];
  for (let i = 0; i <= 10; i++) {
    const target = t0 + T * i / 10, w = T * 0.02;
    const near = p.filter(q => Math.abs(q.t - target) <= w).map(q => q.a0).sort((a, b) => a - b);
    let v = near.length ? near[Math.floor(near.length / 2)] : p.reduce((a, q) => Math.abs(q.t - target) < Math.abs(a.t - target) ? q : a).a0;
    if (i && v > mv[i - 1]) v = mv[i - 1]; // keep it non-increasing
    mv.push(v);
  }
  const table = mv.map((v, i) => (100 - i * 10) + '%: ' + v + ' mV').join('\n');
  const warn = c.meta.usbSamples ? '\n\nNote: ' + c.meta.usbSamples + ' samples had a USB host connected (charging?).' : '';
  if (!confirm('Use ' + name + ' as the 100% → 0% curve?\nThis assumes the run started fully charged and ran until the board shut off, at a steady load.' + warn + '\n\nA0 per 10%:\n' + table)) return;
  try {
    batt = await post('/api/battery/cal?src=' + encodeURIComponent(name) + '&mv=' + mv.join(','));
    renderBatteryNow();
    msg('Calibrated from ' + name);
  } catch (e) { msg(e.message, true); }
}

// One line per plotted run: battery V (est.) against hours since the run began.
function drawChart() {
  const host = $('chart');
  host.querySelectorAll('svg').forEach(x => x.remove());
  const series = plotted.map(n => ({name: n, slot: slotOf[n], pts: (runCache[n] || {}).points || []})).filter(x => x.pts.length);
  const legend = $('legend');
  legend.innerHTML = series.length >= 2
    ? series.map(x => '<span><span class="sw" style="background:var(--series-' + x.slot + ')"></span>' + x.name.replace('.csv', '') + '</span>').join('')
    : '';
  if (!series.length) { chartGeom = null; return; }

  const W = 680, H = 260, m = {l: 44, r: 64, t: 12, b: 30};
  const tMax = Math.max(...series.map(x => x.pts[x.pts.length - 1].t - x.pts[0].t), 60) / 3600;
  let vMin = Infinity, vMax = -Infinity;
  series.forEach(x => x.pts.forEach(q => { vMin = Math.min(vMin, q.mv); vMax = Math.max(vMax, q.mv); }));
  vMin = Math.floor(vMin / 100) * 100 / 1000; vMax = Math.ceil(vMax / 100) * 100 / 1000;
  if (vMax - vMin < 0.2) { vMin -= 0.1; vMax += 0.1; }
  const X = h => m.l + (W - m.l - m.r) * h / tMax;
  const Y = v => m.t + (H - m.t - m.b) * (1 - (v - vMin) / (vMax - vMin));
  const niceStep = (span, n) => { const r = span / n, p = Math.pow(10, Math.floor(Math.log10(r))); return [1, 2, 2.5, 5, 10].map(k => k * p).find(k => k >= r); };

  let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Battery voltage over time">';
  svg += '<g class="grid axis">';
  const vs = niceStep(vMax - vMin, 4);
  for (let v = Math.ceil(vMin / vs) * vs; v <= vMax + 1e-9; v += vs)
    svg += '<line x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + Y(v) + '" y2="' + Y(v) + '"/><text x="' + (m.l - 6) + '" y="' + (Y(v) + 4) + '" text-anchor="end">' + v.toFixed(2) + '</text>';
  const hs = niceStep(tMax, 6);
  for (let h = 0; h <= tMax + 1e-9; h += hs)
    svg += '<text x="' + X(h) + '" y="' + (H - m.b + 16) + '" text-anchor="middle">' + (+h.toFixed(2)) + (h === 0 ? ' h' : '') + '</text>';
  svg += '<text x="' + m.l + '" y="' + (m.t - 2) + '">V (est.)</text></g>';
  svg += '<g class="series">';
  for (const x of series) {
    const t0 = x.pts[0].t;
    const d = x.pts.map((q, i) => (i ? 'L' : 'M') + X((q.t - t0) / 3600).toFixed(1) + ' ' + Y(q.mv / 1000).toFixed(1)).join('');
    svg += '<path d="' + d + '" style="stroke:var(--series-' + x.slot + ')"/>';
  }
  svg += '</g>';
  // Direct labels at the line ends (<= 4 series), nudged apart vertically.
  const ends = series.map(x => { const q = x.pts[x.pts.length - 1]; return {x: X((q.t - x.pts[0].t) / 3600), y: Y(q.mv / 1000), label: x.name.replace('.csv', '').replace('run-', '#')}; })
                     .sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
  for (const e of ends) svg += '<text class="endlabel" x="' + (e.x + 6) + '" y="' + (e.y + 4) + '">' + e.label + '</text>';
  svg += '<g id="crossg" style="display:none"><line class="cross" id="crossl" y1="' + m.t + '" y2="' + (H - m.b) + '"/></g>';
  svg += '<rect id="hit" x="' + m.l + '" y="' + m.t + '" width="' + (W - m.l - m.r) + '" height="' + (H - m.t - m.b) + '" fill="transparent"/></svg>';
  host.insertAdjacentHTML('afterbegin', svg);
  chartGeom = {W, m, X, Y, tMax, series};
  const el = host.querySelector('svg');
  el.addEventListener('pointermove', crosshair);
  el.addEventListener('pointerleave', () => { $('tip').style.display = 'none'; host.querySelector('#crossg').style.display = 'none'; });
}

function crosshair(ev) {
  const g = chartGeom, host = $('chart'), svg = host.querySelector('svg');
  if (!g) return;
  const box = svg.getBoundingClientRect(), scale = g.W / box.width;
  const px = (ev.clientX - box.left) * scale;
  const h = Math.max(0, Math.min(g.tMax, (px - g.m.l) / (g.W - g.m.l - g.m.r) * g.tMax));
  const cg = host.querySelector('#crossg');
  cg.style.display = '';
  cg.querySelectorAll('circle').forEach(c => c.remove());
  host.querySelector('#crossl').setAttribute('x1', g.X(h));
  host.querySelector('#crossl').setAttribute('x2', g.X(h));
  let rows = '';
  for (const x of g.series) {
    const t0 = x.pts[0].t, want = t0 + h * 3600;
    if (want > x.pts[x.pts.length - 1].t + 1) { rows += '<div><span class="sw" style="background:var(--series-' + x.slot + ')"></span>' + x.name.replace('.csv', '') + ': ended</div>'; continue; }
    const q = x.pts.reduce((a, b) => Math.abs(b.t - want) < Math.abs(a.t - want) ? b : a);
    cg.insertAdjacentHTML('beforeend', '<circle class="dot" r="4" cx="' + g.X((q.t - t0) / 3600) + '" cy="' + g.Y(q.mv / 1000) + '" style="fill:var(--series-' + x.slot + ')"/>');
    rows += '<div><span class="sw" style="background:var(--series-' + x.slot + ')"></span>' + x.name.replace('.csv', '') + ': <b>' + (q.mv / 1000).toFixed(3) + ' V</b> · A0 ' + q.a0 + ' mV · ' + q.pct + '% est.</div>';
  }
  const tip = $('tip');
  tip.innerHTML = '<div style="color:var(--muted);margin-bottom:.2rem">' + fmtDuration(h * 3600) + ' in</div>' + rows;
  tip.style.display = 'block';
  const left = (ev.clientX - box.left) + 14;
  tip.style.left = Math.min(left, box.width - tip.offsetWidth - 4) + 'px';
  tip.style.top = Math.max(0, ev.clientY - box.top - tip.offsetHeight - 10) + 'px';
}

buildControls();
loadStatus().then(loadPhotos).then(loadBattery);
setInterval(loadStatus, 5000);
setInterval(loadBattery, 15000);
</script>
</body></html>
)HTML";
