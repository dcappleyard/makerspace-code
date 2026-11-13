"""Read, validate and save the dashboard-editable part of the config.

The dashboard edits the schedule: section and the shows: map. The file is
rewritten with ruamel.yaml (round-trip), so comments, key order and the other
sections are kept; only values that changed are touched. Writes go to a temp
file that replaces the config atomically, with the previous version kept as
config.yaml.bak.

A pre-shows config (schedule.rotation, no shows:) reads as one show,
"evening"; the first save writes it as shows: and drops schedule.rotation.

The runner reads the file with PyYAML (YAML 1.1), so values are written in a
form both agree on: clock times like "23:00" are always quoted (1.1 would read
a bare 23:00 as the number 1380).
"""
import io
import os
import re
import shutil

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

import effects
import shows
from schedule import Schedule
from testpattern import load_config

GLOBALS = {                      # schedule: key -> (type, default)
    "brightness": (int, None),
    "scale": (float, 1.0),
    "minutes_each": (float, 10.0),
    "shuffle": (bool, False),
    "transition_seconds": (float, 2.0),
    "reassert_on": (bool, False),
}
PER_SHOW = {k: GLOBALS[k] for k in shows.SHOW_KEYS}


def _yaml():
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _plain(x):
    """ruamel/PyYAML values -> plain JSON-able Python."""
    if isinstance(x, dict):
        return {("on" if k is True else "off" if k is False else str(k)): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, str):
        return str(x)
    return x


