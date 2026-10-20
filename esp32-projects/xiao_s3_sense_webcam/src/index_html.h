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

buildControls();
loadStatus().then(loadPhotos);
setInterval(loadStatus, 5000);
</script>
</body></html>
)HTML";
