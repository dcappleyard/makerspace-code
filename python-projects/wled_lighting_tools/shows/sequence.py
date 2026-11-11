"""DNA read-out: each lollipop is a nucleotide, paired with its complement.

A read head climbs the helix one base pair at a time. Colors follow the
common A/T/G/C convention (A green, T red, G yellow, C blue).
"""
import numpy as np

from shows._util import pulse, rgb

DESCRIPTION = "Nucleotide colors per base pair with a read head scanning upward"

SEQUENCE = "GATTACAGCT"          # 3'->5' strand, bottom to top (10 base pairs)
COMPLEMENT = {"A": "T", "T": "A", "G": "C", "C": "G"}
COLORS = {"A": rgb("#20d050"), "T": rgb("#ff2020"), "G": rgb("#ffc000"), "C": rgb("#2050ff")}
CYCLE = 10.0                     # seconds per scan: climb, then a short rest
CLIMB = 0.75                     # fraction of the cycle spent climbing
IDLE = 0.22                      # brightness of base pairs away from the head


def render(t, xyz, meta):
    nbp = meta.n_base_pairs
    bases = np.array([SEQUENCE[bp % len(SEQUENCE)] for bp in meta.base_pair])
    bases = np.where(meta.strand_id == 0, bases, [COMPLEMENT[b] for b in bases])
    color = np.array([COLORS[b] for b in bases])

    ph = (t % CYCLE) / CYCLE
    head = ph / CLIMB * (nbp + 1) - 1           # base pair position, runs past the ends
    near = pulse(meta.base_pair - head, 1.6)
    out = color * (IDLE + (1 - IDLE) * near)[:, None]

    # stems flare as the pair is read (the "bond"); rod lights flash white
    out[meta.stem] = np.minimum(1, out[meta.stem] + 0.35 * near[meta.stem, None])
    rod_glow = pulse(meta.base_pair - head + 0.5, 0.8)       # rod light sits below its lollipop
    out[meta.rod] = (0.08 + 0.92 * rod_glow[meta.rod])[:, None]
    return out
