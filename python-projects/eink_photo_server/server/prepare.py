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
from pathlib import Path

from . import config as cfg
from . import photos, pipelines
from .pipelines.base import load_oriented

log = logging.getLogger(__name__)
KEY_LEN = 16


def params_for(device, photo) -> dict:
    pipe = pipelines.get(device.pipeline)
    return {**pipe.default_params, **device.tuning, **json.loads(photo["params_json"] or "{}")}


def cache_key(device, photo) -> str:
    pipe = pipelines.get(device.pipeline)
    blob = json.dumps({
        "sha": photo["sha"], "pipeline": pipe.name, "version": pipe.version,
        "w": device.width, "h": device.height, "rot": device.output_rotation,
        "params": params_for(device, photo),
        "focal": [photo["focal_x"], photo["focal_y"]],
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:KEY_LEN]


def image_name(device, photo) -> str:
    """Public filename, e.g. '12-3f9a0c1d2e4b5a6f_L.jpg'."""
    return f"{photo['id']}-{cache_key(device, photo)}{pipelines.get(device.pipeline).file_suffix}"


def _cache_dir(device) -> Path:
    d = cfg.DATA_DIR / "cache" / device.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_prepared(device, photo) -> Path:
    pipe = pipelines.get(device.pipeline)
    path = _cache_dir(device) / f"{cache_key(device, photo)}{pipe.file_suffix}"
    if not path.exists():
        img = load_oriented(photos.original_path(photo))
        data = pipe.prepare(img, device, params_for(device, photo),
                            (photo["focal_x"], photo["focal_y"]))
        tmp = path.with_suffix(".tmp")
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

