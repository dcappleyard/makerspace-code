"""Pulses flowing along each strand's wire, from the plug end up."""
import numpy as np

from shows._util import pulse, rgb, wrap

DESCRIPTION = "Pulses travel up each strand in wiring order, one color per strand"

COLORS = (rgb("#00d0ff"), rgb("#ff20c0"))   # 3to5, 5to3
PULSES = 3           # pulses on a strand at once
SPEED = 0.18         # strand lengths per second
WIDTH = 0.06         # pulse half-width, fraction of the strand
BASE = 0.06


def render(t, xyz, meta):
    color = np.array([COLORS[s] for s in meta.strand_id])
    ph = wrap(meta.strand_pos * PULSES - SPEED * PULSES * t)
    v = BASE + (1 - BASE) * pulse(ph, WIDTH * PULSES)
    return color * v[:, None]
