"""Shared sky for the sunset and sunrise effects.

The sculpture is a slice of landscape: the base pairs below `horizon` are the
ground, the rest is sky. The sun is a glow on the core (rod and stem lights,
spilling onto the ring lights by the stem) that moves along the rod. The scene
runs over `minutes`, with the sun event at exactly the halfway point, so a
30-minute entry started at sunset - 15m (or sunrise - 15m) lands on time.

The scene is written as a sunset, on a scene clock p from 0 to 1:
  0-0.5     the sun comes down the core from the top; the sky warms from a soft
            day blue to the full sky colors
  0.5       the top of the sun goes below the horizon (and the green flash)
  0.5-1     afterglow: the warm colors sink toward the horizon and dim, the top
            goes navy, stars fade in; it ends on a dim night sky
Sunrise runs the same scene backwards (p = 1 - t / length). The green flash
always streaks upward, in real time, whichever way the scene runs. After the
scene's length it holds its last frame.

Sky colors (`color`) go from the horizon up and are the sky at the moment of
sunset/sunrise. "random" picks one of SKY_PALETTES and varies it a little; a
palette name picks that one; a list of colors ("orange,pink,purple,navy",
horizon first) uses those.
"""
import math

import numpy as np

from effects._util import color, hash01, smoothstep

OPTIONS = {
    "horizon": 1,
    "color": "random",
    "stars": True,
    "minutes": 30.0,
    "green_flash": True,
    "seed": None,
}

# horizon -> top, at the moment the sun goes down
SKY_PALETTES = {
    "classic":     ["#ffb000", "#ff6000", "#ff3c50", "#8030c0", "#102080"],
    "fire":        ["#ffd000", "#ff5000", "#e01000", "#900030", "#200060"],
    "pastel":      ["#ffa060", "#ff6090", "#b070e0", "#6070e0", "#2040a0"],
    "desert":      ["#ffa000", "#e05010", "#c03050", "#602070", "#101850"],
    "tropical":    ["#ffe040", "#ff7020", "#ff2080", "#7020c0", "#0030a0"],
    "purple_haze": ["#ff8020", "#e02080", "#8020c0", "#3010a0", "#081040"],
}
DAY = np.array([[0.55, 0.72, 0.95], [0.12, 0.35, 0.95]])       # horizon, top
NIGHT = np.array([[0.035, 0.03, 0.10], [0.008, 0.01, 0.045]])
GROUND_DAY = np.array([0.03, 0.06, 0.015])
GROUND_NIGHT = np.array([0.004, 0.006, 0.003])
SUN_HIGH = np.array([1.0, 0.92, 0.7])           # sun color high in the sky...
SUN_LOW = np.array([1.0, 0.32, 0.03])           # ...and at the horizon
FLASH_RGB = np.array([0.15, 1.0, 0.3])

SKY_DAY_LEVEL = 0.45     # how bright the day sky is (1 = the colors at full)
SKY_SET_LEVEL = 0.7      # how bright the sky colors are at sunset
SUN_RZ, SUN_RR = 3.0, 6.0    # sun glow: inches along the rod, and out from it
SUN_HALO = 12.0              # inches: the wider, dimmer halo
SUN_TOP = 2.0                # the sun starts this far below the top light
N_STARS = (3, 5)
STAR_LEVEL = 0.8
FLASH_SECONDS = 1.0          # green flash: time for the streak to run up the core
FLASH_TAIL = 12.0            # inches of fading tail behind its head


