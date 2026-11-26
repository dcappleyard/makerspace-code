"""Data dashboards: the server's second kind of content.

A photo is a file that each pipeline crops, tunes and dithers. A dashboard is
instead *drawn* for each panel at pull time, from live data, with the inks that
panel shows exactly (see draw.py and each pipeline's surface()/encode_rendered()).

Storage: a `dashboards` row (type, name, settings) plus one `photos` row with
kind = 'dashboard', so schedules, playlists, queueing and pulls need no special
cases. prepare.py dispatches on that kind.

A dashboard *type* (one module here, decorated with @register) supplies:
  default_settings / form   the settings and how the web UI edits them
  model(settings, ctx)      everything the screen will show, as plain rounded
                            JSON values. It's part of the image cache key, so a
                            frame only redraws when something visible changed
                            (ESP32 frames are told "keep" otherwise).
  render(model, surface, settings) -> RGB image at the surface's size
  refresh_due(all_settings) called every minute by the background refresher
                            with every dashboard of this type (optional)
  refresh(settings)         fetch now, for the UI's Fetch now button (optional)

To add one: drop a module in this package, subclass DashboardType, @register.
"""
from __future__ import annotations

import importlib
import json
import logging
import pkgutil
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"               # text | number | select | bool
    options: tuple = ()              # select: ((value, label), ...)
    min: float | None = None
    max: float | None = None
    step: float | None = None
    help: str = ""
    group: str = ""


class DashboardType:
    name: str = ""
    label: str = ""
    version: str = "1"   # bump when rendering changes for the same model (cache key)
    default_settings: dict = {}
    form: tuple[Field, ...] = ()

    def model(self, settings: dict, ctx: dict) -> dict:
        raise NotImplementedError

    def render(self, model: dict, surface, settings: dict):
        raise NotImplementedError

    def refresh_due(self, all_settings: list[dict]) -> None:
        pass

    def refresh(self, settings: dict) -> dict:
        return {}

    def status(self, settings: dict) -> dict:
        """Short facts for the UI (last fetch, errors...)."""
        return {}

    # -- settings from a submitted form ------------------------------------------
    def coerce(self, form) -> dict:
        """Validated settings from form fields (unknown keys ignored, bad numbers
        clamped or defaulted)."""
        out = {}
        for f in self.form:
            default = self.default_settings.get(f.key)
            raw = form.get(f.key)
            if f.kind == "bool":
                out[f.key] = raw in ("1", "on", "true", True)
                continue
            if raw is None:
                out[f.key] = default
                continue
            raw = str(raw).strip()
            if f.kind == "number":
                try:
                    v = float(raw)
                except ValueError:
                    v = default
                if f.min is not None:
                    v = max(f.min, v)
                if f.max is not None:
                    v = min(f.max, v)
                out[f.key] = int(v) if isinstance(default, int) and not isinstance(default, bool) else v
            elif f.kind == "select":
                vals = [str(v) for v, _ in f.options]
                out[f.key] = raw if raw in vals else default
            else:
                out[f.key] = raw[:120]
        return out


_registry: dict[str, DashboardType] = {}


def register(cls):
    _registry[cls.name] = cls()
    return cls


def get(name: str) -> DashboardType:
    if name not in _registry:
        raise KeyError(f"unknown dashboard type {name!r} (have: {', '.join(sorted(_registry))})")
    return _registry[name]


def types() -> list[DashboardType]:
    return [_registry[k] for k in sorted(_registry)]


def settings_of(row) -> dict:
    t = get(row["type"])
    return {**t.default_settings, **json.loads(row["settings_json"] or "{}")}


# --- background refresher --------------------------------------------------------

def refresh_all_due() -> None:
    from .. import db
    with db.tx() as conn:
        rows = conn.execute("SELECT * FROM dashboards").fetchall()
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        if r["type"] in _registry:
            by_type.setdefault(r["type"], []).append(settings_of(r))
    for name, all_settings in by_type.items():
        try:
            _registry[name].refresh_due(all_settings)
        except Exception:
            log.exception("refresh of %s dashboards failed", name)


def start_refresher(tick_s: int = 60) -> None:
    def loop():
        while True:
            try:
                refresh_all_due()
            except Exception:
                log.exception("dashboard refresh failed")
            time.sleep(tick_s)

    threading.Thread(target=loop, name="dashboard-refresher", daemon=True).start()


for _m in pkgutil.iter_modules(__path__):
    if _m.name not in ("draw", "nws"):
        importlib.import_module(f"{__name__}.{_m.name}")
