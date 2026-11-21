"""Sandworm: a worm breaches from the base, climbs, crosses over and dives back down.

A worm runs along a path of segments. It comes up one way, turns at one of
the top `turn_levels` base pairs (picked at random), and goes back down,
either the same way (head first back over its own body, which shows head on
top where it folds) or a different way, crossing over on the stems. The ways up and down are:
  3to5 / 5to3  the rings of one strand (a segment = one ring's five lights)
  center       the center column: alternately the two rod lights and the
               four inner stem lights at each base pair
The crossover runs along the stems at the turn level: from a strand's ring in
through its outer and inner stem lights, then out along the other strand's
stem to its ring, or down into the rod. Each worm picks its way up at random
(or `track` fixes it) and its way down at random from all three, so a third
of the time it goes back the way it came (`down` can fix or limit this).

Sometimes (`peek`) a worm peeks first: it pops up its way a few rings and
drops back, and after a short dark pause the same worm (same colors, length
and way up) makes its full run.

Distances are measured in rings: one ring = one step, and a center-column or
stem segment (half as far apart) = half a step. So `speed` (steps a second)
gives the same vertical speed on the rings and the center column, and a
worm's length looks about the same on either. Where the body is between two
segments, both are partly lit, so the motion is smooth.

The worm's length is drawn for each worm from a normal distribution
(`length` mean, `length_sd`; 2 to 10 steps). It's colored with a gradient
from head to tail (two or three colors) and dims a little toward the tail,
so you can see which way it's going. After a worm is gone, the sculpture
stays dark for `dark_min` to `dark_max` times as long as that worm was out,
then the next one comes.

Options (play.py -o key=value, or options: in a show entry):
  speed        steps (rings) per second (default 10)
  length       average worm length in steps (default 7)
  length_sd    spread of the length (default 2)
  colors       head-to-tail colors, 2 or 3 (e.g. "gold,orange,brown");
               default None = new random colors for each worm
  track        way up: random (default), 3to5, 5to3 or center
  down         way down: any (default: random, the same way included), other
               (a different way), same (back the way it came), 3to5, 5to3 or center
  peek         chance a worm peeks before its full run (default 0.25; 0 = never)
  turn_levels  the worm crosses over at one of this many top base pairs (default 3)
  dark_min     shortest dark gap, as a multiple of the worm's time out (default 1.5)
  dark_max     longest dark gap (default 4)
  seed         random seed (None = new each run)
"""
import bisect
import math

import numpy as np

from effects._util import color, hash01, hsv

DESCRIPTION = "Worms breach from the base, climb to the top and dive back down"

OPTIONS = {
    "speed": 10.0,
    "length": 7.0,
    "length_sd": 2.0,
    "colors": None,
    "track": "random",
    "down": "any",
    "peek": 0.25,
    "turn_levels": 3,
    "dark_min": 1.5,
    "dark_max": 4.0,
    "seed": None,
}

TRACKS = ("3to5", "5to3", "center")
RING_STEP = 1.0          # path length of a ring segment, in steps
HALF_STEP = 0.5          # ...of a center-column or stem segment (half as far apart)
TAIL_LEVEL = 0.45        # brightness at the tail end (head is 1)
SAMPLES = 8              # body samples per step, for partial lighting
FIRST_DARK = 1.0         # seconds of dark before the first worm
MAX_LENGTH = 10.0
PEEK_LEVELS = (1, 3)     # a peek turns at one of these base pairs (head 2-4 rings up)
PEEK_WAIT = (0.6, 1.8)   # seconds of dark between a peek and its full run


