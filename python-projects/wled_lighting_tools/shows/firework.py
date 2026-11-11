"""Fireworks on a black background.

A white rocket, one rod light from each strand side by side, climbs the rod
from the bottom. It slows to a random apex, between halfway up and the top,
and bursts. Sparks in a random palette fly outward, then twinkle and drift
down toward the ground as they fade. Launches overlap slightly, so a new
rocket can rise through the last burst's falling sparks.

Everything is seeded per firework from hash01, so render() stays a pure
function of t.
"""
import numpy as np

from shows._util import hash01, hsv

DESCRIPTION = "White rocket up the rod, random-color burst, sparks twinkling down"

CYCLE = 5.0            # seconds between launches (plus jitter)
JITTER = 0.8           # random extra delay per launch, s
APEX_MIN = 0.5         # apex height range, as a fraction of the sculpture's lit height
APEX_MAX = 1.0
LAUNCH_BASE = 1.1      # launch time = LAUNCH_BASE + LAUNCH_PER_H * apex fraction, s
LAUNCH_PER_H = 0.7
ROCKET_SIGMA = 1.6     # rocket glow along the rod, inches (rod lights are 4.5" apart)
TRAIL = 9.0            # length of the faint trail under the rocket, inches

SPARKS = 48
BURST_LIFE = 3.6       # s from burst to the last spark fading out
SPREAD_MIN, SPREAD_MAX = 10.0, 16.0    # final burst radius, inches
SPREAD_TAU = 0.35      # how quickly the burst expands, s
FALL = 4.0             # spark drop = FALL * tau^2, inches
SPARK_SIGMA = 2.6      # how far a spark lights nearby bulbs, inches
FLASH = 0.15           # white-hot flash at the start of the burst, s


def _firework(k, t, meta, zlo, zhi, rod_z_max):
    """Contribution (N, 3) of firework k at absolute time t, or None if not alive."""
    start = k * CYCLE + JITTER * hash01(k, 1)
    tau = t - start
    apex_frac = APEX_MIN + (APEX_MAX - APEX_MIN) * hash01(k, 2)
    apex_z = min(zlo + apex_frac * (zhi - zlo), rod_z_max)
    launch = LAUNCH_BASE + LAUNCH_PER_H * apex_frac
    if tau < 0 or tau > launch + BURST_LIFE:
        return None

    out = np.zeros((meta.n, 3))
    if tau < launch:
        # Rocket: ease-out climb along the rod, white, with a short dim trail
        u = tau / launch
        z = zlo - 3 + (apex_z - zlo + 3) * (1 - (1 - u) ** 2)
        dz = meta.z - z
        glow = np.exp(-0.5 * (dz / ROCKET_SIGMA) ** 2)
        trail = np.where((dz < 0) & (dz > -TRAIL), 0.18 * (1 + dz / TRAIL), 0.0)
        flick = 0.85 + 0.15 * hash01(meta.index, int(t * 30), k)
        v = np.where(meta.rod, np.maximum(glow, trail) * flick, 0.0)
        out += v[:, None]
        return out

    # Burst: sparks from a point on the rod at the apex
    bt = tau - launch
    i = np.arange(SPARKS)
    # random directions, flattened a little so the burst fills the rings
    zc = 2 * hash01(k, i, 3) - 1
    ph = 2 * np.pi * hash01(k, i, 4)
    rr = np.sqrt(1 - zc ** 2)
    dirs = np.stack([rr * np.cos(ph), rr * np.sin(ph), 0.65 * zc], axis=1)
    reach = SPREAD_MIN + (SPREAD_MAX - SPREAD_MIN) * hash01(k, i, 5)
    dist = reach * (1 - np.exp(-bt / SPREAD_TAU))
    pos = dirs * dist[:, None]
    pos[:, 2] += apex_z - FALL * bt ** 2

    # palette: 1-3 hues per firework; each spark takes one, slightly jittered
    n_hues = 1 + int(3 * hash01(k, 6))
    hues = hash01(k, np.arange(n_hues), 7)
    hue = hues[(hash01(k, i, 8) * n_hues).astype(int)] + 0.04 * (hash01(k, i, 9) - 0.5)
    color = hsv(hue, 0.75 + 0.25 * hash01(k, i, 10), 1.0)
    white = np.clip(1 - bt / FLASH, 0, 1)
    color = color * (1 - white) + white

    # fade, with twinkle that grows as the sparks fall
    life = BURST_LIFE * (0.7 + 0.3 * hash01(k, i, 11))
    fade = np.clip(1 - bt / life, 0, 1) ** 1.5
    tw_amt = np.clip((bt - 0.4) / 1.2, 0, 1)
    tw = hash01(k, i, int(t * 14)) > 0.45
    b = fade * ((1 - tw_amt) + tw_amt * tw * (0.6 + 0.4 * hash01(k, i, int(t * 14), 12)))

    d2 = ((meta.xyz[:, None, :] - pos[None, :, :]) ** 2).sum(axis=2)       # (N, SPARKS)
    w = np.exp(-0.5 * d2 / SPARK_SIGMA ** 2) * b[None, :]
    out += w @ color
    return out


def render(t, xyz, meta):
    zlo, zhi = meta.z.min(), meta.z.max()
    rod_z_max = meta.z[meta.rod].max()
    out = np.zeros((meta.n, 3))
    k = int(t // CYCLE)
    for kk in (k - 2, k - 1, k):
        if kk < 0:
            continue
        f = _firework(kk, t, meta, zlo, zhi, rod_z_max)
        if f is not None:
            out += f
    return np.clip(out, 0, 1)
