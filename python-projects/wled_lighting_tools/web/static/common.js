// Shared dashboard plumbing: API, DOM helpers, time formatting, tabs, the
// now-playing bar, and the settings model (load / dirty / check / save).
"use strict";

const $ = (id) => document.getElementById(id);
const App = {
  tz: undefined,
  status: null, statusAt: 0,
  effects: [],                 // [{name, description, options}]
  settings: null, savedJson: "",
  on(ev, fn) { document.addEventListener(ev, (e) => fn(e.detail)); },
  emit(ev, detail) { document.dispatchEvent(new CustomEvent(ev, { detail })); },
};

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
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids) if (k !== null && k !== undefined && k !== false) e.append(k);
  return e;
}
const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: App.tz }) : "—";
const fmtDay = (iso) => new Date(iso + "T12:00:00").toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" });
function fmtDayTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso), now = new Date();
  const same = d.toLocaleDateString([], { timeZone: App.tz }) === now.toLocaleDateString([], { timeZone: App.tz });
  return same ? fmtTime(iso) : d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: App.tz });
}
function fmtDur(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), r = s % 60;
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(r).padStart(2, "0")}`;
}
const fmtVal = (v) => v === null || v === undefined ? "" : (typeof v === "object" ? JSON.stringify(v) : String(v));
function showMsg(id, text) { const m = $(id); if (!m) return; m.textContent = text || ""; m.hidden = !text; }
function setChip(id, cls, text) { $(id).className = "chip " + cls; $(id).querySelector("span:last-child").textContent = text; }
const effectByName = (n) => App.effects.find((e) => e.name === n);
const showNames = () => Object.keys((App.settings && App.settings.shows) || {});

// Option inputs for an effect's OPTIONS; `values` is edited in place.
function optionFields(container, effect, values, onChange) {
  container.replaceChildren();
  const def = effect && effect.options;
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

// <select> of effects (+ optional "WLED preset…" and shows), with a value.
function itemSelect(value, { presets = true, shows = false, effects = true } = {}) {
  const sel = el("select");
  if (shows) {
    const g = el("optgroup", { label: "Shows" });
    for (const n of showNames()) g.append(el("option", { value: "show:" + n, selected: value === "show:" + n }, n));
    sel.append(g);
  }
  if (effects) {
    const g = shows ? el("optgroup", { label: "Effects" }) : sel;
    for (const e of App.effects) g.append(el("option", { value: e.name, selected: e.name === value }, e.name));
    if (presets) g.append(el("option", { value: "__wled", selected: String(value).startsWith("wled:") }, "WLED preset…"));
    if (g !== sel) sel.append(g);
  }
  return sel;
}

// ------------------------------------------------------------ tabs
const TABS = ["scheduler", "preview", "builder"];
function showTab(name) {
  if (!TABS.includes(name)) name = "scheduler";
  for (const t of TABS) {
    $("tab-" + t).hidden = t !== name;
    $("tabbtn-" + t).classList.toggle("active", t === name);
    $("tabbtn-" + t).setAttribute("aria-selected", t === name);
  }
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  App.emit("tab", name);
}
for (const t of TABS) $("tabbtn-" + t).onclick = () => showTab(t);
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

// ------------------------------------------------------------ status + now bar
function renderNowBar() {
  const s = App.status;
  if (!s) return;
  App.tz = s.tz;
  if (s.on) {
    const how = s.forced ? "forced on" : (s.window && s.window.manual ? "on (manual)" : "on");
    setChip("stateChip", "ok", s.window && s.window.end ? `${how} until ${fmtTime(s.window.end)}` : how);
  } else if (s.suppressed_until) {
    setChip("stateChip", "warn", `off until ${fmtDayTime(s.suppressed_until)}`);
  } else {
    setChip("stateChip", "", s.next_window ? `off · ${s.next_window.show || ""} at ${fmtDayTime(s.next_window.start)}` : "off");
  }
  if (s.preview) setChip("wledChip", "warn", "preview mode (no WLED)");
  else if (s.wled.reachable === null) setChip("wledChip", "", "WLED: checking…");
  else if (s.wled.reachable) setChip("wledChip", "ok", `WLED ${s.wled.info && s.wled.info.ver ? s.wled.info.ver : "ok"}`);
  else setChip("wledChip", "bad", "WLED unreachable");

  const e = s.entry;
  const left = e ? e.remaining_s - (Date.now() - App.statusAt) / 1000 : 0;
  $("nbShow").textContent = s.on ? (s.show || "—") : "Off";
  $("nbEffect").textContent = s.on && e ? e.label : "";
  $("nbSep").hidden = !(s.on && e);
  $("nbLeft").textContent = s.on && e ? `${fmtDur(left)} left · next ${s.next || "—"}` : "";
  $("nbSkip").disabled = !s.on;
}
async function pollStatus() {
  try {
    App.status = await api("GET", "/api/status"); App.statusAt = Date.now();
    renderNowBar(); App.emit("status", App.status);
  } catch (e) { setChip("stateChip", "bad", "dashboard: " + e.message); }
}
setInterval(pollStatus, 2000);
setInterval(() => { renderNowBar(); App.emit("tick"); }, 1000);

async function cmd(name, body, errId) {
  showMsg(errId, "");
  try {
    const j = await api("POST", `/api/cmd/${name}`, body || {});
    App.status = j.status; App.statusAt = Date.now(); renderNowBar(); App.emit("status", App.status);
    return j;
  } catch (e) { showMsg(errId, e.message); return null; }
}
$("nbSkip").onclick = () => cmd("skip", {}, "ctlErr");

// ------------------------------------------------------------ settings model
function markDirty() {
  const dirty = JSON.stringify(App.settings) !== App.savedJson;
  $("saveBar").hidden = !dirty;
  for (const t of ["scheduler", "builder"]) $("tabbtn-" + t).classList.toggle("dirty", dirty);
  checkLater();
}
let checkTimer = null;
function checkLater() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    try {
      const j = await api("PUT", "/api/settings?dry_run=true", App.settings);
      showMsg("setErr", ""); App.emit("schedule", j.schedule);
    } catch (e) { showMsg("setErr", e.message); }
  }, 500);
}
function renderProgram() {
  const pr = App.status && App.status.program;
  if (!pr) return;
  const name = pr.file.split("/").slice(-2).join("/");
  showMsg("progError", pr.error ? `${name} couldn't be loaded, so the sculpture is still playing the previous program:\n${pr.error}` : "");
  showMsg("progWarn", !pr.error && pr.warning ? `${name}: ${pr.warning} (skipped until it's available — rebuild the image if it's a new effect)` : "");
  $("saveFile").textContent = pr.tracked ? `Saves to ${name}; commit it yourself.` : `Saves to ${name}.`;
  // Changed on disk (git pull, hand edit, another dashboard)?
  if (!App.settings || pr.error || pr.mtime == null || App.settings.mtime == null || pr.mtime === App.settings.mtime) return;
  if (App.diskSeen === pr.mtime) return;
  App.diskSeen = pr.mtime;
  if (JSON.stringify(App.settings) === App.savedJson) {
    loadSettings().then(() => { showMsg("setOk", `${name} changed on disk; reloaded.`); $("saveBar").hidden = false;
      setTimeout(() => { showMsg("setOk", ""); if (JSON.stringify(App.settings) === App.savedJson) $("saveBar").hidden = true; }, 4000); });
  } else {
    $("diskText").textContent = `${name} changed on disk (git pull or a hand edit?) while you have unsaved edits here.`;
    $("diskNote").hidden = false;
  }
}
App.on("status", renderProgram);
$("diskTake").onclick = () => { $("diskNote").hidden = true; loadSettings(); };
$("diskKeep").onclick = () => {
  $("diskNote").hidden = true;
  App.settings.mtime = App.status.program.mtime;      // saving now overwrites the disk version
  App.savedJson = JSON.stringify({ ...JSON.parse(App.savedJson), mtime: App.settings.mtime });
  markDirty();
};

