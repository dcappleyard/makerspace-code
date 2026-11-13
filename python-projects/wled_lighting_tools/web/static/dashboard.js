// Sculpture dashboard: status + controls, live view, settings editor.
"use strict";

const $ = (id) => document.getElementById(id);
let TZ = undefined;
let SHOWS = [];                       // [{name, description, options}]
let status = null, statusAt = 0;
let settings = null, savedJson = "";

// ------------------------------------------------------------ helpers
async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let j = null;
  try { j = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) throw new Error((j && j.detail) || `${r.status} ${r.statusText}`);
  return j;
}
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k);
  return e;
}
const time = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: TZ }) : "—";
const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" });
function dayTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso), now = new Date();
  const sameDay = d.toLocaleDateString([], { timeZone: TZ }) === now.toLocaleDateString([], { timeZone: TZ });
  return sameDay ? time(iso) : d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: TZ });
}
function dur(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), r = s % 60;
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(r).padStart(2, "0")}`;
}
function showMsg(id, text) { const m = $(id); m.textContent = text || ""; m.hidden = !text; }
function fmtVal(v) { return v === null || v === undefined ? "" : (typeof v === "object" ? JSON.stringify(v) : String(v)); }
function chip(id, cls, text) { $(id).className = "chip " + cls; $(id).querySelector("span:last-child").textContent = text; }

// ------------------------------------------------------------ status
function renderStatus() {
  const s = status;
  if (!s) return;
  TZ = s.tz;
  if (s.on) {
    const how = s.forced ? "forced on" : (s.window && s.window.manual ? "on (manual)" : "on");
    chip("stateChip", "ok", s.window && s.window.end ? `${how} until ${time(s.window.end)}` : how);
  } else if (s.suppressed_until) {
    chip("stateChip", "warn", `off until ${dayTime(s.suppressed_until)}`);
  } else {
    chip("stateChip", "", s.next_window ? `off · on at ${dayTime(s.next_window.start)}` : "off");
  }
  if (s.preview) chip("wledChip", "warn", "preview mode (no WLED)");
  else if (s.wled.reachable === null) chip("wledChip", "", "WLED: checking…");
  else if (s.wled.reachable) chip("wledChip", "ok", `WLED ${s.wled.info && s.wled.info.ver ? s.wled.info.ver : "ok"}`);
  else chip("wledChip", "bad", "WLED unreachable");

  const e = s.entry;
  const left = e ? e.remaining_s - (Date.now() - statusAt) / 1000 : 0;
  $("nowShow").textContent = s.on ? (e ? e.label : "—") : "Off";
  $("nowSub").textContent = s.on && e ? `${dur(left)} left · next: ${s.next || "—"}` : "";
  showMsg("showErr", e && e.error ? e.error : "");
  const kv = $("nowKv");
  kv.replaceChildren();
  const add = (k, v) => kv.append(el("dt", {}, k), el("dd", {}, v));
  if (e && e.options && Object.keys(e.options).length)
    add("Options", Object.entries(e.options).map(([k, v]) => `${k}=${fmtVal(v)}`).join(", "));
  if (s.window) add("Window", `${dayTime(s.window.start)} → ${s.window.end ? time(s.window.end) : "—"}`);
  if (s.next_window) add("Next window", `${dayTime(s.next_window.start)} → ${time(s.next_window.end)}`);
  add("Sun", `sunrise ${time(s.sun.sunrise)} · sunset ${time(s.sun.sunset)}`);
  add("Sending to", s.targets.join(", "));
  if (s.pending.length) add("Retrying", s.pending.join(", "));
  if (s.wled.reachable === false && s.wled.error) add("WLED error", s.wled.error);

  $("btnSkip").disabled = !s.on;
  $("btnOff").disabled = !s.on || s.forced;
  $("btnResume").hidden = !(s.manual || s.suppressed_until);
  $("btnOn").disabled = s.on && !s.manual;
  if (document.activeElement !== $("scale")) { $("scale").value = s.scale; $("scaleVal").textContent = s.scale.toFixed(2); }
}

async function pollStatus() {
  try {
    status = await api("GET", "/api/status"); statusAt = Date.now();
    renderStatus();
  } catch (e) { chip("stateChip", "bad", "dashboard: " + e.message); }
}
setInterval(pollStatus, 2000);
setInterval(renderStatus, 1000);              // countdown between polls

async function pollLog() {
  try {
    const j = await api("GET", "/api/log?n=150");
    const box = $("log"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 4;
    box.textContent = j.lines.join("\n");
    if (atEnd) box.scrollTop = box.scrollHeight;
  } catch (_) { /* status chip shows errors */ }
}
setInterval(pollLog, 4000);

// ------------------------------------------------------------ controls
async function cmd(name, body) {
  showMsg("ctlErr", "");
  try {
    const j = await api("POST", `/api/cmd/${name}`, body || {});
    status = j.status; statusAt = Date.now(); renderStatus();
    return j;
  } catch (e) { showMsg("ctlErr", e.message); }
}
$("btnSkip").onclick = () => cmd("skip");
$("btnOn").onclick = () => cmd("on", { minutes: Number($("onMinutes").value) || 60 });
$("btnOff").onclick = () => cmd("off");
$("btnResume").onclick = () => cmd("resume");
let scaleTimer = null;
$("scale").oninput = () => {
  $("scaleVal").textContent = Number($("scale").value).toFixed(2);
  clearTimeout(scaleTimer);
  scaleTimer = setTimeout(() => cmd("scale", { value: Number($("scale").value) }), 120);
};
$("btnScaleSave").onclick = async () => {
  if (!settings) return;
  settings.scale = Number($("scale").value);
  renderSettings();
  await saveSettings();
};

function optionFields(container, show, values, onChange) {
  container.replaceChildren();
  const def = show && show.options;
  if (!def) return;
  for (const [k, d] of Object.entries(def)) {
    const inp = el("input", { value: fmtVal(values[k]), placeholder: d === null ? "auto" : fmtVal(d) });
    inp.oninput = () => {
      if (inp.value.trim() === "") delete values[k]; else values[k] = inp.value;
      onChange && onChange();
    };
    container.append(el("label", {}, k, inp));
  }
}
const playOpts = {};
function renderPlay() {
  const v = $("playItem").value;
  const show = SHOWS.find((s) => s.name === v);
  $("playDesc").textContent = show ? show.description : (v === "__wled" ? "Hand over to a WLED preset." : "");
  for (const k of Object.keys(playOpts)) delete playOpts[k];
  const box = $("playOpts");
  if (v === "__wled") {
    box.replaceChildren(el("label", {}, "Preset id", el("input", { id: "playPreset", type: "number", min: "1", value: "1" })));
  } else optionFields(box, show, playOpts);
}
$("playItem").onchange = renderPlay;
$("btnPlay").onclick = () => {
  let item = $("playItem").value;
  if (item === "__wled") item = "wled:" + ($("playPreset").value || "1");
  const minutes = Number($("playMinutes").value) || undefined;
  cmd("play", { item, minutes, options: { ...playOpts } });
};

// ------------------------------------------------------------ live view
let view = null;
fetch("/api/pixels").then((r) => r.json()).then((px) => {
  view = new SculptureView($("c"), px, { tooltip: $("tip") });
  view.setView("iso");
  connect();
});
for (const b of document.querySelectorAll("[data-view]")) b.onclick = () => view && view.setView(b.dataset.view);
let spin = false;
$("btnSpin").onclick = () => { spin = !spin; $("btnSpin").classList.toggle("on", spin); view && view.setSpin(spin); };

function connect() {
  const es = new EventSource("/api/stream");
  es.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    $("liveChip").textContent = m.state === "live" ? "● live" : m.state === "preset" ? "WLED preset (not shown)" : "idle";
    if (m.frame) {
      const bin = atob(m.frame), a = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
      view.setFrame(a); view.setDim(false);
    } else view.setDim(true);
  };
  es.onerror = () => { $("liveChip").textContent = "reconnecting…"; };
}

// ------------------------------------------------------------ settings
function markDirty() {
  const dirty = JSON.stringify(settings) !== savedJson;
  $("dirty").hidden = !dirty;
  checkLater();
}
function renderSettings() {
  const w = $("windows");
  w.replaceChildren();
  settings.windows.forEach((win, i) => {
    const on = el("input", { value: win.on, "aria-label": "on time" });
    const off = el("input", { value: win.off, "aria-label": "off time" });
    on.oninput = () => { win.on = on.value; markDirty(); };
    off.oninput = () => { win.off = off.value; markDirty(); };
    const rm = el("button", { class: "small", title: "remove", disabled: settings.windows.length < 2 }, "✕");
    rm.onclick = () => { settings.windows.splice(i, 1); renderSettings(); markDirty(); };
    w.append(el("div", { class: "win" }, el("span", { class: "muted" }, "on"), on, el("span", { class: "muted" }, "off"), off, rm));
  });

  for (const inp of document.querySelectorAll("#scalars [data-k], #checks [data-k]")) {
    const k = inp.dataset.k;
    if (inp.type === "checkbox") { inp.checked = !!settings[k]; inp.onchange = () => { settings[k] = inp.checked; markDirty(); }; }
    else {
      inp.value = fmtVal(settings[k]);
      inp.oninput = () => { settings[k] = inp.value === "" ? null : Number(inp.value); markDirty(); };
    }
  }

  const rot = $("rot");
  rot.replaceChildren();
  settings.rotation.forEach((e, i) => {
    const isWled = e.item.startsWith("wled:");
    const sel = el("select", { "aria-label": "show" });
    for (const s of SHOWS) sel.append(el("option", { value: s.name, selected: s.name === e.item }, s.name));
    sel.append(el("option", { value: "__wled", selected: isWled }, "WLED preset…"));
    if (!isWled && !SHOWS.some((s) => s.name === e.item)) sel.prepend(el("option", { value: e.item, selected: true }, `${e.item} (missing)`));
    const preset = el("input", { type: "number", min: "1", value: isWled ? e.item.slice(5) : "1", "aria-label": "preset id", style: isWled ? "" : "display:none" });
    const mins = el("input", { type: "number", min: "0.5", step: "0.5", value: fmtVal(e.minutes),
      placeholder: `${settings.minutes_each ?? 10}`, title: "minutes (blank = default)", "aria-label": "minutes" });
    const up = el("button", { class: "small", title: "move up", disabled: i === 0 }, "↑");
    const down = el("button", { class: "small", title: "move down", disabled: i === settings.rotation.length - 1 }, "↓");
    const rm = el("button", { class: "small", title: "remove" }, "✕");
    const show = SHOWS.find((s) => s.name === e.item);
    const nOpts = Object.keys(e.options || {}).length;
    const optBtn = el("button", { class: "small" + (nOpts ? " on" : ""), hidden: !(show && show.options) }, nOpts ? `options (${nOpts})` : "options");
    const optBox = el("div", { class: "opts", hidden: true });
    const desc = el("div", { class: "desc", hidden: true }, show ? show.description : "");
    optBtn.onclick = () => { optBox.hidden = !optBox.hidden; desc.hidden = optBox.hidden; };
    e.options = e.options || {};
    optionFields(optBox, show, e.options, markDirty);

    sel.onchange = () => {
      e.item = sel.value === "__wled" ? "wled:" + (preset.value || "1") : sel.value;
      e.options = {};
      renderSettings(); markDirty();
    };
    preset.oninput = () => { e.item = "wled:" + preset.value; markDirty(); };
    mins.oninput = () => { e.minutes = mins.value === "" ? null : Number(mins.value); markDirty(); };
    up.onclick = () => { settings.rotation.splice(i - 1, 0, settings.rotation.splice(i, 1)[0]); renderSettings(); markDirty(); };
    down.onclick = () => { settings.rotation.splice(i + 1, 0, settings.rotation.splice(i, 1)[0]); renderSettings(); markDirty(); };
    rm.onclick = () => { settings.rotation.splice(i, 1); renderSettings(); markDirty(); };

    rot.append(el("li", {},
      el("div", { class: "head" }, el("span", { class: "num" }, `${i + 1}`), sel, preset, mins,
        el("span", { class: "muted" }, "min"), optBtn, up, down, rm),
      desc, optBox));
  });
}
$("addWin").onclick = () => { settings.windows.push({ on: "sunset", off: "23:00" }); renderSettings(); markDirty(); };
$("addRot").onclick = () => { settings.rotation.push({ item: SHOWS[0] ? SHOWS[0].name : "", minutes: null, options: {} }); renderSettings(); markDirty(); };

function renderSchedule(rows) {
  const tb = $("sched");
  tb.replaceChildren();
  for (const r of rows) {
    const wins = r.windows.map(([a, b]) => `${time(a)}–${time(b)}`).join(", ") || "—";
    tb.append(el("tr", {}, el("td", {}, day(r.date)), el("td", {}, time(r.sunset)), el("td", {}, wins)));
  }
}

let checkTimer = null;
function checkLater() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    try {
      const j = await api("PUT", "/api/settings?dry_run=true", settings);
      showMsg("setErr", ""); renderSchedule(j.schedule);
    } catch (e) { showMsg("setErr", e.message); }
  }, 500);
}

async function loadSettings() {
  settings = await api("GET", "/api/settings");
  savedJson = JSON.stringify(settings);
  renderSettings(); $("dirty").hidden = true;
  showMsg("setErr", "");
  renderSchedule(await api("GET", "/api/schedule"));
}
async function saveSettings() {
  showMsg("setErr", ""); showMsg("setOk", "");
  $("btnSave").disabled = true;
  try {
    const j = await api("PUT", "/api/settings", settings);
    settings = j.settings; savedJson = JSON.stringify(settings);
    renderSettings(); renderSchedule(j.schedule); $("dirty").hidden = true;
    status = j.status; statusAt = Date.now(); renderStatus();
    showMsg("setOk", "Saved to config.yaml and applied.");
    setTimeout(() => showMsg("setOk", ""), 4000);
  } catch (e) { showMsg("setErr", e.message); }
  $("btnSave").disabled = false;
}
$("btnSave").onclick = saveSettings;
$("btnRevert").onclick = loadSettings;
window.addEventListener("beforeunload", (ev) => { if (settings && JSON.stringify(settings) !== savedJson) ev.preventDefault(); });

// ------------------------------------------------------------ start
(async () => {
  SHOWS = await api("GET", "/api/shows");
  const pi = $("playItem");
  for (const s of SHOWS) pi.append(el("option", { value: s.name }, s.name));
  pi.append(el("option", { value: "__wled" }, "WLED preset…"));
  renderPlay();
  await pollStatus();
  pollLog();
  try { await loadSettings(); } catch (e) { showMsg("setErr", "settings: " + e.message); }
})();
