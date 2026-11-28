"""Snow: soft flakes drifting down through the sculpture.

Each flake is a point that falls from above the top of the sculpture to below
the bottom at a steady speed (a little different for each flake), with a
small flutter from side to side. The lights are sparse, so a flake lights the
light nearest to it, and as it falls it crossfades into the next nearest one.
That way it glides from light to light. `flake_size` sets how many
neighbouring lights share the flake: the default 5 inches is about two lights
(the nearest one at full, the next one fading in and out), smaller is a
single sharp light, and larger is a soft glow over several. A flake far from every light (in the
gaps of the helix) or outside the sculpture's footprint fades out, so flakes
don't all collect on the few lights that are near empty space.

There's a fixed number of flakes in the air, sized so that about `density`
of the lights are lit at any moment (the count is worked out from the
layout and the flake size, so bigger flakes means fewer of them). When one reaches the bottom, a new one
starts above the top at a random spot.

`color=rainbow` walks the 256-step rainbow one flake at a time: each new
flake takes the next step and keeps that color all the way down. With about
two new flakes a second at the defaults, one trip around takes a couple of
minutes (fewer flakes, a bigger flake_size or a longer fall_seconds slow it).

Wind blows the flakes sideways: `wind` is the sideways speed as a fraction
of the falling speed (1 = a 45 degree slant), with slow gusts. Flakes blown
out of one side come back in on the other (the footprint wraps around).
`wind_direction` is a compass angle in degrees, or "random" for a new
direction each run.

Tree companion (render_tree): the tree strand gets its own flakes, in a thin
slab around the plane of its loop, with the same options; the count is worked
out the same way, so about `density` of its lights are lit too.

Options (play.py -o key=value, or options: in a show entry):
  color           "rainbow" (default): each new flake takes the next of 256
                  rainbow steps; or a fixed color, e.g. "#d8e4ff" (white with a
                  hint of blue)
  density         fraction of the lights lit at any moment (default 0.05)
  intensity       flake brightness, 0-1 (default 0.05, "light")
  flake_size      flake size in inches (default 5, about two lights)
  wind            sideways drift as a fraction of the falling speed (default 0 = none)
  wind_direction  degrees, or "random" (default)
  fall_seconds    time for a flake to fall top to bottom (default 6)
  seed            random seed (None = new each run)
"""
import math

import numpy as np

from effects._util import color, hash01, hsv, smoothstep

DESCRIPTION = "Soft flakes drifting down, stepping through the rainbow; optional wind"

OPTIONS = {
    "color": "rainbow",
    "density": 0.05,
    "intensity": 0.05,
    "flake_size": 5.0,
    "wind": 0.0,
    "wind_direction": "random",
    "fall_seconds": 6.0,
    "seed": None,
}

SIGMA_PER_SIZE = 0.4     # crossfade width between neighbouring lights, per inch of flake size
REACH_PER_SIZE = 0.9     # a flake farther than this times its size from every light fades out...
MIN_REACH = 4.5          # ...but never closer than this many inches, so small flakes still show
EDGE = 1.5               # inches: soft edge outside the footprint, and above/below
SPEED_SPREAD = 0.25      # each flake falls at 1 +/- this times the average speed
SWAY = 1.2               # inches of side-to-side flutter
SWAY_HZ = (0.2, 0.5)     # flutter rate range
GUST = 0.4               # wind speed varies +/- this fraction
GUST_HZ = 0.07           # how often the gusts come
RAINBOW_STEPS = 256      # color=rainbow: steps around the hue wheel, one per new flake
CAL_SAMPLES = 3000       # random flake spots used to work out how many lights one flake lights
LIT_LEVEL = 0.35         # a light counts as lit for `density` above this fraction of the intensity


