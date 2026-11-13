"""DNA strand: each base pair is a nucleotide and its complement.

Four colors are assigned to the bases A, C, G and T, from the colors option,
a named palette, or (default) four well-separated random hues. Each base pair
gets a random base on the 3'->5' strand and its complement (A-T, G-C) on the
5'->3' strand. Every lollipop shows its base's color as a light stem and a
darker ring. The rod lights are off, or one color.

motion=up/down makes the sequence flow along the helix one base pair at a
time. Because consecutive base pairs are 40 degrees apart, a sequence moving
up reads as the helix turning. New random bases enter at the end it flows
from, so the sequence never repeats.

Options (play.py -o key=value, or options: in a rotation entry):
  colors       4 colors for A,C,G,T: "red,blue,gold,green" or a list;
               names, #rrggbb or [r, g, b]. Overrides palette.
  palette      a name in PALETTES, or "random" (default)
  rod          "off" (default), a color, or "random"
  motion       "static" (default), "up" or "down"
  bpm          base pairs per minute when moving: 60 = one position per
               second (default 30)
  fade         fraction of each step spent crossfading (0 = hard step)
  sequence     fixed bases for the 3'->5' strand, bottom up, e.g. "GATTACA"
               (repeats; with motion it scrolls). Default: random.
  stem_tint    how far stems are lightened toward white, 0-1
  ring_shade   ring brightness relative to the base color, 0-1
  rod_level    rod brightness, 0-1
  seed         random seed (None = new random colors and sequence each run)
"""
import numpy as np

from effects._util import color, hash01, hsv, smoothstep

DESCRIPTION = "Random-sequence base pairs (A-T, G-C) in 4 colors; static or flowing"

BASES = "ACGT"                                    # color order for colors/palettes
COMPLEMENT = {"A": "T", "T": "A", "G": "C", "C": "G"}

# Stock color sets, A, C, G, T. Add holiday sets here.
PALETTES = {
    "classic": ["#20d050", "#2050ff", "#ffc000", "#ff2020"],   # A green, C blue, G yellow, T red (as in sequence.py)
}

OPTIONS = {
    "colors": None,
    "palette": "random",
    "rod": "off",
    "motion": "static",
    "bpm": 30,
    "fade": 0.35,
    "sequence": None,
    "stem_tint": 0.4,
    "ring_shade": 0.55,
    "rod_level": 0.6,
    "seed": None,
}


def _unit(opts, key):
    v = float(opts[key])
    if not 0 <= v <= 1:
        raise ValueError(f"{key} should be 0-1, got {v}")
    return v


def prepare(opts):
    seed = int(opts["seed"])

    cols = opts["colors"]
    if cols is not None:
        if isinstance(cols, str):
            cols = [c for c in cols.split(",") if c.strip()]
        if len(cols) != 4:
            raise ValueError(f"colors needs 4 colors (A, C, G, T), got {len(cols)}")
        base_rgb = np.array([color(c) for c in cols])
    elif opts["palette"] == "random":
        # four hues a quarter turn apart (a little jitter), in random base order
        h0 = hash01(seed, 1)
        hues = h0 + 0.25 * np.arange(4) + 0.06 * (hash01(seed, np.arange(4), 2) - 0.5)
        order = np.argsort(hash01(seed, np.arange(4), 3))
        base_rgb = hsv(hues[order], 0.85 + 0.15 * hash01(seed, np.arange(4), 4), 1.0)
    elif opts["palette"] in PALETTES:
        base_rgb = np.array([color(c) for c in PALETTES[opts["palette"]]])
    else:
        raise ValueError(f"unknown palette {opts['palette']!r} (have: random, {', '.join(PALETTES)})")

    rod = opts["rod"]
    if rod is None or str(rod).lower() == "off":
        rod_rgb = np.zeros(3)
    elif str(rod).lower() == "random":
        rod_rgb = hsv(hash01(seed, 5), 0.6, 1.0)
    else:
        rod_rgb = color(rod)

    if opts["motion"] not in ("static", "up", "down"):
        raise ValueError(f"motion should be static, up or down, got {opts['motion']!r}")
    if float(opts["bpm"]) <= 0:
        raise ValueError(f"bpm should be > 0, got {opts['bpm']}")

    seq = opts["sequence"]
    if seq is not None:
        seq = str(seq).upper()
        if not seq or set(seq) - set(BASES):
            raise ValueError(f"sequence should only use A, C, G, T, got {opts['sequence']!r}")
        seq = np.array([BASES.index(b) for b in seq])

    stem_tint, ring_shade = _unit(opts, "stem_tint"), _unit(opts, "ring_shade")
    return {
        **opts,
        "seed": seed,
        "stem_rgb": base_rgb * (1 - stem_tint) + stem_tint,    # per base, lightened
        "ring_rgb": base_rgb * ring_shade,                     # per base, darker
        "rod_rgb": rod_rgb * _unit(opts, "rod_level"),
        "seq": seq,
        "fade": _unit(opts, "fade"),
        "bpm": float(opts["bpm"]),
    }


COMP_INDEX = np.array([BASES.index(COMPLEMENT[b]) for b in BASES])   # A<->T, C<->G


def _base(opts, j):
    """Base index (0-3, BASES order) on the 3'->5' strand at sequence position j."""
    if opts["seq"] is not None:
        return opts["seq"][j % len(opts["seq"])]
    return (hash01(opts["seed"], j + (1 << 40), 6) * 4).astype(int)


def _colors(opts, j, meta):
    """Per-pixel color for sequence positions j (one per pixel)."""
    b = _base(opts, j)
    b = np.where(meta.strand_id == 0, b, COMP_INDEX[b])
    out = np.where(meta.stem[:, None], opts["stem_rgb"][b], opts["ring_rgb"][b])
    return np.where(meta.rod[:, None], opts["rod_rgb"], out)


def render(t, xyz, meta, opts):
    bp = meta.base_pair.astype(np.int64)
    if opts["motion"] == "static":
        return _colors(opts, bp, meta)

    steps = t * opts["bpm"] / 60.0
    n = int(np.floor(steps))
    frac = steps - n
    # Flowing up, base pair bp shows what was one below it a step ago.
    # j is the sequence position now on bp; next is what moves onto it.
    sign = -1 if opts["motion"] == "up" else 1
    j = bp + sign * n
    cur = _colors(opts, j, meta)
    if opts["fade"] == 0:
        return cur
    nxt = _colors(opts, j + sign, meta)
    w = smoothstep(1 - opts["fade"], 1.0, frac)
    return cur * (1 - w) + nxt * w
