"""Per-device prepared-image cache.

Output is keyed on everything that affects it (source hash, pipeline + version,
device geometry, merged tuning params, focal point), so changing any of those
yields a new file -- and a new URL, which keeps the frame from reusing a stale
download.

Dashboards (photos rows with kind = 'dashboard') are drawn instead of loaded:
the key covers the dashboard's *model* (every value it will show), so a frame
gets a new URL only when something visible changed. Their files are named
d<dashboard id>-<key> and older ones are pruned, since they churn hourly.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

from . import config as cfg
from . import dashboards, db, photos, pipelines, sidecar
from .pipelines.base import LOW_BATTERY, load_oriented

log = logging.getLogger(__name__)
KEY_LEN = 16


def battery_overlay(device, battery: int | None) -> int | None:
    """The battery % to draw on the image, or None for no overlay."""
    if battery is None or device.battery_monitor == "none":
        return None
    if device.battery_monitor == "low" and battery >= LOW_BATTERY:
        return None
    return max(0, min(100, int(battery)))


def params_for(device, photo, battery: int | None = None) -> dict:
    pipe = pipelines.get(device.pipeline)
    params = {**pipe.default_params, **device.tuning, **json.loads(photo["params_json"] or "{}")}
    # Part of params so it's part of the cache key: a new reading means a new file/URL.
    overlay = battery_overlay(device, battery)
    if overlay is not None:
        params["battery_overlay"] = overlay
    # Same for the caption: editing a photo's title gives a new file/URL.
    if device.captions != "none":
        params["caption"] = sidecar.caption_fields(sidecar.read(photo))
        params["caption_layout"], params["caption_size"] = device.captions, device.caption_px
    return params


def cache_key(device, photo, battery: int | None = None) -> str:
    if db.is_dashboard(photo):
        return dashboard_model(device, photo, battery)[0]
    pipe = pipelines.get(device.pipeline)
    blob = json.dumps({
        "sha": photo["sha"], "pipeline": pipe.name, "version": pipe.version,
        "w": device.width, "h": device.height, "rot": device.output_rotation, "options": device.options,
        "params": params_for(device, photo, battery),
        "focal": [photo["focal_x"], photo["focal_y"]],
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:KEY_LEN]


def image_name(device, photo, battery: int | None = None) -> str:
    """Public filename, e.g. '12-3f9a0c1d2e4b5a6f_L.jpg'."""
    return f"{photo['id']}-{cache_key(device, photo, battery)}{pipelines.get(device.pipeline).file_suffix}"


def name_for_path(device, photo, path: Path) -> str:
    """Public filename for a prepared file (inverse of cached_path)."""
    key = path.name.removesuffix(pipelines.get(device.pipeline).file_suffix).rpartition("-")[2]
    return f"{photo['id']}-{key}{pipelines.get(device.pipeline).file_suffix}"


def cached_path(device, key: str, photo=None) -> Path:
    prefix = f"d{photo['dashboard_id']}-" if db.is_dashboard(photo) else ""
    return _cache_dir(device) / f"{prefix}{key}{pipelines.get(device.pipeline).file_suffix}"


def _cache_dir(device) -> Path:
    d = cfg.DATA_DIR / "cache" / device.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_prepared(device, photo, battery: int | None = None) -> Path:
    if db.is_dashboard(photo):
        return _prepared_dashboard(device, photo, battery)
    pipe = pipelines.get(device.pipeline)
    path = cached_path(device, cache_key(device, photo, battery))
    if not path.exists():
        img = load_oriented(photos.original_path(photo))
        data = pipe.prepare(img, device, params_for(device, photo, battery),
                            (photo["focal_x"], photo["focal_y"]))
        tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")  # unique: prewarm threads
        tmp.write_bytes(data)
        tmp.replace(path)
        log.info("prepared photo %s for %s: %s (%d bytes)", photo["id"], device.id, path.name, len(data))
    return path


def get_preview(device, photo) -> Path | None:
    if db.is_dashboard(photo):
        key, model, dash, settings = dashboard_model(device, photo, None)
        path = _cache_dir(device) / f"d{dash['id']}-{key}_preview.png"
        if not path.exists():
            img = render_dashboard(device, dash, settings, model)
            pipelines.get(device.pipeline).rendered_preview(img, device).save(path)
            _prune(device, dash["id"], keep={path.name})
        return path
    pipe = pipelines.get(device.pipeline)
    path = _cache_dir(device) / f"{cache_key(device, photo)}_preview.png"
    if not path.exists():
        img = pipe.preview(load_oriented(photos.original_path(photo)), device, params_for(device, photo),
                           (photo["focal_x"], photo["focal_y"]))
        if img is None:
            return None
        img.save(path)
    return path



# --- dashboards ----------------------------------------------------------------

def _dashboard_row(photo):
    with db.tx() as conn:
        dash = db.dashboard(conn, photo["dashboard_id"])
    if not dash:
        raise LookupError(f"dashboard {photo['dashboard_id']} was deleted")
    return dash


def dashboard_model(device, photo, battery: int | None = None, settings: dict | None = None,
                    dash=None) -> tuple[str, dict, object, dict]:
    """(cache key, model, dashboards row, settings) for drawing this dashboard
    on this device now. `settings` overrides the saved ones (live UI preview)."""
    from .schedule import utc_now
    dash = dash or _dashboard_row(photo)
    t = dashboards.get(dash["type"])
    settings = settings if settings is not None else dashboards.settings_of(dash)
    model = t.model(settings, {"now": utc_now(), "tz": cfg.config.tz,
                               "battery": battery_overlay(device, battery)})
    pipe = pipelines.get(device.pipeline)
    blob = json.dumps({
        "dashboard": dash["id"], "type": t.name, "type_version": t.version, "settings": settings,
        "model": model, "pipeline": pipe.name, "version": pipe.version,
        "w": device.width, "h": device.height, "rot": device.output_rotation, "options": device.options,
    }, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:KEY_LEN], model, dash, settings


def render_dashboard(device, dash, settings: dict, model: dict):
    """The dashboard drawn on this device's surface (RGB, as mounted)."""
    pipe = pipelines.get(device.pipeline)
    return dashboards.get(dash["type"]).render(model, pipe.surface(device), settings)


def _prepared_dashboard(device, photo, battery) -> Path:
    key, model, dash, settings = dashboard_model(device, photo, battery)
    path = cached_path(device, key, photo)
    if not path.exists():
        img = render_dashboard(device, dash, settings, model)
        data = pipelines.get(device.pipeline).encode_rendered(img, device)
        tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        log.info("rendered dashboard %s for %s: %s (%d bytes)", dash["id"], device.id, path.name, len(data))
        _prune(device, dash["id"], keep={path.name})
    return path


PRUNE_KEEP = 3   # newest renders kept per dashboard per frame (one may be mid-download)


def _prune(device, dashboard_id: int, keep: set[str]) -> None:
    files = sorted(_cache_dir(device).glob(f"d{dashboard_id}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for kind in ("_preview.png", ""):
        group = [f for f in files if f.name.endswith("_preview.png") == bool(kind)]
        for f in group[PRUNE_KEEP:]:
            if f.name not in keep:
                f.unlink(missing_ok=True)
