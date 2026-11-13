"use strict";
// Shared 3D canvas view of the sculpture (plain script, defines global SculptureView).
// Used by preview/index.html and the web dashboard. No dependencies.
//
//   const view = new SculptureView(canvas, pixels, { tooltip: el | null });
//   view.setFrame(rgb)   view.setDim(bool)   view.setView("front"|"iso"|"top")
//   view.setSpin(bool)   view.resize()       view.setOptions({structure, unlit, exposure})
//
// Tooltip markup uses .sw (swatch) and .muted classes from the host page's CSS.
class SculptureView {
  static VIEWS = { front: [0, 0.08], iso: [0.6, 0.35], top: [0, Math.PI / 2 - 0.001] };
  static D = 160; // camera distance, inches

  constructor(canvas, pixels, { tooltip = null } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.tip = tooltip;
    this.pixels = pixels;
    this.colors = new Uint8Array(3 * pixels.length);
    this.dim = true;   // idle until the host says the stream is live
    this.cam = { az: 0.6, el: 0.35, zoom: 1, spin: false };
    this.opts = { structure: true, unlit: true, exposure: 1.2 };
    this.W = 0; this.H = 0; this.DPR = 1;
    this.projected = []; this.hover = -1; this.drag = null;
    this.buildStructure();
    this.bind();
    this.resize();
    this.last = performance.now();
    requestAnimationFrame(t => this.tick(t));
  }

  // ---------------------------------------------------------------- public API
  setFrame(rgb) { this.colors = rgb; }
  setDim(on) { this.dim = !!on; }
  setSpin(on) { this.cam.spin = !!on; }
  setView(name) {
    const v = SculptureView.VIEWS[name];
    if (!v) return;
    [this.cam.az, this.cam.el] = v; this.cam.zoom = 1;
  }
  setOptions(o) { Object.assign(this.opts, o); }
  resize() {
    const c = this.canvas;
    this.DPR = window.devicePixelRatio || 1;
    this.W = c.clientWidth; this.H = c.clientHeight;
    c.width = Math.round(this.W * this.DPR); c.height = Math.round(this.H * this.DPR);
    this.ctx.setTransform(this.DPR, 0, 0, this.DPR, 0, 0);
  }

  // ---------------------------------------------------------------- geometry
  buildStructure() {
    const pixels = this.pixels, groups = new Map();
    for (const p of pixels) {
      if (p.part !== "ring") continue;
      const k = p.output + ":" + p.base_pair;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(p);
    }
    const rings = [], stems = [];
    for (const ring of groups.values()) {
      // evenly spaced ring lights average to the ring's center
      const c = ring.reduce((a, p) => [a[0] + p.x / ring.length, a[1] + p.y / ring.length, p.z], [0, 0, 0]);
      const r = Math.hypot(ring[0].x - c[0], ring[0].y - c[1]);
      rings.push({ c, r });
      const d = Math.hypot(c[0], c[1]);
      const ux = c[0] / d, uy = c[1] / d;
      stems.push([[0, 0, c[2]], [c[0] - ux * r, c[1] - uy * r, c[2]]]);
    }
    const ztop = Math.max(...pixels.map(p => p.z)) + 3;
    this.structure = { rings, stems, rod: [[0, 0, 0], [0, 0, ztop]] };
    this.zc = ztop / 2;                  // frame ground (z=0) to the top of the rod
    const rmax = Math.max(...pixels.map(p => Math.hypot(p.x, p.y)));
    this.extent = Math.max(ztop, 2 * rmax) * 1.25;
  }

  // ---------------------------------------------------------------- camera
  project(x, y, z) {
    const cam = this.cam, D = SculptureView.D;
    const ca = Math.cos(cam.az), sa = Math.sin(cam.az);
    const ce = Math.cos(cam.el), se = Math.sin(cam.el);
    const x1 = x * ca + y * sa, y1 = -x * sa + y * ca, zz = z - this.zc;
    const up = zz * ce + y1 * se;
    const depth = y1 * ce - zz * se;
    const base = Math.min(this.W, this.H * 0.92) / this.extent * cam.zoom;
    const s = base * D / (D + depth);
    return [this.W / 2 + x1 * s, this.H * 0.46 - up * s, depth, s];   // nudged up, clear of a bottom toolbar
  }

