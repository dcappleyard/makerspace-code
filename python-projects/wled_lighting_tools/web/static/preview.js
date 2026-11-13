// Preview tab: the 3D view, fed either by what the sculpture is getting (Live)
// or by an in-browser-only render of any effect or show (Audition).
"use strict";

const Preview = (() => {
  let view = null, mode = "live", es = null, spin = false;
  const audOpts = {};

  function decode(b64) {
    const bin = atob(b64), a = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
    return a;
  }
  function connect() {
    if (es) es.close();
    es = new EventSource(mode === "live" ? "/api/stream" : "/api/audition/stream");
    es.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (mode === "live") {
        $("liveChip").textContent = m.state === "live" ? "● live" : m.state === "preset" ? "WLED preset (not shown)" : "idle";
      } else {
        $("liveChip").textContent = m.playing ? "● audition" : "audition: stopped";
        $("audNow").textContent = m.playing
          ? `${m.label}${m.count > 1 ? ` · ${m.index + 1}/${m.count}` : ""} › ${m.entry}${m.kind === "preset" ? " (WLED preset, not shown)" : ""} · ${fmtDur(m.remaining_s)} left`
          : "Nothing playing. Pick an effect or show and press Play.";
        showMsg("audErr", m.error || "");
      }
      if (m.frame) { view.setFrame(decode(m.frame)); view.setDim(false); } else view.setDim(true);
    };
    es.onerror = () => { $("liveChip").textContent = "reconnecting…"; };
  }
  function setMode(m) {
    mode = m;
    $("modeLive").classList.toggle("on", m === "live");
    $("modeAud").classList.toggle("on", m === "audition");
    $("audPanel").hidden = m !== "audition";
    $("audBanner").hidden = m !== "audition";
    if (view && !$("tab-preview").hidden) connect();
  }
  $("modeLive").onclick = () => setMode("live");
  $("modeAud").onclick = () => setMode("audition");

  for (const b of document.querySelectorAll("[data-view]")) b.onclick = () => view && view.setView(b.dataset.view);
  $("btnSpin").onclick = () => { spin = !spin; $("btnSpin").classList.toggle("on", spin); view && view.setSpin(spin); };

  // Only stream while the tab is showing (audition stops by itself when nobody watches).
  App.on("tab", (t) => {
    if (t === "preview") { if (view) { view.resize(); connect(); } }
    else if (es) { es.close(); es = null; }
  });

  // ---------------------------------------------------------- audition picker
  function renderAudPick() {
    const v = $("audItem").value;
    for (const k of Object.keys(audOpts)) delete audOpts[k];
    const fx = effectByName(v);
    $("audDesc").textContent = v.startsWith("show:") ? "Plays the saved show's effects in order, with its crossfades." : (fx ? fx.description : "");
    optionFields($("audOpts"), v.startsWith("show:") ? null : fx, audOpts);
    $("audSecsRow").hidden = !v.startsWith("show:");
  }
  function buildAudSelect() {
    const old = $("audItem").value;
    const sel = itemSelect(old || "", { shows: true, presets: false });
    sel.id = "audItem"; sel.setAttribute("aria-label", "Effect or show to audition");
    $("audItem").replaceWith(sel);
    sel.onchange = renderAudPick;
    renderAudPick();
  }
  App.on("settings", buildAudSelect);
  App.on("shows-changed", buildAudSelect);

  async function start(body) {
    showMsg("audErr", "");
    try { await api("POST", "/api/audition", body); } catch (e) { showMsg("audErr", e.message); }
  }
  $("audPlay").onclick = () => {
    const v = $("audItem").value;
    const secs = Number($("audSecs").value) || null;
    if (v.startsWith("show:")) start({ show: v.slice(5), seconds_each: secs });
    else start({ effect: v, options: { ...audOpts } });
  };
  $("audNext").onclick = () => api("POST", "/api/audition/next").catch((e) => showMsg("audErr", e.message));
  $("audStop").onclick = () => api("POST", "/api/audition/stop").catch((e) => showMsg("audErr", e.message));

  App.on("ready", async () => {
    const px = await api("GET", "/api/pixels");
    view = new SculptureView($("c"), px, { tooltip: $("tip") });
    view.setView("iso");
    if (!$("tab-preview").hidden) connect();
  });

  return {
    // Used by the show builder: audition an (unsaved) show body.
    auditionShow(label, showBody) {
      setMode("audition");
      showTab("preview");
      start({ show_body: showBody, label, seconds_each: Number($("audSecs").value) || null });
    },
  };
})();
