"""Effect modules and the loader.

An effect is a module in this folder with

    def render(t: float, xyz: np.ndarray, meta: Layout) -> np.ndarray   # (N, 3)

`t` is seconds since the effect started, `xyz` is meta.xyz (inches, z up), and
`meta` is a layout.Layout with per-pixel labels (strand, base_pair, part,
slot, masks like meta.ring) and derived geometry (theta, h, ...). Return
uint8 RGB, or floats in 0..1 (the player converts). Keep render a pure
function of t so it looks the same on hardware and in the preview; for
randomness use effects._util.hash01 instead of random.

Optional module attributes: DESCRIPTION (one line).
Files starting with "_" are helpers, not effects.

Options: an effect that takes settings defines OPTIONS = {name: default} and
render(t, xyz, meta, opts). Options come from play.py (-o key=value), a
rotation entry's options: in config.yaml, or the defaults. An optional
prepare(opts) -> opts parses/validates them once (raise ValueError for bad
ones) instead of on every frame. An option "seed" left at None gets a random
value per run (printed by play.py, re-rolled by the preview's Restart), so a
"random" effect is still a pure function of t within a run.
"""
import importlib
import pkgutil
import random
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def available():
    return sorted(m.name for m in pkgutil.iter_modules([str(HERE)]) if not m.name.startswith("_"))


def load(name):
    mod = importlib.import_module(f"effects.{name}")
    if not callable(getattr(mod, "render", None)):
        raise ValueError(f"effects/{name}.py has no render(t, xyz, meta)")
    return mod


def path_of(name):
    return HERE / f"{name}.py"


class Player:
    """Runs one effect against the clock and returns DDP-ready frames.

    Used by play.py, the preview server, and (later) the runner. With
    reload=True the effect file is re-imported when it changes on disk. An effect
    that raises keeps its last good frame, and the error is kept in .error.
    """

    def __init__(self, name, layout, scale=1.0, reload=False, options=None):
        self.name, self.layout, self.scale, self.reload = name, layout, scale, reload
        self.options = dict(options or {})     # as given; defaults fill the rest
        self.mod = load(name)
        self._auto_seed = False
        self.raw_opts, self.opts = self._resolve(self.mod)
        self.t0 = time.monotonic()
        self.reload_error = None     # last failed re-import (old module keeps running)
        self.render_error = None     # last render() exception
        self._mtime = self._stat()
        self._next_check = 0.0
        self._last = bytes(3 * layout.n)

    def _resolve(self, mod, reroll=False):
        """(merged options, prepared options) for mod; raises ValueError."""
        defaults = getattr(mod, "OPTIONS", None)
        if defaults is None:
            if self.options:
                raise ValueError(f"effect '{self.name}' takes no options")
            return {}, None
        unknown = set(self.options) - set(defaults)
        if unknown:
            raise ValueError(f"effect '{self.name}' has no option(s) {', '.join(sorted(unknown))}; "
                             f"it takes {', '.join(defaults)}")
        raw = {**defaults, **self.options}
        if "seed" in raw and raw["seed"] is None:
            self._auto_seed = True
        if self._auto_seed:
            old = getattr(self, "raw_opts", {}).get("seed")
            raw["seed"] = random.randrange(1 << 31) if (reroll or old is None) else old
        prep = getattr(mod, "prepare", None)
        return raw, (prep(dict(raw)) if prep else raw)

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
                mod = importlib.reload(self.mod)
                self.raw_opts, self.opts = self._resolve(mod)
                self.mod = mod
                self.reload_error = None
            except Exception as e:                       # syntax error etc.
                self.reload_error = f"reload failed, still running the previous version: {type(e).__name__}: {e}"

    @property
    def error(self):
        return self.reload_error or self.render_error

    def restart(self, reroll=False):
        """Restart the clock; reroll=True also picks a new random seed (if auto)."""
        if reroll and self._auto_seed:
            self.raw_opts, self.opts = self._resolve(self.mod, reroll=True)
        self.t0 = time.monotonic()

    def frame(self):
        now = time.monotonic()
        if self.reload:
            self._maybe_reload(now)
        try:
            t = now - self.t0
            if self.opts is None:
                out = self.mod.render(t, self.layout.xyz, self.layout)
            else:
                out = self.mod.render(t, self.layout.xyz, self.layout, self.opts)
            a = to_frame(out, self.layout.n)
            if self.scale != 1.0:
                a = (a * self.scale + 0.5).astype(np.uint8)
            self._last = a.tobytes()
            self.render_error = None
        except Exception as e:
            self.render_error = f"{type(e).__name__}: {e}"
        return self._last


def parse_option(text):
    """'key=value' from the command line -> (key, value); value as bool/None/int/float/str."""
    if "=" not in text:
        raise ValueError(f"option {text!r} should be key=value")
    k, v = (x.strip() for x in text.split("=", 1))
    low = v.lower()
    if low in ("true", "yes"):
        return k, True
    if low in ("false", "no"):
        return k, False
    if low in ("none", "null", ""):
        return k, None
    for typ in (int, float):
        try:
            return k, typ(v)
        except ValueError:
            pass
    return k, v


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
