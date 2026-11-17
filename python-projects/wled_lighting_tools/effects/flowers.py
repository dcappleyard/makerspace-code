"""Flowers: a green stem grows up the core with leaves near its tip; buds form
at the top and all the flowers bloom together. Then it holds, fades, and a
new plant grows.

One growth cycle, as fractions of the growth time G (grow_seconds, varied by
up to +/- speed_jitter each cycle):

  0 - 0.5 G    The stem grows up the rod lights to a random top base pair
               (min_height up to the top), in a random green and brightness.
  while short  Leaves grow outward along the lollipop stems just below the
  0.05-0.35 G  tip, inner light then outer. They sit on the top 1-3 base
               pairs under the tip (leaf_levels) and move up with it, sliding
               from one base pair to the next as the stem grows.
  0.5 - 0.62 G Buds close around the flowering rings in a darker green, from
               the stem side to the outermost light. A flower always forms on
               the top base pair, sometimes on the 2nd and less often on the
               3rd. With top_flower, the tip of the stem (the rod lights
               above the top lollipops) buds too.
  0.7 - 0.9 G  All flowers bloom at the same time, each opening from its
               outermost ring light inward until the full ring is the flower.
  after G      Hold for hold_seconds, fade over fade_seconds, a short dark
               gap, then the next plant.

All flowers on one plant share a color scheme of three colors: the petal
tip (the ring's outermost light), the two beside it, and the center (the two
lights next to the stem). Each plant draws a scheme from FLOWER_LIBRARY
(irises, roses, daisies, ...). None of them use green.

Options (play.py -o key=value, or options: in a show entry):
  grow_seconds   time for full growth and blooming (default 60)
  speed_jitter   random change in growth time per plant, 0-0.9 (default 0.2)
  hold_seconds   how long the bloomed plant stays (default 20)
  fade_seconds   fade out at the end (default 4)
  min_height     lowest stem height, as a fraction of the rod (default 0.55)
  leaf_levels    leaves on up to this many base pairs under the tip, 1-3;
                 each plant picks 1 to this many (default 3)
  leaves         chance each leaf spot has a leaf (default 0.75)
  flowers        chance each top lollipop flowers; the 2nd base pair down
                 gets half that, the 3rd a quarter (default 0.9; the top base
                 pair always gets at least one)
  top_flower     chance of a bud and flower at the tip of the stem (default 0.7)
  colors         a fixed scheme: 1-3 colors, petal tip first, center last,
                 e.g. "white,white,yellow" (names, #rrggbb or [r, g, b]).
                 Overrides palette.
  palette        "library" (default: a scheme from FLOWER_LIBRARY per plant),
                 "generated" (a new non-green scheme per plant), "random"
                 (either), or a name in FLOWER_LIBRARY
  seed           random seed (None = a new garden each run)
"""
import numpy as np

from effects._util import color, hash01, hsv, smoothstep

DESCRIPTION = "A stem grows up the core with leaves at its tip; flowers bloom together at the top"

# petal tip (outermost ring light), the two beside it, the center (by the stem)
FLOWER_LIBRARY = {
    "iris":           ["#6a00ff", "#9a40ff", "#ffd000"],
    "red_rose":       ["#d00018", "#ff0820", "#a00010"],
    "pink_rose":      ["#ff4080", "#ff2068", "#e00050"],
    "orange_rose":    ["#ff5000", "#ff7010", "#ff3800"],
    "daisy":          ["#ffffff", "#ffffff", "#ffd000"],
    "sunflower":      ["#ffc000", "#ffa000", "#602000"],
    "black_eyed_susan": ["#ffb000", "#ff9000", "#401000"],
    "tulip":          ["#ff1000", "#ff5000", "#ffd000"],
    "pansy":          ["#a000ff", "#6000d0", "#ffe000"],
    "lavender":       ["#b080ff", "#9060ff", "#6020c0"],
    "cornflower":     ["#2050ff", "#3070ff", "#ffffff"],
    "forget_me_not":  ["#40a0ff", "#60b0ff", "#ffe040"],
    "stargazer_lily": ["#ffffff", "#ff60a0", "#e00060"],
    "poppy":          ["#ff2000", "#ff1000", "#200000"],
    "hibiscus":       ["#ff2050", "#ff0030", "#a00010"],
    "marigold":       ["#ff9000", "#ff7000", "#ff4000"],
    "peony":          ["#ffb0c8", "#ff80a8", "#ff4080"],
    "magenta_aster":  ["#ff00c0", "#e000a0", "#ffd000"],
    "pink_tip":       ["#ff1070", "#ffffff", "#ffffff"],
}

