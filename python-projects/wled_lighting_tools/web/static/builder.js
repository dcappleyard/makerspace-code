// Show builder tab: create / rename / duplicate / delete shows and edit each
// show's effects list and its own timing and brightness.
"use strict";

(() => {
  let current = null;                     // name of the show being edited
  const NAME_RE = /^[a-z0-9_-]{1,32}$/;

  const S = () => App.settings;
  const shows = () => S().shows;
  function usedBy(name) {
    const why = [];
    if (S().schedule.default_show === name) why.push("it's the default show");
    S().schedule.windows.forEach((w, i) => { if (w.show === name) why.push(`window #${i + 1} plays it`); });
    return why;
  }
  function changed() { App.emit("shows-changed"); markDirty(); }

  // ---------------------------------------------------------- show list
  function renderList() {
    const ul = $("showList");
    ul.replaceChildren();
    const names = showNames();
    if (!names.includes(current)) current = names[0] || null;
    for (const n of names) {
      const sh = shows()[n];
      const tags = [];
      if (S().schedule.default_show === n) tags.push("default");
      const wins = S().schedule.windows.filter((w) => (w.show || S().schedule.default_show) === n).length;
      if (wins) tags.push(`${wins} window${wins > 1 ? "s" : ""}`);
      const b = el("button", { class: "showitem" + (n === current ? " active" : ""), "aria-current": n === current ? "true" : null },
        el("span", { class: "nm" }, n),
        el("span", { class: "muted small" }, `${sh.effects.length} effect${sh.effects.length === 1 ? "" : "s"}${tags.length ? " · " + tags.join(" · ") : ""}`));
      b.onclick = () => { current = n; render(); };
      ul.append(el("li", {}, b));
    }
  }
  function uniqueName(base) {
    let n = base, i = 2;
    while (shows()[n]) n = `${base}-${i++}`;
    return n;
  }
  $("newShow").onclick = () => {
    const name = uniqueName("new-show");
    shows()[name] = { effects: [{ item: App.effects[0] ? App.effects[0].name : "", minutes: null, options: {} }],
      scale: null, minutes_each: null, shuffle: null, transition_seconds: null };
    current = name; render(); changed();
    $("showName").focus(); $("showName").select();
  };
  $("dupShow").onclick = () => {
    if (!current) return;
    const name = uniqueName(current + "-copy");
    shows()[name] = JSON.parse(JSON.stringify(shows()[current]));
    current = name; render(); changed();
  };
  $("delShow").onclick = () => {
    if (!current) return;
    const why = usedBy(current);
    if (why.length) { showMsg("bErr", `Can't delete ${current}: ${why.join(", ")}. Change that in the Scheduler tab first.`); return; }
    if (!confirm(`Delete show "${current}"? (Not saved until you press Save & apply.)`)) return;
    delete shows()[current];
    current = null; render(); changed();
  };

  // Rename keeps order and updates the windows / default that point at it.
  function rename(oldN, newN) {
    if (newN === oldN) return true;
    if (!NAME_RE.test(newN)) { showMsg("bErr", "Show names: lowercase letters, digits, - or _ (max 32)."); return false; }
    if (shows()[newN]) { showMsg("bErr", `There's already a show called ${newN}.`); return false; }
    const out = {};
    for (const [k, v] of Object.entries(shows())) out[k === oldN ? newN : k] = v;
    S().shows = out;
    if (S().schedule.default_show === oldN) S().schedule.default_show = newN;
    for (const w of S().schedule.windows) if (w.show === oldN) w.show = newN;
    current = newN;
    showMsg("bErr", "");
    return true;
  }

  // ---------------------------------------------------------- editor
  function renderEditor() {
    const box = $("showEditor");
    $("showEmpty").hidden = !!current;
    box.hidden = !current;
    if (!current) return;
    const sh = shows()[current];
    const sc = S().schedule;

    const name = $("showName");
    name.value = current;
    name.onchange = () => { if (rename(current, name.value.trim())) { render(); changed(); } else name.value = current; };

    const why = usedBy(current);
    $("delShow").title = why.length ? `Can't delete: ${why.join(", ")}` : "Delete this show";
    $("showUsed").textContent = why.length ? `Used: ${why.join(", ")}.` : "Not used by any window yet.";

    // per-show overrides (blank = global)
    for (const inp of document.querySelectorAll("#showOverrides [data-k]")) {
      const k = inp.dataset.k;
      if (inp.tagName === "SELECT") {
        inp.value = sh[k] === null || sh[k] === undefined ? "" : String(sh[k]);
        inp.options[0].textContent = `global (${sc[k] ? "on" : "off"})`;
        inp.onchange = () => { sh[k] = inp.value === "" ? null : inp.value === "true"; markDirty(); };
      } else {
        inp.value = fmtVal(sh[k]);
        inp.placeholder = `global: ${fmtVal(sc[k])}`;
        inp.oninput = () => { sh[k] = inp.value === "" ? null : Number(inp.value); markDirty(); renderEffects(); };
      }
    }
    renderEffects();
  }

  function renderEffects() {
    const sh = shows()[current];
    const sc = S().schedule;
    const defMin = sh.minutes_each ?? sc.minutes_each ?? 10;
    const ul = $("fxList");
    ul.replaceChildren();
    sh.effects.forEach((e, i) => {
      const isWled = e.item.startsWith("wled:");
      const sel = itemSelect(isWled ? "wled:" : e.item);
      sel.setAttribute("aria-label", "effect");
      if (!isWled && !effectByName(e.item)) sel.prepend(el("option", { value: e.item, selected: true }, `${e.item} (missing — not in this build; rebuild the image)`));
      const preset = el("input", { type: "number", min: "1", value: isWled ? e.item.slice(5) : "1", "aria-label": "preset id", hidden: !isWled, class: "preset" });
      const mins = el("input", { type: "number", min: "0.5", step: "0.5", value: fmtVal(e.minutes), placeholder: String(defMin), title: "minutes (blank = show default)", "aria-label": "minutes" });
      const up = el("button", { class: "small", title: "move up", disabled: i === 0 }, "↑");
      const down = el("button", { class: "small", title: "move down", disabled: i === sh.effects.length - 1 }, "↓");
      const rm = el("button", { class: "small", title: "remove", disabled: sh.effects.length < 2 }, "✕");
      const fx = effectByName(e.item);
      e.options = e.options || {};
      const nOpts = Object.keys(e.options).length;
      const optBtn = el("button", { class: "small" + (nOpts ? " on" : ""), hidden: !(fx && fx.options) }, nOpts ? `options (${nOpts})` : "options");
      const optBox = el("div", { class: "opts", hidden: true });
      const desc = el("div", { class: "desc", hidden: true }, fx ? fx.description : "");
      optBtn.onclick = () => { optBox.hidden = !optBox.hidden; desc.hidden = optBox.hidden; };
      optionFields(optBox, fx, e.options, markDirty);

      sel.onchange = () => { e.item = sel.value === "__wled" ? "wled:" + (preset.value || "1") : sel.value; e.options = {}; renderEffects(); markDirty(); };
      preset.oninput = () => { e.item = "wled:" + preset.value; markDirty(); };
      mins.oninput = () => { e.minutes = mins.value === "" ? null : Number(mins.value); markDirty(); };
      up.onclick = () => { sh.effects.splice(i - 1, 0, sh.effects.splice(i, 1)[0]); renderEffects(); markDirty(); };
      down.onclick = () => { sh.effects.splice(i + 1, 0, sh.effects.splice(i, 1)[0]); renderEffects(); markDirty(); };
      rm.onclick = () => { sh.effects.splice(i, 1); renderEffects(); markDirty(); };

      ul.append(el("li", {},
        el("div", { class: "head" }, el("span", { class: "num" }, `${i + 1}`), sel, preset, mins,
          el("span", { class: "muted" }, "min"), optBtn, up, down, rm),
        desc, optBox));
    });
    const total = sh.effects.reduce((a, e) => a + (e.minutes ?? defMin), 0);
    $("fxTotal").textContent = `One pass through this show takes about ${Math.round(total)} min.`;
  }
  $("addFx").onclick = () => {
    shows()[current].effects.push({ item: App.effects[0] ? App.effects[0].name : "", minutes: null, options: {} });
    renderEffects(); markDirty();
  };

  // ---------------------------------------------------------- actions
  $("auditionShow").onclick = () => Preview.auditionShow(current, shows()[current]);
  $("playShow").onclick = () => {
    const saved = JSON.parse(App.savedJson).shows[current];
    if (!saved || JSON.stringify(saved) !== JSON.stringify(shows()[current])) {
      showMsg("bErr", "Save & apply first: the sculpture plays the saved version of a show.");
      return;
    }
    cmd("play", { show: current }, "bErr");
  };

  function render() { renderList(); renderEditor(); }
  App.on("settings", render);
  App.on("shows-changed", renderList);
})();