async function loadSettings() {
  App.settings = await api("GET", "/api/settings");
  App.diskSeen = App.settings.mtime;
  $("diskNote").hidden = true; $("btnForce").hidden = true;
  App.savedJson = JSON.stringify(App.settings);
  $("saveBar").hidden = true;
  for (const t of ["scheduler", "builder"]) $("tabbtn-" + t).classList.remove("dirty");
  showMsg("setErr", "");
  App.emit("settings", App.settings);
  App.emit("schedule", await api("GET", "/api/schedule"));
}
async function saveSettings(force) {
  showMsg("setErr", ""); showMsg("setOk", "");
  $("btnSave").disabled = true; $("btnForce").hidden = true;
  try {
    const j = await api("PUT", "/api/settings" + (force === true ? "?force=true" : ""), App.settings);
    App.diskSeen = j.settings.mtime;
    App.settings = j.settings; App.savedJson = JSON.stringify(App.settings);
    $("saveBar").hidden = false;
    for (const t of ["scheduler", "builder"]) $("tabbtn-" + t).classList.remove("dirty");
    App.emit("settings", App.settings); App.emit("schedule", j.schedule);
    App.status = j.status; App.statusAt = Date.now(); renderNowBar(); App.emit("status", App.status);
    showMsg("setOk", "Saved to config.yaml and applied.");
    setTimeout(() => { showMsg("setOk", ""); if (JSON.stringify(App.settings) === App.savedJson) $("saveBar").hidden = true; }, 3000);
  } catch (e) {
    showMsg("setErr", e.message);
    if (/changed on disk/.test(e.message)) $("btnForce").hidden = false;
  }
  $("btnSave").disabled = false;
}
$("btnForce").onclick = () => saveSettings(true);
$("btnSave").onclick = saveSettings;
$("btnRevert").onclick = loadSettings;
window.addEventListener("beforeunload", (ev) => {
  if (App.settings && JSON.stringify(App.settings) !== App.savedJson) ev.preventDefault();
});

// ------------------------------------------------------------ start
App.start = async () => {
  App.effects = await api("GET", "/api/effects");
  await pollStatus();
  try { await loadSettings(); } catch (e) { showMsg("setErr", "settings: " + e.message); }
  showTab(location.hash.slice(1));
  App.emit("ready");
};