  // ---------------------------------------------------------------- drawing
  line3(a, b) {
    const ctx = this.ctx, p = this.project(...a), q = this.project(...b);
    ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]);
  }

  draw() {
    const ctx = this.ctx, W = this.W, H = this.H, opts = this.opts, colors = this.colors;
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#07080b";
    ctx.fillRect(0, 0, W, H);

    // ground ring + +x marker
    ctx.strokeStyle = "rgba(120,130,150,0.18)"; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 64; i++) {
      const a = i / 64 * 2 * Math.PI, p = this.project(16 * Math.cos(a), 16 * Math.sin(a), 0);
      i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    }
    ctx.stroke();
    ctx.beginPath(); this.line3([0, 0, 0], [20, 0, 0]); ctx.stroke();
    const xl = this.project(22, 0, 0);
    ctx.fillStyle = "rgba(140,150,170,0.6)"; ctx.font = "11px sans-serif"; ctx.fillText("+x", xl[0] - 6, xl[1] + 4);

    if (opts.structure) {
      const st = this.structure;
      ctx.strokeStyle = "rgba(150,160,180,0.22)";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      this.line3(...st.rod);
      for (const s of st.stems) this.line3(...s);
      for (const { c, r } of st.rings) {
        for (let i = 0; i <= 40; i++) {
          const a = i / 40 * 2 * Math.PI;
          const p = this.project(c[0] + r * Math.cos(a), c[1] + r * Math.sin(a), c[2]);
          i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
        }
      }
      ctx.stroke();
    }

    this.projected = this.pixels.map((p, i) => {
      const q = this.project(p.x, p.y, p.z); return { i, x: q[0], y: q[1], d: q[2], s: q[3] };
    });
    const order = this.projected.slice().sort((a, b) => b.d - a.d);
    const ex = opts.exposure * (this.dim ? 0.35 : 1);

    // unlit bulbs first (opaque), then additive glow
    for (const q of order) {
      const r0 = Math.max(1.5, 0.28 * q.s);
      const k = 3 * q.i;
      const lit = colors[k] + colors[k + 1] + colors[k + 2] > 0;
      if (!lit && opts.unlit) {
        ctx.fillStyle = "#1c1f26"; ctx.strokeStyle = "#343946";
        ctx.beginPath(); ctx.arc(q.x, q.y, r0, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      }
    }
    ctx.globalCompositeOperation = "lighter";
    for (const q of order) {
      const k = 3 * q.i;
      const r = Math.min(255, colors[k] * ex), g = Math.min(255, colors[k + 1] * ex), b = Math.min(255, colors[k + 2] * ex);
      if (r + g + b < 1) continue;
      const lum = Math.max(r, g, b) / 255;
      const rg = Math.max(3, (0.5 + 0.9 * lum) * q.s);
      const grad = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, rg);
      grad.addColorStop(0, `rgba(${r},${g},${b},0.8)`);
      grad.addColorStop(0.3, `rgba(${r},${g},${b},0.22)`);
      grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(q.x, q.y, rg, 0, 2 * Math.PI); ctx.fill();
      // hot core
      const cr = Math.max(1.2, 0.22 * q.s);
      ctx.fillStyle = `rgba(${Math.min(255, r + 90 * lum)},${Math.min(255, g + 90 * lum)},${Math.min(255, b + 90 * lum)},0.9)`;
      ctx.beginPath(); ctx.arc(q.x, q.y, cr, 0, 2 * Math.PI); ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";

    if (this.hover >= 0) {
      const q = this.projected[this.hover];
      ctx.strokeStyle = "#6aa8ff"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(q.x, q.y, Math.max(5, 0.6 * q.s), 0, 2 * Math.PI); ctx.stroke();
    }
  }

  tick(now) {
    const dt = (now - this.last) / 1000; this.last = now;
    if (this.cam.spin) this.cam.az += dt * 0.35;
    this.draw();
    requestAnimationFrame(t => this.tick(t));
  }

  // ---------------------------------------------------------------- interaction
  bind() {
    const c = this.canvas, cam = this.cam;
    c.addEventListener("pointerdown", e => {
      this.drag = { x: e.clientX, y: e.clientY, az: cam.az, el: cam.el };
      c.setPointerCapture(e.pointerId); c.classList.add("dragging");
    });
    c.addEventListener("pointermove", e => {
      if (this.drag) {
        cam.az = this.drag.az - (e.clientX - this.drag.x) * 0.008;
        cam.el = Math.max(-0.2, Math.min(Math.PI / 2 - 0.001, this.drag.el + (e.clientY - this.drag.y) * 0.008));
        this.hideTip();
        return;
      }
      this.pick(e.clientX, e.clientY);
    });
    c.addEventListener("pointerup", () => { this.drag = null; c.classList.remove("dragging"); });
    c.addEventListener("pointerleave", () => this.hideTip());
    c.addEventListener("wheel", e => {
      e.preventDefault();
      cam.zoom = Math.max(0.4, Math.min(5, cam.zoom * Math.exp(-e.deltaY * 0.0015)));
    }, { passive: false });
    c.addEventListener("dblclick", () => this.setView("iso"));
    window.addEventListener("resize", () => this.resize());
    // follow the box the dashboard puts us in, not just the window
    if (window.ResizeObserver && c.parentElement) new ResizeObserver(() => this.resize()).observe(c.parentElement);
  }

  pick(cx, cy) {
    const rect = this.canvas.getBoundingClientRect();
    const mx = cx - rect.left, my = cy - rect.top, projected = this.projected;
    let best = -1, bd = 14 * 14;
    for (const q of projected) {
      const d = (q.x - mx) ** 2 + (q.y - my) ** 2;
      if (d < bd || (best >= 0 && d === bd && q.d < projected[best].d)) { bd = d; best = q.i; }
    }
    this.hover = best;
    if (best < 0) return this.hideTip();
    const tip = this.tip;
    if (!tip) return;
    const p = this.pixels[best], k = 3 * best, colors = this.colors;
    const rgb = [colors[k] || 0, colors[k + 1] || 0, colors[k + 2] || 0];
    tip.innerHTML = `<span class="sw" style="background:rgb(${rgb})"></span>` +
      `<b>#${p.index}</b> · output ${p.output} light ${p.light}<br>` +
      `<span class="muted">${p.strand} · bp ${p.base_pair} · ${p.part} slot ${p.slot} · rgb(${rgb.join(", ")})</span>`;
    tip.style.display = "block";
    const tw = tip.offsetWidth, th = tip.offsetHeight;   // tooltip is position: fixed (viewport coords)
    tip.style.left = Math.max(8, Math.min(window.innerWidth - tw - 8, cx + 14)) + "px";
    tip.style.top = Math.max(8, cy - th - 10) + "px";
  }

  hideTip() {
    this.hover = -1;
    if (this.tip) this.tip.style.display = "none";
  }
}