def _num(opts, key, lo=None, hi=None):
    try:
        v = float(opts[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key} should be a number, got {opts[key]!r}") from None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        rng = f"{lo}-{hi}" if hi is not None else f">= {lo}"
        raise ValueError(f"{key} should be {rng}, got {v}")
    return v


def prepare(opts):
    seed = int(opts["seed"])
    density = _num(opts, "density", 0.005, 1.0)
    intensity = _num(opts, "intensity", 0.0, 1.0)
    wind = _num(opts, "wind", 0.0, 5.0)
    fall = _num(opts, "fall_seconds", 0.5)
    size = _num(opts, "flake_size", 0.5, 30.0)
    d = opts["wind_direction"]
    if d is None or str(d).strip().lower() in ("", "random", "none"):
        direction = 2 * math.pi * float(hash01(seed, 7))
    else:
        direction = math.radians(_num(opts, "wind_direction"))
    return {
        **opts,
        "seed": seed, "density": density, "intensity": intensity, "wind": wind,
        "fall_seconds": fall, "flake_size": size,
        "sigma": SIGMA_PER_SIZE * size, "reach": max(MIN_REACH, REACH_PER_SIZE * size),
        "direction": direction, "rgb": None if str(opts["color"]).strip().lower() == "rainbow" else color(opts["color"]),
        "_geom": None, "_tgeom": None,
    }


def _geometry(opts, meta):
    """Flake count and per-flake constants for the sculpture (cached in opts).
    Flakes live in a square around the rod, and fade out beyond its radius."""
    g = opts["_geom"]
    if g is not None and g["n"] == meta.n:
        return g
    rmax = float(meta.r.max())
    half = rmax + EDGE
    g = _field(opts, meta.xyz, opts["seed"], center=np.zeros(2), half=np.array([half, half]),
               shape=("disc", rmax))
    opts["_geom"] = g
    return g


def _tree_geometry(opts, tree):
    """The same for the tree strand: a box around its loop (x, z), a thin slab in y."""
    g = opts["_tgeom"]
    if g is not None and g["n"] == tree.n:
        return g
    lo, hi = tree.xyz[:, :2].min(axis=0), tree.xyz[:, :2].max(axis=0)
    center, inner = (lo + hi) / 2, (hi - lo) / 2
    g = _field(opts, tree.xyz, opts["seed"] + 7919, center=center, half=inner + EDGE,
               shape=("box", center, inner))
    opts["_tgeom"] = g
    return g


def _field(opts, xyz, seed, center, half, shape):
    """Flakes over the lights at xyz, in center +/- half (x, y), wrapped."""
    zmin, zmax = float(xyz[:, 2].min()), float(xyz[:, 2].max())
    ztop, zbot = zmax + EDGE, zmin - EDGE
    g = {"n": len(xyz), "seed": seed, "center": center, "half": half, "shape": shape,
         "zmin": zmin, "zmax": zmax, "ztop": ztop, "zbot": zbot}
    # How many lights does one flake in the air light, on average? Drop flakes
    # at random spots in their space (the square, from above the top to below
    # the bottom) and count; that covers the dark corners, gaps and flake size.
    cs = np.arange(CAL_SAMPLES)
    p = np.column_stack([center[0] + half[0] * (2 * hash01(seed, cs, 21) - 1),
                         center[1] + half[1] * (2 * hash01(seed, cs, 22) - 1),
                         zbot + (ztop - zbot) * hash01(seed, cs, 23)])
    vis = _visible(p, g) * 0.85                                   # 0.85 = average flake brightness
    lit = (_levels(p, xyz, opts) * vis[:, None] > LIT_LEVEL).sum(axis=1).mean()
    n = max(1, round(opts["density"] * len(xyz) / max(lit, 0.05)))
    i = np.arange(n)
    v = (zmax - zmin) / opts["fall_seconds"]            # average falling speed, in/s
    speed = v * (1 + SPEED_SPREAD * (2 * hash01(seed, i, 1) - 1))
    sway_hz = SWAY_HZ[0] + (SWAY_HZ[1] - SWAY_HZ[0]) * hash01(seed, i, 2)
    g.update({
        "flakes": n,
        "speed": speed, "life": (ztop - zbot) / speed,
        "phase": hash01(seed, i, 3),
        "births_per_s": float((speed / (ztop - zbot)).sum()),   # new flakes a second, all slots
        "bright": 0.7 + 0.3 * hash01(seed, i, 4),
        "sway_w": 2 * np.pi * sway_hz,
        "sway_ph": 2 * np.pi * hash01(seed, i, 5),
        "wind": opts["wind"] * v * np.array([math.cos(opts["direction"]), math.sin(opts["direction"])]),
        "gust_ph": 2 * np.pi * float(hash01(seed, 6)),
    })
    return g


def _drift(t, g):
    """Sideways distance the wind has carried things by time t (closed form), (..., 2)."""
    w = 2 * np.pi * GUST_HZ
    s = np.asarray(t, float) - GUST * np.cos(w * np.asarray(t, float) + g["gust_ph"]) / w
    return s[..., None] * g["wind"]


def _flakes(t, g):
    """Flake positions (F, 3), how visible each one is (F,), and its hue (F,)
    for the rainbow: the step reached when it was born, kept for its fall."""
    life = g["life"]
    cyc = t / life + g["phase"]
    k = np.floor(cyc).astype(np.int64)                  # which flake this slot is on
    age = (cyc - k) * life
    i = np.arange(g["flakes"])
    c, h = g["center"], g["half"]
    x0 = c[0] + h[0] * (2 * hash01(g["seed"], i, k, 11) - 1)     # a new random spot each fall
    y0 = c[1] + h[1] * (2 * hash01(g["seed"], i, k, 12) - 1)
    z = g["ztop"] - g["speed"] * age
    xy = np.column_stack([x0, y0]) + _drift(t, g) - _drift(t - age, g)
    sw = g["sway_w"] * t + g["sway_ph"]
    xy += SWAY * np.column_stack([np.sin(sw), np.sin(0.7 * sw + 1.3)])
    xy = (xy - c + h) % (2 * h) - h + c                 # wrap around the footprint
    pos = np.column_stack([xy, z])
    # flakes are born at births_per_s on average, so counting births up to
    # this one's birth time gives each new flake the next step
    born = np.floor((t - age) * g["births_per_s"])
    hue = (born % RAINBOW_STEPS) / RAINBOW_STEPS
    return pos, _visible(pos, g) * g["bright"], hue


def _visible(pos, g):
    """Fade for flakes outside the footprint or above/below the lights, (F,)."""
    z = pos[:, 2]
    if g["shape"][0] == "disc":
        rmax = g["shape"][1]
        foot = smoothstep(rmax + EDGE, rmax, np.hypot(pos[:, 0], pos[:, 1]))
    else:
        _, center, inner = g["shape"]
        out = np.maximum(np.abs(pos[:, :2] - center) - inner, 0)
        foot = smoothstep(EDGE, 0.0, np.hypot(out[:, 0], out[:, 1]))
    return foot * smoothstep(g["zbot"], g["zmin"], z) * smoothstep(g["ztop"], g["zmax"], z)


def _levels(pos, xyz, opts):
    """How much each flake lights each light, (F, N), before its own fade."""
    d2 = ((xyz[None, :, :] - pos[:, None, :]) ** 2).sum(axis=2)
    near = d2.min(axis=1, keepdims=True)
    # the nearest light gets the flake at full; the next ones crossfade in as
    # the flake gets about as close to them (closer than the flake size)
    level = np.exp(-(d2 - near) / opts["sigma"] ** 2)
    level[level < 0.02] = 0.0
    # a flake far from every light (a gap in the helix) fades out
    reach = smoothstep(opts["reach"] + EDGE, opts["reach"], np.sqrt(near[:, 0]))
    return level * reach[:, None]


def render(t, xyz, meta, opts):
    return _snow(t, xyz, _geometry(opts, meta), opts)


def render_tree(t, xyz, tree, opts):
    return _snow(t, xyz, _tree_geometry(opts, tree), opts)


def _snow(t, xyz, g, opts):
    pos, vis, hue = _flakes(t, g)
    level = _levels(pos, xyz, opts) * vis[:, None]
    lit = level.max(axis=0)                              # overlapping flakes don't add up
    if opts["rgb"] is None:
        rgb = hsv(hue)[level.argmax(axis=0)]             # each light takes its brightest flake's color
    else:
        rgb = opts["rgb"][None, :]
    return rgb * (opts["intensity"] * lit)[:, None]
