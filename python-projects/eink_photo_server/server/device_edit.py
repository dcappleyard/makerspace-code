"""Edit a frame's commonly adjusted settings from the UI, written back to devices.yaml.

Only the keys in EDITABLE are touched; ids, protocol, pipeline, tokens and
secrets stay hand-edited. The file is rewritten with ruamel.yaml so comments and
key order survive, validated by loading it the same way the server does
(config.Device.from_dict) before it replaces the original (previous version kept
as devices.yaml.bak), then the config is reloaded.

Orientation: width/height are the panel *as mounted* and output_rotation turns
the image to the panel's native orientation. So the UI edits only the rotation;
width/height follow from it (a 90/270 rotation swaps the native size).
"""
from __future__ import annotations

import io
import os
import threading

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from . import config as cfg
from . import pipelines

ROTATIONS = (0, 90, 180, 270)
MIN_INTERVAL = 5          # minutes
_lock = threading.Lock()


class SettingsError(ValueError):
    """A user-fixable problem with the submitted settings."""


def native_size(device) -> tuple[int, int]:
    """The panel's own (unrotated) width x height."""
    if device.output_rotation in (90, 270):
        return device.height, device.width
    return device.width, device.height


def mounted_size(native: tuple[int, int], rotation: int) -> tuple[int, int]:
    nw, nh = native
    return (nh, nw) if rotation in (90, 270) else (nw, nh)


def orientation(w: int, h: int) -> str:
    return "portrait" if h > w else "landscape" if w > h else "square"


def option_choices(device) -> dict[str, tuple]:
    """Pipeline options offered in the UI: {key: (default, other choices...)}."""
    return getattr(pipelines.get(device.pipeline), "editable_options", {})


def _yaml() -> YAML:
    y = YAML()                      # round-trip: keeps comments, order, quoting
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)   # "  - id: ..." as in devices.example.yaml
    return y


def _num(value: str, key: str, integer: bool = False):
    try:
        x = float(value)
    except ValueError:
        raise SettingsError(f"{key}: {value!r} isn't a number") from None
    return int(round(x)) if integer else x


def _hhmm(value: str, key: str) -> str:
    try:
        t = cfg.parse_hhmm(value)
    except (ValueError, TypeError):
        raise SettingsError(f"{key}: {value!r} isn't a time like 07:00") from None
    return f"{t.hour:02d}:{t.minute:02d}"


def _set(m: CommentedMap, key: str, value) -> None:
    """Set or (value None) remove a key, keeping its position and comment."""
    if value is None:
        m.pop(key, None)
    else:
        m[key] = value


def _put(m: CommentedMap, key: str, value, default) -> None:
    """Set a key, but leave it out if the file doesn't have it and it's still the default."""
    if key not in m and value == default:
        return
    m[key] = value


def apply(device_id: str, form: dict) -> list[str]:
    """Update one device in devices.yaml from the settings form. Returns a list
    of what changed (empty if nothing did). Raises SettingsError."""
    with _lock:
        y = _yaml()
        text = cfg.DEVICES_FILE.read_text()
        doc = y.load(text)
        entry = next((d for d in (doc.get("devices") or []) if str(d.get("id")) == device_id), None)
        if entry is None:
            raise SettingsError(f"{device_id} isn't in {cfg.DEVICES_FILE.name}")
        dev = cfg.config.devices[device_id]
        pipe = pipelines.get(dev.pipeline)
        before = {k: entry.get(k) for k in entry}
        before_tuning = dict(entry.get("tuning") or {})
        before_options = dict(entry.get("options") or {})

        name = " ".join(str(form.get("name", "")).split())
        _put(entry, "name", name or device_id, device_id)

        # Orientation: rotation, with width/height following it.
        try:
            rot = int(form.get("output_rotation", dev.output_rotation))
        except ValueError:
            rot = -1
        if rot not in ROTATIONS:
            raise SettingsError("rotation must be 0, 90, 180 or 270")
        w, h = mounted_size(native_size(dev), rot)
        _put(entry, "output_rotation", rot, 0)
        entry["width"], entry["height"] = w, h

        # Default schedule (only used while the frame has no blocks).
        start, end = str(form.get("wake_start", "")).strip(), str(form.get("wake_end", "")).strip()
        if bool(start) != bool(end):
            raise SettingsError("wake hours need both a start and an end (or neither, for all day)")
        if start:
            seq = CommentedSeq([DoubleQuotedScalarString(_hhmm(start, "wake start")),
                                DoubleQuotedScalarString(_hhmm(end, "wake end"))])
            seq.fa.set_flow_style()
            entry["wake_hours"] = seq
        else:
            entry.pop("wake_hours", None)
        interval = str(form.get("interval_minutes", "")).strip()
        if interval:
            n = _num(interval, "interval", integer=True)
            if n < MIN_INTERVAL:
                raise SettingsError(f"interval must be at least {MIN_INTERVAL} min")
            _put(entry, "interval_minutes", n, cfg.Device.interval_minutes)

        # Overlays.
        _put(entry, "battery_monitor", str(form.get("battery_monitor", dev.battery_monitor)), cfg.Device.battery_monitor)
        _put(entry, "captions", str(form.get("captions", dev.captions)), cfg.Device.captions)
        size = str(form.get("caption_size", "")).strip()
        _set(entry, "caption_size", _num(size, "caption size", integer=True) if size else None)

        # Tuning: blank = the pipeline's default (key removed).
        tuning = entry.get("tuning")
        if tuning is None:
            tuning = CommentedMap()
        for key, default in pipe.default_params.items():
            raw = str(form.get(f"tuning.{key}", "")).strip()
            value = _num(raw, key, integer=isinstance(default, int) and not isinstance(default, bool)) if raw else None
            _set(tuning, key, value)
        if tuning:
            entry["tuning"] = tuning
        else:
            entry.pop("tuning", None)

        # Pipeline options offered in the UI (e.g. fit); the first choice is the default.
        options = entry.get("options")
        if options is None:
            options = CommentedMap()
        for key, choices in option_choices(dev).items():
            value = str(form.get(f"options.{key}", choices[0]))
            if value not in choices:
                raise SettingsError(f"{key} must be one of {', '.join(choices)}")
            _put(options, key, value, choices[0])
        if options:
            entry["options"] = options
        else:
            entry.pop("options", None)

        changed = [k for k in set(before) | set(entry)
                   if k not in ("tuning", "options") and before.get(k) != entry.get(k)]
        changed += [f"tuning.{k}" for k in set(before_tuning) | set(entry.get("tuning") or {})
                    if before_tuning.get(k) != (entry.get("tuning") or {}).get(k)]
        changed += [f"options.{k}" for k in set(before_options) | set(entry.get("options") or {})
                    if before_options.get(k) != (entry.get("options") or {}).get(k)]
        if not changed:
            return []

        buf = io.StringIO()
        y.dump(doc, buf)
        new_text = buf.getvalue()
        # Validate exactly as the server will load it.
        try:
            import yaml as pyyaml
            raw = pyyaml.safe_load(new_text) or {}
            for d in raw.get("devices") or []:
                cfg.Device.from_dict(d)
        except Exception as e:
            raise SettingsError(f"not saved -- the result wouldn't load: {e}") from None

        path = cfg.DEVICES_FILE
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(new_text)
        path.with_name(path.name + ".bak").write_text(text)
        os.replace(tmp, path)
        cfg.reload()
        return sorted(changed)
