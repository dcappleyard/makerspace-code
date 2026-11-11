"""Show modules and the loader.

A show is a module in this folder with

    def render(t: float, xyz: np.ndarray, meta: Layout) -> np.ndarray   # (N, 3)

`t` is seconds since the show started, `xyz` is meta.xyz (inches, z up), and
`meta` is a layout.Layout with per-pixel labels (strand, base_pair, part,
slot, masks like meta.ring) and derived geometry (theta, h, ...). Return
uint8 RGB, or floats in 0..1 (the player converts). Keep render a pure
function of t so it looks the same on hardware and in the preview; for
randomness use shows._util.hash01 instead of random.

Optional module attributes: DESCRIPTION (one line).
Files starting with "_" are helpers, not shows.
"""
import importlib
import pkgutil
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def available():
    return sorted(m.name for m in pkgutil.iter_modules([str(HERE)]) if not m.name.startswith("_"))


def load(name):
    mod = importlib.import_module(f"shows.{name}")
    if not callable(getattr(mod, "render", None)):
        raise ValueError(f"shows/{name}.py has no render(t, xyz, meta)")
    return mod


def path_of(name):
    return HERE / f"{name}.py"


class Player:
    """Runs one show against the clock and returns DDP-ready frames.

    Used by play.py, the preview server, and (later) the runner. With
    reload=True the show file is re-imported when it changes on disk. A show
    that raises keeps its last good frame, and the error is kept in .error.
    """

    def __init__(self, name, layout, scale=1.0, reload=False):
        self.name, self.layout, self.scale, self.reload = name, layout, scale, reload
        self.mod = load(name)
        self.t0 = time.monotonic()
        self.reload_error = None     # last failed re-import (old module keeps running)
        self.render_error = None     # last render() exception
        self._mtime = self._stat()
        self._next_check = 0.0
        self._last = bytes(3 * layout.n)

    def _stat(self):
        try:
            return path_of(self.name).stat().st_mtime
        except OSError:
            return None

    def _maybe_reload(self, now):
        if now < self._next_check:
            return
        self._next_check = now + 0.5
        m = self._stat()
        if m != self._mtime:
            self._mtime = m
            try:
                self.mod = importlib.reload(self.mod)
                self.reload_error = None
            except Exception as e:                       # syntax error etc.
                self.reload_error = f"reload failed, still running the previous version: {type(e).__name__}: {e}"

    @property
    def error(self):
        return self.reload_error or self.render_error

    def restart(self):
        self.t0 = time.monotonic()

    def frame(self):
        now = time.monotonic()
        if self.reload:
            self._maybe_reload(now)
        try:
            a = to_frame(self.mod.render(now - self.t0, self.layout.xyz, self.layout), self.layout.n)
            if self.scale != 1.0:
                a = (a * self.scale + 0.5).astype(np.uint8)
            self._last = a.tobytes()
            self.render_error = None
        except Exception as e:
            self.render_error = f"{type(e).__name__}: {e}"
        return self._last


def to_frame(out, n):
    """Validate a render() result and convert it to (n, 3) uint8."""
    a = np.asarray(out)
    if a.shape != (n, 3):
        raise ValueError(f"render returned shape {a.shape}, expected ({n}, 3)")
    if a.dtype != np.uint8:
        if np.issubdtype(a.dtype, np.floating):
            a = np.clip(np.nan_to_num(a) * 255.0 + 0.5, 0, 255)
        else:
            a = np.clip(a, 0, 255)
        a = a.astype(np.uint8)
    return a