OPTIONS = {
    "grow_seconds": 60.0,
    "speed_jitter": 0.2,
    "hold_seconds": 20.0,
    "fade_seconds": 4.0,
    "min_height": 0.55,
    "leaf_levels": 3,
    "leaves": 0.75,
    "flowers": 0.9,
    "top_flower": 0.7,
    "colors": None,
    "palette": "library",
    "seed": None,
}

GAP = 1.5                 # dark seconds between plants
STEM_PHASE = 0.5          # the stem finishes growing at this fraction of G
TIP_SOFT = 2.0            # inches: a rod light fades in over this as the tip passes
LEAF_GROW = (0.05, 0.35)  # leaves grow outward over this part of G
BUD = (0.5, 0.12)         # buds: start, duration (fractions of G)
BLOOM = (0.7, 0.2)        # blooms: start, duration (fractions of G), all together
LOWER_FLOWER = (1.0, 0.5, 0.25)   # flower chance by level below the top, times `flowers`


def _num(opts, key, lo, hi=None):
    try:
        v = float(opts[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key} should be a number, got {opts[key]!r}") from None
    if v < lo or (hi is not None and v > hi):
        rng = f"{lo}-{hi}" if hi is not None else f">= {lo}"
        raise ValueError(f"{key} should be {rng}, got {v}")
    return v


def prepare(opts):
    out = dict(opts)
    out["seed"] = int(opts["seed"])
    out["grow"] = _num(opts, "grow_seconds", 1.0)
    out["jitter"] = _num(opts, "speed_jitter", 0.0, 0.9)
    out["hold"] = _num(opts, "hold_seconds", 0.0)
    out["fade"] = _num(opts, "fade_seconds", 0.0)
    out["min_h"] = _num(opts, "min_height", 0.0, 1.0)
    out["leaf_levels"] = int(_num(opts, "leaf_levels", 1, 3))
    for k in ("leaves", "flowers", "top_flower"):
        out[k] = _num(opts, k, 0.0, 1.0)

    cols = opts["colors"]
    if cols is not None and str(cols).strip().lower() not in ("", "none"):
        if isinstance(cols, str):
            cols = [c for c in cols.split(",") if c.strip()]
        if not 1 <= len(cols) <= 3:
            raise ValueError(f"colors needs 1-3 colors (petal tip first, center last), got {len(cols)}")
        cols = [color(c) for c in cols]
        cols += [cols[-1]] * (3 - len(cols))
        out["scheme"] = np.array(cols)
    else:
        out["scheme"] = None
        pal = opts["palette"]
        if pal not in ("library", "generated", "random") and pal not in FLOWER_LIBRARY:
            raise ValueError(f"unknown palette {pal!r} (have: library, generated, random, "
                             f"{', '.join(FLOWER_LIBRARY)})")
    out["cycle_len"] = out["grow"] * (1 + out["jitter"]) + out["hold"] + out["fade"] + GAP
    out["_geom"] = None
    out["_cycles"] = {}
    return out


def _geometry(opts, meta):
    g = opts["_geom"]
    if g is not None and g["n"] == meta.n:
        return g
    n = meta.n
    rod = np.flatnonzero(meta.rod)
    nbp = meta.n_base_pairs
    rod_bp_z = np.array([meta.z[rod][meta.base_pair[rod] == b].mean() for b in range(nbp)])
    lol_bp_z = np.array([meta.z[(meta.base_pair == b) & ~meta.rod].mean() for b in range(nbp)])
    # stem rank: 0 = inner pair (next to the rod), 1 = outer pair
    stem_rank = np.full(n, -1)
    for o in np.unique(meta.output):
        for b in range(nbp):
            s = np.flatnonzero((meta.output == o) & (meta.base_pair == b) & meta.stem)
            if len(s):
                stem_rank[s] = (meta.r[s] > np.median(meta.r[s])).astype(int)
    # ring rank: 0 = outermost light (slot 2), 1 = slots 1/3, 2 = slots 0/4 (by the stem)
    ring_rank = np.where(meta.ring, np.abs(meta.slot - 2), -1)
    g = {"n": n, "nbp": nbp, "rod": rod, "rod_bp_z": rod_bp_z, "lol_bp_z": lol_bp_z,
         "spacing": float(np.diff(lol_bp_z).mean()) if nbp > 1 else 4.5,
         "side": np.searchsorted(np.unique(meta.output), meta.output),   # 0 / 1 per strand
         "bp": meta.base_pair.astype(int), "stem_rank": stem_rank, "ring_rank": ring_rank,
         "zbase": float(rod_bp_z.min()) - TIP_SOFT}
    opts["_geom"] = g
    return g


GREEN_HUES = (0.17, 0.48)     # generated schemes stay out of yellow-green .. cyan


def _flower_hue(u):
    lo, hi = GREEN_HUES
    return (hi + u * (1 - (hi - lo))) % 1.0


def _scheme(opts, k):
    if opts["scheme"] is not None:
        return opts["scheme"]
    seed = opts["seed"]
    pal = opts["palette"]
    names = list(FLOWER_LIBRARY)
    if pal == "random":
        pal = "generated" if hash01(seed, k, 23) < 0.3 else "library"
    if pal == "library":
        pal = names[int(hash01(seed, k, 20) * len(names))]
    if pal != "generated":
        return np.array([color(c) for c in FLOWER_LIBRARY[pal]])
    h = _flower_hue(hash01(seed, k, 21))
    if hash01(seed, k, 22) < 0.5:          # gradient: saturated tip to a deeper center
        return np.array([hsv(h, 1.0, 1.0), hsv(h, 0.8, 1.0), hsv(h, 1.0, 0.6)])
    # contrast: petals in one hue, a center in another (also not green)
    c = _flower_hue(hash01(seed, k, 24))
    return np.array([hsv(h, 0.9, 1.0), hsv(h, 0.7, 1.0), hsv(c, 1.0, 1.0)])


def _cycle(opts, g, k):
    """Everything random about plant k (cached)."""
    cache = opts["_cycles"]
    if k in cache:
        return cache[k]
    seed = opts["seed"]
    nbp = g["nbp"]
    G = opts["grow"] * (1 + opts["jitter"] * (2 * hash01(seed, k, 1) - 1))
    lo = min(nbp - 1, int(np.ceil(opts["min_h"] * (nbp - 1))))
    top_bp = lo + int(hash01(seed, k, 2) * (nbp - lo))          # the top lollipops
    # the tip: the rod lights just above the top lollipops (or the top rod lights)
    tip_bp = min(top_bp + 1, nbp - 1)
    tip_z = g["rod_bp_z"][tip_bp]

    hue = 0.27 + 0.09 * hash01(seed, k, 3)                 # yellow-green .. green
    val = 0.35 + 0.55 * hash01(seed, k, 4)                 # the random intensity
    sides, levels = np.arange(2)[:, None], np.arange(3)[None, :]
    n_leaf = 1 + int(hash01(seed, k, 5) * opts["leaf_levels"])
    leaf = (hash01(seed, k, sides, levels, 6) < opts["leaves"]) & (levels < n_leaf)
    leaf_len = np.where(hash01(seed, k, sides, levels, 7) < 0.7, 2, 1)   # stem lights per leaf

    flower = np.zeros((2, 3), bool)                        # [side, level below top]
    chance = opts["flowers"] * np.array(LOWER_FLOWER)[None, :]
    flower[:] = hash01(seed, k, sides, levels, 8) < chance
    flower[:, levels[0] > top_bp] = False                  # nothing below the bottom
    if opts["flowers"] > 0 and not flower[:, 0].any():
        flower[int(hash01(seed, k, 9) * 2), 0] = True

    c = {
        "G": G, "top_bp": top_bp, "tip_z": tip_z,
        "green": hsv(hue, 0.95, val),
        "leaf_green": hsv(hue - 0.02, 0.85, min(1.0, val * 1.15)),
        "bud_green": hsv(hue + 0.05, 1.0, val * 0.45),
        "leaf": leaf, "leaf_len": leaf_len, "flower": flower,
        "scheme": _scheme(opts, k), "has_top": hash01(seed, k, 10) < opts["top_flower"],
        # so leaves line up with the top lollipops when the stem is done
        "leaf_offset": (tip_z - g["lol_bp_z"][top_bp]) / g["spacing"],
        "vary": 0.85 + 0.3 * hash01(seed, k, np.arange(g["n"]), 11),
    }
    if len(cache) > 8:
        cache.clear()
    cache[k] = c
    return c


def _ramp(tau, start, dur):
    return smoothstep(0.0, 1.0, (tau - start) / max(dur, 1e-6))


def render(t, xyz, meta, opts):
    g = _geometry(opts, meta)
    k = int(t // opts["cycle_len"])
    tau = t - k * opts["cycle_len"]
    c = _cycle(opts, g, k)
    G = c["G"]
    out = np.zeros((g["n"], 3))
    bp, side = g["bp"], g["side"]

    # stem up the rod
    tip = g["zbase"] + (c["tip_z"] + TIP_SOFT - g["zbase"]) * np.clip(tau / (STEM_PHASE * G), 0, 1)
    rod = g["rod"]
    rz = meta.z[rod]
    lit = np.where(rz <= c["tip_z"] + 0.01, smoothstep(rz, rz + TIP_SOFT, tip), 0.0)
    out[rod] = c["green"] * (lit * c["vary"][rod])[:, None]
    tip_now = min(tip - TIP_SOFT, c["tip_z"])          # height of the lit tip

    # leaves: on the base pairs just under the tip, sliding up with it.
    # d = base pairs below the tip; level j sits at d = j + leaf_offset.
    stem = g["stem_rank"] >= 0
    s_idx = np.flatnonzero(stem)
    d = (tip_now - g["lol_bp_z"][bp[s_idx]]) / g["spacing"]
    grow = _ramp(tau, LEAF_GROW[0] * G, (LEAF_GROW[1] - LEAF_GROW[0]) * G)
    level = np.zeros(len(s_idx))
    sd, rank = side[s_idx], g["stem_rank"][s_idx]
    for j in range(3):
        w = np.clip(1 - np.abs(d - (j + c["leaf_offset"])), 0, 1)
        has = c["leaf"][sd, j] & (rank < c["leaf_len"][sd, j])
        level = np.maximum(level, w * has)
    # inner light grows first, then outer
    ext = np.clip(grow * 2 - rank, 0, 1)
    out[s_idx] = c["leaf_green"] * (level * ext * c["vary"][s_idx] * (d >= c["leaf_offset"] - 0.5))[:, None]

    # buds then blooms on the top rings, all together
    ring = g["ring_rank"] >= 0
    r_idx = np.flatnonzero(ring)
    lev = c["top_bp"] - bp[r_idx]
    ok = (lev >= 0) & (lev < 3)
    has = np.zeros(len(r_idx), bool)
    has[ok] = c["flower"][side[r_idx][ok], lev[ok]]
    r_idx = r_idx[has]
    if len(r_idx):
        rr = g["ring_rank"][r_idx]
        b = _ramp(tau, BUD[0] * G + (2 - rr) * BUD[1] / 3 * G, BUD[1] / 3 * G)
        w = _ramp(tau, BLOOM[0] * G + rr * BLOOM[1] / 3 * G, BLOOM[1] / 3 * G)
        out[r_idx] = c["bud_green"] * b[:, None] * (1 - w[:, None]) + c["scheme"][rr] * w[:, None]

    # bud and flower at the tip of the stem
    if c["has_top"]:
        tips = rod[np.abs(rz - c["tip_z"]) < 0.01]
        b = _ramp(tau, BUD[0] * G, BUD[1] * G)
        w = _ramp(tau, BLOOM[0] * G, BLOOM[1] * G)
        out[tips] = out[tips] * (1 - b) + (c["bud_green"] * (1 - w) + c["scheme"][0] * w) * b

    # fade out at the end of the cycle
    fade_end = opts["cycle_len"] - GAP
    if opts["fade"] > 0:
        out *= 1 - smoothstep(fade_end - opts["fade"], fade_end, tau)
    elif tau >= fade_end:
        out[:] = 0
    return np.clip(out, 0, 1)