def _num(v):
    """Whole floats as ints, so YAML says 10 rather than 10.0."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


# ------------------------------------------------------------------ read
def _norm_entry(raw):
    item, minutes, options = shows.entry_item(raw)
    return {"item": item, "minutes": minutes, "options": dict(options or {})}


def read_settings(path):
    """The editable settings as plain data, for GET /api/settings."""
    cfg = _plain(load_config(path))
    sc = cfg.get("schedule", {})
    raw = shows.raw_shows(cfg)
    names = [str(n) for n in raw]
    out = {"legacy": not cfg.get("shows") and bool(sc.get("rotation"))}
    wins = sc.get("windows") or [{"on": sc.get("on"), "off": sc.get("off")}]
    sched = {"default_show": shows.default_show_name(cfg, names),
             "windows": [{"on": str(w.get("on")), "off": str(w.get("off")), "show": w.get("show")}
                         for w in wins]}
    for k, (typ, default) in GLOBALS.items():
        sched[k] = sc.get(k, default)
    out["schedule"] = sched
    out["shows"] = {}
    for name, body in raw.items():
        body = body or {}
        s = {"effects": [_norm_entry(e) for e in body.get("effects") or []]}
        for k in PER_SHOW:
            s[k] = body.get(k)          # None = use the global value
        out["shows"][str(name)] = s
    return out


# ------------------------------------------------------------------ validate
def _typed(errors, where, k, v, typ):
    try:
        return typ(v) if typ is not bool else bool(v)
    except (TypeError, ValueError):
        errors.append(f"{where}{k}: not a {typ.__name__}: {v!r}")
        return None


def _check_ranges(errors, where, d):
    if d.get("scale") is not None and not 0 <= d["scale"] <= 1:
        errors.append(f"{where}scale must be between 0 and 1")
    if d.get("brightness") is not None and not 0 <= d["brightness"] <= 255:
        errors.append(f"{where}brightness must be 0-255")
    if d.get("minutes_each") is not None and d["minutes_each"] <= 0:
        errors.append(f"{where}minutes per effect must be positive")
    if d.get("transition_seconds") is not None and d["transition_seconds"] < 0:
        errors.append(f"{where}crossfade can't be negative")


def _entry_out(e):
    """Validated entry -> what goes in the config: a bare name, wled:<id>, or a map."""
    item, minutes, options = e["item"], e.get("minutes"), e.get("options") or {}
    if minutes in ("", None) and not options:
        return item
    out = {"wled": int(item[5:])} if item.startswith("wled:") else {"effect": item}
    if minutes not in ("", None):
        out["minutes"] = _num(float(minutes))
    if options and not item.startswith("wled:"):
        out["options"] = dict(options)
    return out


def validate(settings, base_cfg, layout):
    """Check edited settings. Returns the new full config as the runner would
    load it (plain dicts). Raises ValueError listing every problem found."""
    errors = []
    s_in = settings.get("schedule") or {}
    shows_in = settings.get("shows") or {}

    # shows
    new_shows = {}
    if not shows_in:
        errors.append("there are no shows")
    for name, body in shows_in.items():
        where = f"show {name}: "
        if not shows.NAME_RE.match(str(name)):
            errors.append(f"show name {name!r}: use lowercase letters, digits, - or _ (max 32)")
            continue
        out = {}
        for k, (typ, _) in PER_SHOW.items():
            v = (body or {}).get(k)
            if v not in (None, ""):
                out[k] = _typed(errors, where, k, v, typ)
        _check_ranges(errors, where, out)
        ents = (body or {}).get("effects") or []
        if not ents:
            errors.append(f"show {name} has no effects")
        items = []
        for n, e in enumerate(ents, 1):
            item = str(e.get("item", "")).strip()
            opts = e.get("options") or {}
            if opts and not item.startswith("wled:") and item in effects.available():
                try:
                    effects.Player(item, layout, options=opts)       # runs the effect's prepare()
                except Exception as ex:
                    errors.append(f"show {name} #{n} ({item}): {ex}")
                    continue
            items.append({"item": item, "minutes": e.get("minutes"), "options": opts})
        out["effects"] = [_entry_out(e) for e in items]
        try:
            shows.parse_entries(out["effects"], 10, where=f"show {name}", strict=True)
        except ValueError as ex:
            errors.append(str(ex))
        new_shows[str(name)] = {k: (_num(v) if k != "effects" else v) for k, v in out.items()}

    # schedule
    sc = {k: v for k, v in (base_cfg.get("schedule") or {}).items()
          if k not in ("on", "off", True, False, "rotation", "windows")}
    for k, (typ, default) in GLOBALS.items():
        v = s_in.get(k, sc.get(k, default))
        if v in ("", None):
            sc.pop(k, None)
            if k != "brightness":
                sc[k] = default
            continue
        sc[k] = _typed(errors, "", k, v, typ)
    _check_ranges(errors, "", sc)
    default = s_in.get("default_show") or next(iter(new_shows), None)
    if default not in new_shows:
        errors.append(f"default show {default!r} doesn't exist")
    sc["default_show"] = default
    wins = s_in.get("windows") or []
    if not wins:
        errors.append("at least one on/off window is needed")
    sc["windows"] = []
    for n, w in enumerate(wins, 1):
        ww = {"on": str(w.get("on", "")).strip(), "off": str(w.get("off", "")).strip()}
        if w.get("show"):
            if w["show"] not in new_shows:
                errors.append(f"window #{n}: no show {w['show']!r}")
            ww["show"] = w["show"]
        sc["windows"].append(ww)

    cfg = {k: v for k, v in base_cfg.items() if k not in ("schedule", "shows")}
    cfg["schedule"] = sc
    cfg["shows"] = new_shows
    if not errors:
        try:
            Schedule.from_config(cfg, default)
        except Exception as ex:
            errors.append(f"windows: {ex}")
    if errors:
        raise ValueError("; ".join(dict.fromkeys(errors)))
    return cfg


# ------------------------------------------------------------------ write
def _replace_seq(old, new_items):
    """Fill the existing CommentedSeq `old` with `new_items`, carrying comments
    along: an item that is kept keeps its inline comment. Returns (seq, the
    comment lines that trailed the old list)."""
    if not isinstance(old, CommentedSeq):
        return CommentedSeq(new_items), ""
    olds = [_plain(x) for x in old]
    cas = {i: old.ca.items.get(i) for i in range(len(old))}
    tail = ""
    if olds and cas.get(len(olds) - 1) and cas[len(olds) - 1][0] is not None:
        tok = cas[len(olds) - 1][0]
        inline, sep, rest = tok.value.partition("\n")
        tail = sep + rest if sep else ""
        tok.value = inline + "\n"
    old.clear()
    old.ca.items.clear()
    used = set()
    for j, item in enumerate(new_items):
        old.append(item)
        for i, v in enumerate(olds):
            if i not in used and v == _plain(item) and cas.get(i):
                used.add(i)
                old.ca.items[j] = cas[i]
                break
    return old, tail


def _put_seq(parent, key, items):
    """parent[key] = items as a list, keeping the old list's comments. Comment
    lines that trailed the old list are re-attached in front of the next key."""
    seq, tail = _replace_seq(parent.get(key), items)
    parent[key] = seq
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return
    keys = list(parent.keys())
    i = keys.index(key) + 1
    text = [ln[1:][1:] if ln[1:].startswith(" ") else ln[1:] for ln in lines]   # drop "# "
    if i < len(keys):
        parent.yaml_set_comment_before_after_key(keys[i], before="\n".join(text), indent=4)


def _time_str(s):
    s = str(s).strip()
    return DoubleQuotedScalarString(s) if re.fullmatch(r"\d{1,2}:\d{2}", s) else s


def _flow(d):
    m = CommentedMap()
    for k, v in d.items():
        m[k] = _flow(v) if isinstance(v, dict) else v
    m.fa.set_flow_style()
    return m


def _effects_items(ents):
    return [_flow(e) if isinstance(e, dict) else e for e in ents]


def _write_show(m, body):
    """Update a show's CommentedMap in place from its validated body."""
    for k in PER_SHOW:
        if k in body:
            if _plain(m.get(k)) != body[k]:
                m[k] = body[k]
        elif k in m:
            del m[k]
    if _plain(m.get("effects")) != body["effects"]:
        _put_seq(m, "effects", _effects_items(body["effects"]))


