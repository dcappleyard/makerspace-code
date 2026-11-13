"""Rainbow wrapped around the helix, slowly rotating upward."""
import numpy as np

from effects._util import hsv

DESCRIPTION = "Rainbow keyed to each lollipop's angle, climbing the helix"

SPEED = 0.06        # hue turns per second
CLIMB = 0.5         # extra hue shift from bottom to top


def render(t, xyz, meta):
    h = meta.lollipop_theta / (2 * np.pi) + CLIMB * meta.h - SPEED * t
    v = np.where(meta.rod, 0.6, 1.0)
    return hsv(h, 1.0, v)
