"""Per-device prepared-image cache.

Output is keyed on everything that affects it (source hash, pipeline + version,
device geometry, merged tuning params, focal point), so changing any of those
yields a new file -- and a new URL, which keeps the frame from reusing a stale
download.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

from . import config as cfg
from . import photos, pipelines, sidecar
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


def cached_path(device, key: str) -> Path:
    return _cache_dir(device) / f"{key}{pipelines.get(device.pipeline).file_suffix}"


def _cache_dir(device) -> Path:
    d = cfg.DATA_DIR / "cache" / device.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_prepared(device, photo, battery: int | None = None) -> Path:
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
    pipe = pipelines.get(device.pipeline)
    path = _cache_dir(device) / f"{cache_key(device, photo)}_preview.png"
    if not path.exists():
        img = pipe.preview(load_oriented(photos.original_path(photo)), device, params_for(device, photo),
                           (photo["focal_x"], photo["focal_y"]))
        if img is None:
            return None
        img.save(path)
    return path

