"""Swarm: a breathing cloud of bugs wandering around inside the sculpture.

The swarm is a soft ellipsoid. Its center follows a random walk: the
velocity on each axis is a sum of sines at random frequencies (spread evenly
on a log scale), with equal weight, which is a smooth stand-in for white-noise
velocity. Integrating that gives the walk's position in closed form, so
render() stays a pure function of t. The walk is folded back at the
sculpture's edges (a triangle wave in z and in a square in x/y, which is then
mapped onto the round footprint), so the swarm bounces around inside. Only the core is kept inside: the
outer part of the swarm can spill past the edge, which puts the core right
out at the rings.

`speed` 1 means the swarm's straight-line speed would cross the sculpture's
height in 2 s. Because the walk keeps changing direction, it takes several
times longer to get from bottom to top.

The swarm breathes: its outer size swells and shrinks by `breath` (a
fraction of its size), at `breath_rate` times the motion rate (1 / the time
for one straight-line crossing). Each axis breathes a little differently so
the shape wobbles instead of just scaling.

Brightness falls from the core to the edge ((1 - u^2)^falloff, u = 0 at the
center, 1 at the edge), then the brightest lit pixel is brought up to full
so the swarm stays visible when its core falls between lights. Color is "rainbow" (the hue cycles every
cycle_seconds) or a fixed color. The hue shifts by `gradient` toward the
edge; with the rainbow, the edge is the hue that's coming next, so the next
color is drawn in from the outside to the core. `edge_color` blends to a
specific color at the edge instead.

Options (play.py -o key=value, or options: in a show entry):
  size           swarm volume as a fraction of the sculpture's (default 0.1)
  speed          motion speed; 1 = straight line crosses the height in 2 s
  breath         how much the outer size swells and shrinks, 0-1 (default 0.2)
  breath_rate    breathing rate relative to the motion rate (default 3)
  falloff        core-to-edge dimming; 0 = flat, higher = smaller bright core
  color          "rainbow" (default) or a color (name, #rrggbb, [r, g, b])
  cycle_seconds  rainbow: seconds for one full turn of hue (default 30)
  gradient       hue shift from core to edge, in turns (default 0.15; 0 = uniform)
  edge_color     a color to blend to at the edge instead of the hue shift
  seed           random seed for the walk (None = new each run)
"""
import colorsys

import numpy as np

from effects._util import color, hash01, hsv

DESCRIPTION = "A breathing rainbow swarm wandering through the sculpture"

OPTIONS = {
    "size": 0.1,
    "speed": 1.0,
    "breath": 0.2,
    "breath_rate": 3.0,
    "falloff": 1.5,
    "color": "rainbow",
    "cycle_seconds": 30.0,
    "gradient": 0.15,
    "edge_color": None,
    "seed": None,
}

CROSS_SECONDS = 2.0       # speed 1: a straight line crosses the height in this time
N_WAVES = 8               # sines per axis in the walk's velocity
F_LO, F_HI = 0.04, 1.0    # their frequency range, Hz at speed 1
KEEP_IN = 0.0             # core stays this fraction of the radius inside the edges (0 = core can reach the edge)
MAX_GAIN = 4.0            # most the swarm is brightened when its core is between lights