def save(path, cfg):
    """Write the validated config's schedule: and shows: into the file at `path`."""
    y = _yaml()
    doc = (y.load(path.read_text()) if path.exists() else None) or CommentedMap()
    if not isinstance(doc.get("schedule"), CommentedMap):
        doc["schedule"] = CommentedMap()
    sd, new = doc["schedule"], cfg["schedule"]

    for k in ("on", "off", "rotation"):          # legacy forms
        if k in sd:
            del sd[k]
    if _plain(sd.get("default_show")) != new["default_show"]:
        if "default_show" not in sd:
            sd.insert(0, "default_show", new["default_show"])
        else:
            sd["default_show"] = new["default_show"]
    old_w = [{k: str(v) for k, v in _plain(w).items()} for w in (sd.get("windows") or [])]
    if old_w != new["windows"]:
        items = []
        for w in new["windows"]:
            m = CommentedMap([("on", _time_str(w["on"])), ("off", _time_str(w["off"]))])
            if w.get("show"):
                m["show"] = w["show"]
            items.append(m)
        _put_seq(sd, "windows", items)
    for k in GLOBALS:
        if k not in new:
            if k in sd:
                del sd[k]
        elif _plain(sd.get(k)) != new[k]:
            sd[k] = _num(new[k]) if k != "scale" else new[k]

    if not isinstance(doc.get("shows"), CommentedMap):
        doc["shows"] = CommentedMap()
    dm = doc["shows"]
    for name in [n for n in dm if n not in cfg["shows"]]:
        del dm[name]
    for name, body in cfg["shows"].items():
        if name not in dm or not isinstance(dm[name], CommentedMap):
            dm[name] = CommentedMap()
        _write_show(dm[name], body)

    buf = io.StringIO()
    y.dump(doc, buf)

    # Read it back with the runner's own loader before replacing anything.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(buf.getvalue())
    try:
        back = _plain(load_config(tmp))
        bs = back.get("schedule", {})
        got_w = [{k: str(v) for k, v in w.items()} for w in bs.get("windows", [])]
        if got_w != new["windows"] or back.get("shows") != cfg["shows"] \
                or bs.get("default_show") != new["default_show"]:
            raise ValueError("written config didn't read back the same; not saved")
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