def _num(opts, key, lo=None, hi=None):
    try:
        v = float(opts[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key} should be a number, got {opts[key]!r}") from None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        rng = f"{lo}-{hi}" if hi is not None else f">= {lo}"
        raise ValueError(f"{key} should be {rng}, got {v}")
    return v


def _flag(opts, key):
    v = opts[key]
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", "none", ""):
        return False
    raise ValueError(f"{key} should be on or off, got {v!r}")


def _palette(spec, seed):
    """Sky colors, horizon first, (K, 3)."""
    if isinstance(spec, str) and "," in spec:
        spec = [c for c in spec.split(",") if c.strip()]
    if spec is None or (isinstance(spec, str) and spec.strip().lower() in ("", "random")):
        names = sorted(SKY_PALETTES)
        name = names[int(hash01(seed, 31) * len(names))]
        pal = np.array([color(c) for c in SKY_PALETTES[name]])
        # vary each color a little: brightness and a slight red/blue lean
        k = np.arange(len(pal))
        lean = 0.12 * (2 * hash01(seed, k, 32) - 1)
        pal = pal * (0.85 + 0.15 * hash01(seed, k, 33))[:, None]
        pal[:, 0] = np.clip(pal[:, 0] * (1 + lean), 0, 1)
        pal[:, 2] = np.clip(pal[:, 2] * (1 - lean), 0, 1)
        return pal
    if isinstance(spec, str):
        key = spec.strip().lower()
        if key in SKY_PALETTES:
            return np.array([color(c) for c in SKY_PALETTES[key]])
        raise ValueError(f"color should be random, a palette ({', '.join(SKY_PALETTES)}) "
                         f"or a list of colors, horizon first; got {spec!r}")
    pal = np.array([color(c) for c in spec])
    if len(pal) < 2:
        raise ValueError("color needs at least 2 colors (horizon first)")
    return pal


def prepare(opts, rising):
    seed = int(opts["seed"])
    horizon = int(_num(opts, "horizon", 0, 8))
    return {
        **opts,
        "seed": seed, "horizon": horizon, "rising": rising,
        "length": 60 * _num(opts, "minutes", 0.1),
        "stars": _flag(opts, "stars"), "green_flash": _flag(opts, "green_flash"),
        "pal": _palette(opts["color"], seed),
        "_geom": None,
    }


def _geometry(opts, meta):
    g = opts["_geom"]
    if g is not None and g["n"] == meta.n:
        return g
    seed = opts["seed"]
    zmax = float(meta.z.max())
    # the horizon sits between a base pair's lollipops and the next one's rod light
    rod_z = np.array([meta.z[meta.rod & (meta.base_pair == b)].mean() for b in range(meta.n_base_pairs)])
    lol_z = np.array([meta.z[~meta.rod & (meta.base_pair == b)].mean() for b in range(meta.n_base_pairs)])
    h = opts["horizon"]
    zh = (lol_z[h - 1] + rod_z[h]) / 2 if h > 0 else float(meta.z.min()) - 1.0
    sky = meta.z > zh
    s = np.clip((meta.z - zh) / (zmax - zh), 0, 1)               # 0 horizon .. 1 top
    # stars: a few ring lights in the top two base pairs
    cand = np.flatnonzero(meta.ring & (meta.base_pair >= meta.n_base_pairs - 2) & sky)
    n_st = N_STARS[0] + int(hash01(seed, 41) * (N_STARS[1] - N_STARS[0] + 1))
    order = np.argsort(hash01(seed, cand, 42))
    stars = cand[order[:n_st]]
    g = {
        "n": meta.n, "zh": zh, "zmax": zmax, "sky": sky, "s": s,
        "core": meta.rod | meta.stem,
        "stars": stars,
        "star_rgb": np.array([[1.0, 0.95, 0.85], [0.85, 0.9, 1.0]])[(hash01(seed, stars, 43) * 2).astype(int)],
        "star_ph": 2 * np.pi * hash01(seed, stars[:, None], np.arange(2), 44),
        "star_hz": 0.3 + 0.9 * hash01(seed, stars[:, None], np.arange(2), 45),
    }
    opts["_geom"] = g
    return g


def _ramp(stops, s):
    """Colors at heights s (0 horizon .. 1 top) from evenly spaced stops."""
    x = np.clip(s, 0, 1) * (len(stops) - 1)
    i = np.minimum(np.floor(x).astype(int), len(stops) - 2)
    f = (x - i)[:, None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def _sky(p, s, pal):
    day = _ramp(DAY, s) * SKY_DAY_LEVEL
    sett = _ramp(pal, s) * SKY_SET_LEVEL
    night = _ramp(NIGHT, s)
    if p <= 0.5:
        return day + (sett - day) * smoothstep(0.08, 0.48, p)
    q = (p - 0.5) / 0.5
    # afterglow: the colors squeeze down toward the horizon and dim; above
    # them the sky goes to night
    c = 1 - 0.8 * smoothstep(0.0, 0.6, q)
    glow = _ramp(pal, s / c) * SKY_SET_LEVEL * (1 - 0.6 * smoothstep(0, 0.8, q))
    above = (smoothstep(0.6 * c, 1.1 * c, s) * smoothstep(0.0, 0.3, q))[:, None]
    twilight = glow * (1 - above) + night * above
    return twilight + (night - twilight) * smoothstep(0.35, 0.95, q)


def render(t, xyz, meta, opts):
    g = _geometry(opts, meta)
    T = opts["length"]
    p = min(max(t / T, 0.0), 1.0)
    if opts["rising"]:
        p = 1.0 - p
    zh, zmax, sky = g["zh"], g["zmax"], g["sky"]

    out = np.zeros((meta.n, 3))
    out[sky] = _sky(p, g["s"][sky], opts["pal"])

    # ground: dim, darker at night, with a warm glow near the horizon around the event
    daylight = 1 - smoothstep(0.4, 0.75, p)
    near = np.clip(1 - (zh - meta.z[~sky]) / 6.0, 0, 1)[:, None]
    warm = math.exp(-((p - 0.5) / 0.12) ** 2)
    out[~sky] = (GROUND_NIGHT + (GROUND_DAY - GROUND_NIGHT) * daylight
                 + opts["pal"][0] * 0.1 * warm * near)

    # sun: center on the rod, from just under the top down to its top touching
    # the horizon at p = 0.5, then on below
    zc = (zmax - SUN_TOP) - (zmax - SUN_TOP - (zh - SUN_RZ)) * (p / 0.5)
    vis = float(np.clip((zc + SUN_RZ - zh) / (2 * SUN_RZ), 0, 1))
    if vis > 0:
        e = float(np.clip((zc - zh) / (zmax - zh), 0, 1))
        sun_rgb = SUN_LOW + (SUN_HIGH - SUN_LOW) * math.sqrt(e)
        dz = meta.z - zc
        core = np.exp(-(dz / SUN_RZ) ** 2 - (meta.r / SUN_RR) ** 2)
        halo = 0.25 * np.exp(-(dz ** 2 + meta.r ** 2) / SUN_HALO ** 2)
        lvl = np.where(sky, (core + halo) * vis, 0.0)
        out = out + sun_rgb[None, :] * lvl[:, None]

    # stars twinkle in during the night part of the scene
    if opts["stars"] and len(g["stars"]):
        a = smoothstep(0.6, 0.8, p)
        if a > 0:
            tw = 0.65 + 0.2 * np.sin(g["star_hz"][:, 0] * 2 * np.pi * t + g["star_ph"][:, 0]) \
                      + 0.15 * np.sin(g["star_hz"][:, 1] * 5.3 * t + g["star_ph"][:, 1])
            lvl = STAR_LEVEL * a * tw
            st = g["stars"]
            out[st] = np.maximum(out[st], g["star_rgb"] * lvl[:, None])

    # green flash: a quick streak up the core, in real time, at the sun event
    if opts["green_flash"]:
        dt = t - T / 2
        if 0 <= dt <= FLASH_SECONDS * 1.5:
            head = zh + (zmax + FLASH_TAIL - zh) * dt / FLASH_SECONDS
            behind = head - meta.z
            lvl = np.where(g["core"] & sky & (behind >= 0), np.clip(1 - behind / FLASH_TAIL, 0, 1), 0.0)
            out = out + (FLASH_RGB[None, :] - out) * lvl[:, None]     # replaces the sky, so it reads green

    return np.clip(out, 0, 1)