def _num(opts, key, lo=None, hi=None):
    try:
        v = float(opts[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key} should be a number, got {opts[key]!r}") from None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        rng = f"{lo}-{hi}" if hi is not None else f">= {lo}"
        raise ValueError(f"{key} should be {rng}, got {v}")
    return v


def _choice(opts, key, allowed):
    v = str(opts[key] or allowed[0]).strip().lower()
    if v not in allowed:
        raise ValueError(f"{key} should be one of {', '.join(allowed)}; got {opts[key]!r}")
    return v


def prepare(opts):
    seed = int(opts["seed"])
    speed = _num(opts, "speed", 0.5, 100.0)
    length = _num(opts, "length", 1.0, MAX_LENGTH)
    sd = _num(opts, "length_sd", 0.0, 10.0)
    turns = int(_num(opts, "turn_levels", 1, 10))
    dmin = _num(opts, "dark_min", 0.0)
    dmax = _num(opts, "dark_max", 0.0)
    if dmax < dmin:
        raise ValueError(f"dark_max ({dmax}) should be at least dark_min ({dmin})")
    track = _choice(opts, "track", ("random",) + TRACKS)
    down = _choice(opts, "down", ("any", "other", "same") + TRACKS)
    peek = _num(opts, "peek", 0.0, 1.0)
    cols = opts["colors"]
    if isinstance(cols, str):
        cols = None if cols.strip().lower() in ("", "none", "random") else [c for c in cols.split(",") if c.strip()]
    if cols is not None:
        cols = np.array([color(c) for c in cols])
        if not 2 <= len(cols) <= 3:
            raise ValueError("colors should be 2 or 3 colors, head first")
    return {
        **opts,
        "seed": seed, "speed": speed, "length": length, "length_sd": sd,
        "turn_levels": turns, "dark_min": dmin, "dark_max": dmax,
        "track": track, "down": down, "peek": peek, "cols": cols,
        "_geom": None, "_worms": None,
    }


def _geometry(opts, meta):
    """Segments (arrays of pixel indices) by kind, strand and base pair."""
    g = opts["_geom"]
    if g is not None and g["n"] == meta.n:
        return g
    nb = meta.n_base_pairs
    split = 0.5 * (meta.r[meta.stem].min() + meta.r[meta.stem].max())
    inner = meta.stem & (meta.r < split)
    outer = meta.stem & (meta.r >= split)
    seg = lambda m: [np.flatnonzero(m & (meta.base_pair == b)) for b in range(nb)]
    g = {"n": meta.n, "nb": nb,
         "ring": {s: seg(meta.ring & (meta.strand == s)) for s in ("3to5", "5to3")},
         "outer": {s: seg(outer & (meta.strand == s)) for s in ("3to5", "5to3")},
         "inner": {s: seg(inner & (meta.strand == s)) for s in ("3to5", "5to3")},
         "inner_both": seg(inner), "rod": seg(meta.rod)}
    opts["_geom"] = g
    return g


def _path(g, up, down, L):
    """[(pixels, steps)] from the base up `up` to base pair L, across, and down
    `down` (the same way = back down over itself)."""
    path = []
    if up == down:
        if up == "center":
            for b in range(L):
                path += [(g["rod"][b], HALF_STEP), (g["inner_both"][b], HALF_STEP)]
            path.append((g["rod"][L], HALF_STEP))
        else:
            path += [(g["ring"][up][b], RING_STEP) for b in range(L + 1)]
        return path + path[-2::-1]
    if up == "center":
        for b in range(L):
            path += [(g["rod"][b], HALF_STEP), (g["inner_both"][b], HALF_STEP)]
        path.append((g["rod"][L], HALF_STEP))
    else:
        path += [(g["ring"][up][b], RING_STEP) for b in range(L + 1)]
        path += [(g["outer"][up][L], HALF_STEP), (g["inner"][up][L], HALF_STEP)]
    if down == "center":
        if up != "center":
            path.append((g["rod"][L], HALF_STEP))
        for b in range(L - 1, -1, -1):
            path += [(g["inner_both"][b], HALF_STEP), (g["rod"][b], HALF_STEP)]
    else:
        path += [(g["inner"][down][L], HALF_STEP), (g["outer"][down][L], HALF_STEP)]
        path += [(g["ring"][down][b], RING_STEP) for b in range(L, -1, -1)]
    return path


def _worm_colors(opts, k):
    if opts["cols"] is not None:
        return opts["cols"]
    seed = opts["seed"]
    n = 2 + int(hash01(seed, k, 21) < 0.5)
    h0 = hash01(seed, k, 22)
    step = (0.12 + 0.18 * hash01(seed, k, 23)) * (1 if hash01(seed, k, 24) < 0.5 else -1)
    return hsv(h0 + step * np.arange(n), 1.0, 1.0)


def _appearance(opts, path, length):
    steps = np.array([w for _, w in path])
    out = (float(steps.sum()) + length) / opts["speed"]     # until the tail is back under
    return {"path": path, "steps": steps, "ends": np.cumsum(steps),
            "length": length, "out": out}


def _worm(opts, g, k):
    """Worm k as a list of appearances (a peek, then its full run, or just the
    run). Each: path, length, time out, colors, and the dark gap after it."""
    seed = opts["seed"]
    up = opts["track"]
    if up == "random":
        up = TRACKS[int(hash01(seed, k, 1) * len(TRACKS))]
    down = opts["down"]
    if down == "any":
        down = TRACKS[int(hash01(seed, k, 5) * len(TRACKS))]
    elif down == "same":
        down = up
    elif down == "other":
        others = [x for x in TRACKS if x != up]
        down = others[int(hash01(seed, k, 5) * len(others))]
    nb = g["nb"]
    turns = min(opts["turn_levels"], nb)
    L = nb - 1 - int(hash01(seed, k, 6) * turns)
    # normal length (Box-Muller from two hashes)
    u1, u2 = max(float(hash01(seed, k, 2)), 1e-12), float(hash01(seed, k, 3))
    z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    length = min(max(opts["length"] + opts["length_sd"] * z, 2.0), MAX_LENGTH)
    cols = _worm_colors(opts, k)
    run = _appearance(opts, _path(g, up, down, L), length)
    run.update(cols=cols, up=up, down=down, turn=L, peek=False)
    run["dark"] = run["out"] * (opts["dark_min"] + (opts["dark_max"] - opts["dark_min"]) * float(hash01(seed, k, 4)))
    if hash01(seed, k, 7) >= opts["peek"]:
        return [run]
    P = PEEK_LEVELS[0] + int(hash01(seed, k, 8) * (PEEK_LEVELS[1] - PEEK_LEVELS[0] + 1))
    pk = _appearance(opts, _path(g, up, up, min(P, nb - 1)), length)
    pk.update(cols=cols, up=up, down=up, turn=P, peek=True)
    pk["dark"] = PEEK_WAIT[0] + (PEEK_WAIT[1] - PEEK_WAIT[0]) * float(hash01(seed, k, 9))
    return [pk, run]


def _schedule(opts, g, t):
    """Start times of appearances up to time t (grown and cached as t advances)."""
    w = opts["_worms"]
    if w is None:
        w = opts["_worms"] = {"start": [FIRST_DARK], "info": [], "worms": 0}
    while w["start"][-1] <= t:
        for a in _worm(opts, g, w["worms"]):
            w["info"].append(a)
            w["start"].append(w["start"][-1] + a["out"] + a["dark"])
        w["worms"] += 1
    return w


def render(t, xyz, meta, opts):
    g = _geometry(opts, meta)
    out = np.zeros((meta.n, 3))
    w = _schedule(opts, g, t)
    k = bisect.bisect_right(w["start"], t) - 1
    if k < 0 or k >= len(w["info"]):
        return out
    wm = w["info"][k]
    age = t - w["start"][k]
    if age >= wm["out"]:
        return out                                 # dark gap
    length, ends, steps = wm["length"], wm["ends"], wm["steps"]
    # sample the body from head (u = 0) to tail (u = length); d is how far
    # along the path that bit of body is
    u = np.linspace(0.0, length, int(math.ceil(length * SAMPLES)) + 1)
    d = opts["speed"] * age - u
    ok = (d >= 0) & (d < ends[-1])
    if not ok.any():
        return out
    seg = np.searchsorted(ends, d[ok], side="right")
    uu = u[ok]
    n = len(steps)
    cover = np.bincount(seg, minlength=n) / (SAMPLES * steps)    # how full each segment is
    first = np.full(n, np.inf)
    np.minimum.at(first, seg, uu)                                 # the bit nearest the head
    cols = wm["cols"]
    lit = np.flatnonzero(cover > 0)
    f = np.clip(first[lit] / max(length, 1e-9), 0, 1)
    # head-to-tail gradient through the colors, dimming toward the tail
    x = f * (len(cols) - 1)
    i = np.minimum(np.floor(x).astype(int), len(cols) - 2)
    rgb = cols[i] * (1 - (x - i))[:, None] + cols[i + 1] * (x - i)[:, None]
    lvl = np.clip(cover[lit], 0, 1) * (1 - (1 - TAIL_LEVEL) * f)
    # where the worm folds back over itself, the bit nearest the head shows
    taken = np.zeros(meta.n, bool)
    for j in np.argsort(f, kind="stable"):
        px = wm["path"][lit[j]][0]
        px = px[~taken[px]]
        out[px] = rgb[j] * lvl[j]
        taken[px] = True
    return out
