"""Comets circling every ring, offset per base pair so they spiral."""
import numpy as np

from effects._util import hsv, pulse, wrap

DESCRIPTION = "A comet around each ring, strands spinning opposite ways"

SPEED = 0.5          # ring turns per second
TWIST = 0.1          # phase offset per base pair
TAIL = 0.45          # comet length, fraction of a ring


def render(t, xyz, meta):
    direction = np.where(meta.strand_id == 0, 1.0, -1.0)
    head = direction * SPEED * t + TWIST * meta.base_pair
    d = wrap(direction * (meta.ring_pos - head))       # >0 = ahead of the head
    tail = np.where(d <= 0, pulse(d, TAIL), pulse(d, 0.08))
    hue = 0.55 + 0.25 * meta.bp_frac + 0.5 * meta.strand_id
    out = hsv(hue, 0.85, np.nan_to_num(tail))
    out[meta.stem] = hsv(hue[meta.stem], 1.0, 0.12)
    out[meta.rod] = 0.0
    return out
