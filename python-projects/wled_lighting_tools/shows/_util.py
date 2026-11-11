"""Helpers for shows. Colors are floats in 0..1 unless noted."""
import numpy as np


def hsv(h, s=1.0, v=1.0):
    """Vectorized HSV -> RGB. h wraps (0..1 = one turn); returns (..., 3)."""
    h, s, v = np.broadcast_arrays(np.asarray(h, float) % 1.0, np.asarray(s, float), np.asarray(v, float))
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def rgb(hex_or_tuple):
    """'#ff8800' or (255, 136, 0) -> float RGB array."""
    if isinstance(hex_or_tuple, str):
        s = hex_or_tuple.lstrip("#")
        return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)]) / 255.0
    return np.asarray(hex_or_tuple, float) / 255.0


def smoothstep(e0, e1, x):
    x = np.clip((np.asarray(x, float) - e0) / (e1 - e0), 0.0, 1.0)
    return x * x * (3 - 2 * x)


def pulse(d, width):
    """Soft bump: 1 at d == 0, 0 beyond |d| >= width."""
    return np.clip(1 - np.abs(d) / width, 0, 1) ** 2


def wrap(d):
    """Wrap a 0..1 phase difference into -0.5..0.5."""
    return (np.asarray(d) + 0.5) % 1.0 - 0.5


def hash01(*keys):
    """Deterministic pseudo-random 0..1 from integer arrays/scalars (broadcasts)."""
    x = np.uint64(0x9E3779B97F4A7C15)
    with np.errstate(over="ignore"):
        for k in keys:
            x = (x ^ np.asarray(k, dtype=np.uint64)) * np.uint64(0xBF58476D1CE4E5B9)
            x ^= x >> np.uint64(31)
        x = x * np.uint64(0x94D049BB133111EB)
        x ^= x >> np.uint64(29)
    return (x >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def frame(n):
    return np.zeros((n, 3))
