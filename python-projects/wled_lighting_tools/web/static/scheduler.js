// Scheduler tab: what's playing, controls, on/off windows, global settings, log.
"use strict";

(() => {
  // ---------------------------------------------------------- now + controls
  function renderNow(s) {
    if (!s) return;
    const e = s.entry;
    $("nowShow").textContent = s.on ? `${s.show || "—"}${e ? " › " + e.label : ""}` : "Off";
    const left = e ? e.remaining_s - (Date.now() - App.statusAt) / 1000 : 0;
    $("nowSub").textContent = s.on && e ? `${fmtDur(left)} left · next: ${s.next || "—"}` : "";
    showMsg("showErr", e && e.error ? e.error : "");
    const kv = $("nowKv");
    kv.replaceChildren();
    const add = (k, v) => kv.append(el("dt", {}, k), el("dd", {}, v));
    if (e && e.options && Object.keys(e.options).length)
      add("Options", Object.entries(e.options).map(([k, v]) => `${k}=${fmtVal(v)}`).join(", "));
    if (s.window) add("Window", `${fmtDayTime(s.window.start)} → ${s.window.end ? fmtTime(s.window.end) : "—"}`);
    if (s.show_override) add("Show override", `${s.show_override.show}${s.show_override.until ? " until " + fmtTime(s.show_override.until) : ""}`);
    if (s.next_window) add("Next window", `${fmtDayTime(s.next_window.start)} → ${fmtTime(s.next_window.end)} · ${s.next_window.show || ""}`);
    add("Sun", `sunrise ${fmtTime(s.sun.sunrise)} · sunset ${fmtTime(s.sun.sunset)}`);
    add("Sending to", s.targets.join(", "));
    if (s.pending.length) add("Retrying", s.pending.join(", "));
    if (s.wled.reachable === false && s.wled.error) add("WLED error", s.wled.error);

    $("btnOff").disabled = !s.on || s.forced;
    $("btnResume").hidden = !(s.manual || s.suppressed_until || s.show_override);
    if (document.activeElement !== $("scale")) { $("scale").value = s.scale; $("scaleVal").textContent = s.scale.toFixed(2); }
  }
  App.on("status", renderNow);
  App.on("tick", () => renderNow(App.status));

  function fillShowSelect(sel, withDefault) {
    const keep = sel.value;
    sel.replaceChildren();
    if (withDefault) sel.append(el("option", { value: "" }, `default (${App.settings.schedule.default_show})`));
    for (const n of showNames()) sel.append(el("option", { value: n }, n));
    if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
  }

  $("btnOn").onclick = () => cmd("on", { minutes: Number($("onMinutes").value) || 60, show: $("onShow").value || undefined }, "ctlErr");
  $("btnOff").onclick = () => cmd("off", {}, "ctlErr");
  $("btnResume").onclick = () => cmd("resume", {}, "ctlErr");
  let scaleTimer = null;
  $("scale").oninput = () => {
    $("scaleVal").textContent = Number($("scale").value).toFixed(2);
    clearTimeout(scaleTimer);
    scaleTimer = setTimeout(() => cmd("scale", { value: Number($("scale").value) }, "ctlErr"), 120);
  };

  // Play now: a show or an effect
  const playOpts = {};
  function renderPlay() {
    const v = $("playItem").value;
    for (const k of Object.keys(playOpts)) delete playOpts[k];
    const box = $("playOpts");
    if (v.startsWith("show:")) {
      $("playDesc").textContent = "Switch to this show until the window ends (or for the minutes given), then back to the schedule.";
      box.replaceChildren();
    } else if (v === "__wled") {
      $("playDesc").textContent = "Hand over to a WLED preset.";
      box.replaceChildren(el("label", {}, "Preset id", el("input", { id: "playPreset", type: "number", min: "1", value: "1" })));
    } else {
      const fx = effectByName(v);
      $("playDesc").textContent = fx ? fx.description : "";
      optionFields(box, fx, playOpts);
    }
  }
  function buildPlaySelect() {
    const old = $("playItem").value;
    const sel = itemSelect(old || "", { shows: true });
    sel.id = "playItem"; sel.setAttribute("aria-label", "Show or effect to play");
    $("playItem").replaceWith(sel);
    sel.onchange = renderPlay;
    renderPlay();
  }
  $("btnPlay").onclick = () => {
    const v = $("playItem").value;
    const minutes = Number($("playMinutes").value) || undefined;
    if (v.startsWith("show:")) return cmd("play", { show: v.slice(5), minutes }, "ctlErr");
    const item = v === "__wled" ? "wled:" + ($("playPreset").value || "1") : v;
    cmd("play", { effect: item, minutes, options: { ...playOpts } }, "ctlErr");
  };

  // ---------------------------------------------------------- windows + globals
  function renderSettings() {
    const S = App.settings, sc = S.schedule;
    fillShowSelect($("onShow"), true);
    buildPlaySelect();

    const w = $("windows");
    w.replaceChildren();
    sc.windows.forEach((win, i) => {
      const on = el("input", { value: win.on, "aria-label": "on time" });
      const off = el("input", { value: win.off, "aria-label": "off time" });
      const show = el("select", { "aria-label": "show" });
      show.append(el("option", { value: "" }, `default (${sc.default_show})`));
      for (const n of showNames()) show.append(el("option", { value: n, selected: win.show === n }, n));
      if (win.show && !showNames().includes(win.show)) show.append(el("option", { value: win.show, selected: true }, `${win.show} (missing)`));
      on.oninput = () => { win.on = on.value; markDirty(); };
      off.oninput = () => { win.off = off.value; markDirty(); };
      show.onchange = () => { win.show = show.value || null; markDirty(); };
      const rm = el("button", { class: "small", title: "remove window", disabled: sc.windows.length < 2 }, "✕");
      rm.onclick = () => { sc.windows.splice(i, 1); renderSettings(); markDirty(); };
      w.append(el("div", { class: "win" },
        el("span", { class: "muted" }, "on"), on, el("span", { class: "muted" }, "off"), off,
        el("span", { class: "muted" }, "plays"), show, rm));
    });

    const ds = $("defaultShow");
    ds.replaceChildren(...showNames().map((n) => el("option", { value: n, selected: n === sc.default_show }, n)));
    ds.onchange = () => { sc.default_show = ds.value; renderSettings(); markDirty(); };

    for (const inp of document.querySelectorAll("#tab-scheduler [data-k]")) {
      const k = inp.dataset.k;
      if (inp.type === "checkbox") { inp.checked = !!sc[k]; inp.onchange = () => { sc[k] = inp.checked; markDirty(); }; }
      else {
        inp.value = fmtVal(sc[k]);
        inp.oninput = () => { sc[k] = inp.value === "" ? null : Number(inp.value); markDirty(); };
      }
    }
    $("legacyNote").hidden = !S.legacy;
  }
  $("addWin").onclick = () => {
    App.settings.schedule.windows.push({ on: "sunset", off: "23:00", show: null });
    renderSettings(); markDirty();
  };
  App.on("settings", renderSettings);
  App.on("shows-changed", renderSettings);       // from the builder (rename/add/delete)

  App.on("schedule", (rows) => {
    const tb = $("sched");
    tb.replaceChildren();
    for (const r of rows) {
      const wins = r.windows.map(([a, b, show]) => `${fmtTime(a)}–${fmtTime(b)} ${show || ""}`).join(", ") || "—";
      tb.append(el("tr", {}, el("td", {}, fmtDay(r.date)), el("td", {}, fmtTime(r.sunset)), el("td", {}, wins)));
    }
  });

  // ---------------------------------------------------------- log
  async function pollLog() {
    if ($("tab-scheduler").hidden) return;
    try {
      const j = await api("GET", "/api/log?n=150");
      const box = $("log"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 4;
      box.textContent = j.lines.join("\n");
      if (atEnd) box.scrollTop = box.scrollHeight;
    } catch (_) { /* the status chip shows errors */ }
  }
  setInterval(pollLog, 4000);
  App.on("tab", (t) => { if (t === "scheduler") pollLog(); });
})();
