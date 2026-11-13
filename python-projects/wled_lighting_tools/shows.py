"""Shows: named lists of effects (plus WLED presets), e.g. "morning", "evening".

Config (see config.example.yaml):

    shows:
      evening:
        effects:                  # effect names, wled:<id>, or {effect: name, minutes: N, options: {...}}
          - rainbow_helix
          - {effect: dna_strand, minutes: 5, options: {motion: up}}
          - wled:1
        scale: 0.8                # optional per-show overrides of the schedule: globals
        minutes_each: 10
        shuffle: false
        transition_seconds: 2

A config with no shows: but a schedule.rotation: (the pre-shows format) loads
as one show, "evening". Entries may also say {show: name} (the old key) for an
effect.
"""
import logging
import re
from dataclasses import dataclass, field

import effects

log = logging.getLogger("runner")

NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
LEGACY_SHOW = "evening"
SHOW_KEYS = ("scale", "minutes_each", "shuffle", "transition_seconds")


@dataclass
class Entry:
    kind: str             # "effect" or "preset"
    name: str             # effect name, or preset id as str
    minutes: float
    options: dict = None  # effect options (entry's options:)

    def __str__(self):
        return self.name if self.kind == "effect" else f"wled:{self.name}"


@dataclass
class Show:
    name: str
    entries: list = field(default_factory=list)
    scale: float = 1.0
    minutes_each: float = 10.0
    shuffle: bool = False
    fade_s: float = 2.0


def entry_item(item):
    """A raw config entry -> (item string, minutes or None, options or None)."""
    minutes, options = None, None
    if isinstance(item, dict):
        minutes = item.get("minutes")
        options = item.get("options")
        if "wled" in item:
            item = f"wled:{item['wled']}"
        else:
            item = item.get("effect", item.get("show"))
    return str(item).strip(), minutes, options


def parse_entries(items, default_minutes, where="rotation", strict=False):
    """Config entries -> [Entry]. Bad entries are logged and skipped, or with
    strict=True raise ValueError listing them all."""
    known = set(effects.available())
    out, errors = [], []
    for n, raw in enumerate(items or [], 1):
        item, minutes, options = entry_item(raw)
        try:
            minutes = float(default_minutes if minutes in (None, "") else minutes)
            if minutes <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{where} #{n} ({item}): minutes must be a positive number")
            continue
        if item.startswith("wled:"):
            pid = item[5:].strip()
            if not pid.isdigit():
                errors.append(f"{where} #{n}: bad preset {item!r} (use wled:<number>)")
                continue
            out.append(Entry("preset", pid, minutes))
        elif item in known:
            out.append(Entry("effect", item, minutes, options or None))
        else:
            errors.append(f"{where} #{n}: no effect {item!r} (have: {', '.join(sorted(known))})")
    if errors:
        if strict:
            raise ValueError("; ".join(errors))
        for e in errors:
            log.error("%s, skipped", e)
    return out


def raw_shows(cfg):
    """The shows: mapping from config, or the legacy schedule.rotation as one show."""
    raw = cfg.get("shows")
    if raw:
        return dict(raw)
    rot = (cfg.get("schedule") or {}).get("rotation")
    return {LEGACY_SHOW: {"effects": rot}} if rot else {}


def default_show_name(cfg, names):
    sc = cfg.get("schedule") or {}
    d = sc.get("default_show")
    if d:
        return str(d)
    if LEGACY_SHOW in names:
        return LEGACY_SHOW
    return next(iter(names), None)


def load_shows(cfg, strict=False):
    """cfg -> ({name: Show}, default show name). Per-show settings fall back to
    the schedule: globals."""
    sc = cfg.get("schedule") or {}
    glob = {"scale": float(sc.get("scale", 1.0)), "minutes_each": float(sc.get("minutes_each", 10)),
            "shuffle": bool(sc.get("shuffle", False)),
            "transition_seconds": float(sc.get("transition_seconds", 2))}
    out, errors = {}, []
    for name, body in raw_shows(cfg).items():
        name = str(name)
        body = body or {}
        if not NAME_RE.match(name):
            errors.append(f"show name {name!r}: use lowercase letters, digits, - or _ (max 32)")
            continue
        vals = {k: body.get(k, glob[k]) for k in SHOW_KEYS}
        try:
            entries = parse_entries(body.get("effects"), vals["minutes_each"], where=f"show {name}", strict=strict)
        except ValueError as e:
            errors.append(str(e))
            continue
        if not entries:
            errors.append(f"show {name} has no (valid) effects")
            continue
        out[name] = Show(name, entries, scale=max(0.0, min(1.0, float(vals["scale"]))),
                         minutes_each=float(vals["minutes_each"]), shuffle=bool(vals["shuffle"]),
                         fade_s=float(vals["transition_seconds"]))
    if errors:
        if strict:
            raise ValueError("; ".join(errors))
        for e in errors:
            log.error("%s", e)
    return out, default_show_name(cfg, list(out))