def _num(opts, key, lo=None, hi=None):
    try:
        v = float(opts[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key} should be a number, got {opts[key]!r}") from None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        rng = f"{lo}-{hi}" if hi is not None else f">= {lo}"
        raise ValueError(f"{key} should be {rng}, got {v}")
    return v


def _fold(p, lo, hi):
    """Triangle-wave fold of p into [lo, hi] (bounces off both ends)."""
    w = hi - lo
    if w <= 0:
        return np.full_like(p, (lo + hi) / 2)
    q = np.mod(p - lo, 2 * w)
    return lo + np.where(q > w, 2 * w - q, q)


def prepare(opts):
    seed = int(opts["seed"])
    size = _num(opts, "size", 0.005, 1.0)
    speed = _num(opts, "speed", 0.0)
    breath = _num(opts, "breath", 0.0, 0.9)
    breath_rate = _num(opts, "breath_rate", 0.0)
    falloff = _num(opts, "falloff", 0.0)
    cycle = _num(opts, "cycle_seconds", 0.1)
    gradient = _num(opts, "gradient", -1.0, 1.0)

    c = opts["color"]
    if c is None or str(c).strip().lower() == "rainbow":
        base = None
    else:
        r, g, b = color(c)
        base = colorsys.rgb_to_hsv(r, g, b)          # (h, s, v)
    edge = opts["edge_color"]
    edge = None if edge is None or str(edge).strip().lower() in ("", "none") else color(edge)

    return {
        **opts,
        "seed": seed, "size": size, "speed": speed, "breath": breath,
        "breath_rate": breath_rate, "falloff": falloff, "cycle": cycle,
        "gradient": gradient, "base_hsv": base, "edge_rgb": edge,
        "_geom": None,
    }


def _geometry(opts, meta):
    """Sizes and walk constants that depend on the layout (cached in opts)."""
    g = opts["_geom"]
    if g is not None and g["n"] == meta.n:
        return g
    seed = opts["seed"]
    zmin, zmax = float(meta.z.min()), float(meta.z.max())
    height = zmax - zmin
    rcyl = float(meta.r.max())
    vol = np.pi * rcyl ** 2 * height
    radius = (opts["size"] * vol * 3 / (4 * np.pi)) ** (1 / 3)
    keep = KEEP_IN * radius
    # straight-line speed at speed 1, in inches/s; RMS of the 3-D velocity
    v0 = height / CROSS_SECONDS
    amp = v0 / np.sqrt(1.5 * N_WAVES)                # per-wave amplitude, per axis
    k = np.arange(N_WAVES)
    axes = np.arange(3)[:, None]
    # log-spaced frequencies with jitter, random phases, per axis
    u = (k + hash01(seed, axes, k, 1)) / N_WAVES
    freq = F_LO * (F_HI / F_LO) ** u                 # (3, N)
    phase = 2 * np.pi * hash01(seed, axes, k, 2)
    g = {
        "n": meta.n, "zmin": zmin, "zmax": zmax, "rcyl": rcyl, "radius": radius,
        "zlo": zmin + keep, "zhi": zmax - keep, "rlim": max(0.0, rcyl - keep),
        "amp": amp, "freq": freq, "phase": phase,
        "motion_hz": 1.0 / CROSS_SECONDS,
        "breath_phase": 2 * np.pi * hash01(seed, np.arange(4), 3),
        "start": np.array([0.0, 0.0, (zmin + zmax) / 2]),
    }
    opts["_geom"] = g
    return g


def _center(tau, g):
    """Swarm center at walk time tau (seconds at speed 1)."""
    w = 2 * np.pi * g["freq"]
    # position = integral of amp * cos(w t + phase), starting at the middle
    disp = (g["amp"] * (np.sin(w * tau + g["phase"]) - np.sin(g["phase"])) / w).sum(axis=1)
    x, y, z = g["start"] + disp
    z = _fold(z, g["zlo"], g["zhi"])
    rl = g["rlim"]
    x, y = _fold(x, -rl, rl), _fold(y, -rl, rl)
    # square -> disk, keeping the direction: a corner of the square maps to the rim
    h = np.hypot(x, y)
    if h > 1e-9:
        s = max(abs(x), abs(y)) / h
        x, y = x * s, y * s
    return np.array([x, y, z])


def _breath(t, opts, g):
    """Per-axis size factors (3,)."""
    if opts["breath"] == 0 or opts["breath_rate"] == 0:
        return np.ones(3)
    f = opts["breath_rate"] * g["motion_hz"] * max(opts["speed"], 1e-6)
    ph = g["breath_phase"]
    common = 0.75 * np.sin(2 * np.pi * f * t + ph[0])
    # a slower, out-of-step wobble per axis so the shape isn't just scaling
    own = 0.25 * np.sin(2 * np.pi * f * 0.618 * t + ph[1:])
    return 1 + opts["breath"] * (common + own)


def render(t, xyz, meta, opts):
    g = _geometry(opts, meta)
    c = _center(t * opts["speed"], g)
    radii = g["radius"] * _breath(t, opts, g)
    u = np.sqrt((((xyz - c) / radii) ** 2).sum(axis=1))      # 0 core .. 1 edge
    inside = u < 1
    level = np.where(inside, np.clip(1 - u * u, 0, 1) ** opts["falloff"], 0.0)
    if opts["falloff"] == 0:
        level = inside.astype(float)
    # The lights are sparse, so the core often sits between them. Lift the
    # brightest lit pixel to full (up to MAX_GAIN) so the swarm doesn't fade
    # out in the gaps; the core-to-edge shape is kept.
    peak = level.max()
    if peak > 0:
        level = level * min(1 / peak, MAX_GAIN)
    uu = np.clip(u, 0, 1)

    if opts["base_hsv"] is None:
        h0, s, v = t / opts["cycle"], 1.0, 1.0
    else:
        h0, s, v = opts["base_hsv"]
    if opts["edge_rgb"] is None:
        rgb = hsv(h0 + opts["gradient"] * uu, s, v)
    else:
        core = hsv(h0, s, v)
        rgb = core[None, :] * (1 - uu[:, None]) + opts["edge_rgb"][None, :] * uu[:, None]
    return rgb * level[:, None]
