"""Warm-white twinkle over a dim glow."""
import numpy as np

from effects._util import hash01, rgb

DESCRIPTION = "Calm warm-white twinkle"

WARM = rgb("#ffb060")
BASE = 0.12
RATE = 0.35          # twinkle slots per second, per pixel
CHANCE = 0.45        # fraction of slots that twinkle


def render(t, xyz, meta):
    idx = meta.index
    offset = hash01(idx, 1)                      # desync pixels
    slot_t = t * RATE + offset
    k = np.floor(slot_t).astype(np.int64)
    f = slot_t - k                               # 0..1 within the slot
    on = hash01(idx, k) < CHANCE
    peak = 0.5 + 0.5 * hash01(idx, k, 7)
    env = np.sin(np.pi * f) ** 2 * peak * on
    v = BASE + (1 - BASE) * env
    return WARM * v[:, None]
