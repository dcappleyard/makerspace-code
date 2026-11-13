"""Read, validate and save the dashboard-editable part of config.yaml.

Only the schedule: section is edited. The file is rewritten with ruamel.yaml
(round-trip), so comments, key order and the other sections are kept; only keys
whose value changed are touched. Writes go to a temp file that replaces the
config atomically, with the previous version kept as config.yaml.bak.

The runner itself reads the file with PyYAML (YAML 1.1), so values are written
in a form both agree on: clock times like "23:00" are always quoted (1.1 would
read a bare 23:00 as the number 1380).
"""
import io
import os
import re
import shutil

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

import shows
from runner import parse_rotation
from schedule import Schedule
from testpattern import load_config

SCALARS = {                      # key: (type, default)
    "brightness": (int, None),
    "scale": (float, 1.0),
    "minutes_each": (float, 10.0),
    "shuffle": (bool, False),
    "transition_seconds": (float, 2.0),
    "reassert_on": (bool, False),
}


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


def _norm_entry(item, default_minutes):
    """Rotation item (str or dict) -> {"item": "name"|"wled:N", "minutes": float|None, "options": dict}."""
    minutes, options = None, {}
    if isinstance(item, dict):
        minutes = item.get("minutes")
        options = dict(item.get("options") or {})
        item = f"wled:{item['wled']}" if "wled" in item else item.get("show")
    return {"item": str(item).strip(), "minutes": minutes, "options": options}


def read_settings(path):
    """The editable settings as plain data, for GET /api/settings."""
    cfg = _plain(load_config(path))
    sc = cfg.get("schedule", {})
    wins = sc.get("windows") or [{"on": sc.get("on"), "off": sc.get("off")}]
    out = {"windows": [{"on": str(w.get("on")), "off": str(w.get("off"))} for w in wins]}
    for k, (typ, default) in SCALARS.items():
        out[k] = sc.get(k, default)
    out["rotation"] = [_norm_entry(i, out["minutes_each"]) for i in sc.get("rotation", [])]
    return out


def _to_rotation_item(e):
    item, minutes, options = e["item"], e.get("minutes"), e.get("options") or {}
    if minutes in ("", None) and not options:
        return item
    if item.startswith("wled:"):
        m = CommentedMap(wled=int(item[5:]))
    else:
        m = CommentedMap(show=item)
    if minutes not in ("", None):
        m["minutes"] = float(minutes) if float(minutes) != int(float(minutes)) else int(float(minutes))
    if options and not item.startswith("wled:"):
        o = CommentedMap(options)
        o.fa.set_flow_style()
        m["options"] = o
    m.fa.set_flow_style()
    return m


def _replace_seq(old, new_items):
    """Fill the existing CommentedSeq `old` with `new_items`, carrying comments
    along: an item that is kept keeps its inline comment, and the comment lines
    trailing the list (e.g. commented-out examples) stay at the end."""
    if not isinstance(old, CommentedSeq):
        return CommentedSeq(new_items), ""
    olds = [_plain(x) for x in old]
    cas = {i: old.ca.items.get(i) for i in range(len(old))}
    tail = ""
    if olds and cas.get(len(olds) - 1) and cas[len(olds) - 1][0] is not None:
        tok = cas[len(olds) - 1][0]
        inline, sep, rest = tok.value.partition("\n")
        tail = sep + rest if sep else ""
        tok.value = inline + "\n"                     # last item's own inline comment
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
    lines that trailed the old list are re-attached in front of the next key
    (ruamel drops them if they hang off an item that was replaced)."""
    seq, tail = _replace_seq(parent.get(key), items)
    parent[key] = seq
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return
    keys = list(parent.keys())
    nxt = keys[keys.index(key) + 1] if keys.index(key) + 1 < len(keys) else None
    text = [ln[1:][1:] if ln[1:].startswith(" ") else ln[1:] for ln in lines]   # drop "# "
    if nxt is not None:
        parent.yaml_set_comment_before_after_key(nxt, before="\n".join(text), indent=4)
    elif len(seq):                     # list is the last key: hang them off its last item
        from ruamel.yaml.error import CommentMark
        from ruamel.yaml.tokens import CommentToken
        last = len(seq) - 1
        c = seq.ca.items.get(last)
        block = "".join(f"\n    # {t}" for t in text) + "\n"
        if c and c[0] is not None:
            c[0].value = c[0].value.rstrip("\n") + block
        else:
            seq.ca.items[last] = [CommentToken(block, CommentMark(0), None), None]


def _time_str(s):
    s = str(s).strip()
    return DoubleQuotedScalarString(s) if re.fullmatch(r"\d{1,2}:\d{2}", s) else s


def validate(settings, base_cfg, layout):
    """Check edited settings; returns the new full config (plain dict, as the
    runner would load it). Raises ValueError listing every problem found."""
    errors = []
    s = dict(settings)
    sc = dict(base_cfg.get("schedule", {}))
    sc.pop("on", None), sc.pop("off", None), sc.pop(True, None), sc.pop(False, None)

    wins = s.get("windows") or []
    if not wins:
        errors.append("at least one on/off window is needed")
    sc["windows"] = [{"on": str(w.get("on", "")).strip(), "off": str(w.get("off", "")).strip()} for w in wins]
    for k, (typ, default) in SCALARS.items():
        v = s.get(k, sc.get(k, default))
        if v in ("", None):
            if k == "brightness":
                sc.pop(k, None)
                continue
            v = default
        try:
            sc[k] = typ(v) if typ is not bool else bool(v)
        except (TypeError, ValueError):
            errors.append(f"{k}: not a {typ.__name__}: {v!r}")
    if "scale" in sc and not 0 <= sc["scale"] <= 1:
        errors.append("scale must be between 0 and 1")
    if sc.get("brightness") is not None and not 0 <= sc["brightness"] <= 255:
        errors.append("brightness must be 0-255")
    for k in ("minutes_each", "transition_seconds"):
        if k in sc and sc[k] < 0:
            errors.append(f"{k} can't be negative")

    rot = s.get("rotation") or []
    if not rot:
        errors.append("the rotation is empty")
    known = set(shows.available())
    items = []
    for n, e in enumerate(rot, 1):
        item = str(e.get("item", "")).strip()
        if item.startswith("wled:"):
            if not item[5:].strip().isdigit():
                errors.append(f"rotation #{n}: bad preset {item!r} (use wled:<number>)")
                continue
        elif item not in known:
            errors.append(f"rotation #{n}: no show {item!r}")
            continue
        m = e.get("minutes")
        if m not in ("", None):
            try:
                if float(m) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"rotation #{n} ({item}): minutes must be a positive number")
                continue
        opts = e.get("options") or {}
        if opts and not item.startswith("wled:"):
            try:
                shows.Player(item, layout, options=opts)      # runs the show's prepare()
            except Exception as ex:
                errors.append(f"rotation #{n} ({item}): {ex}")
                continue
        items.append({"item": item, "minutes": m, "options": opts})

    cfg = {**base_cfg, "schedule": sc}
    if not errors:
        sc["rotation"] = [_plain(_to_rotation_item(e)) for e in items]
        try:
            Schedule.from_config(cfg)
        except Exception as ex:
            errors.append(f"windows: {ex}")
        if len(parse_rotation(sc)) != len(items):
            errors.append("some rotation entries didn't parse (see log)")
    if errors:
        raise ValueError("; ".join(errors))
    cfg["_items"] = items
    return cfg


def save(path, cfg):
    """Write the validated config's schedule: section into the file at `path`."""
    y = _yaml()
    doc = y.load(path.read_text()) if path.exists() else CommentedMap()
    if doc is None:
        doc = CommentedMap()
    if "schedule" not in doc or doc["schedule"] is None:
        doc["schedule"] = CommentedMap()
    sd = doc["schedule"]
    new = cfg["schedule"]

    # windows (replace the legacy single on/off pair with a windows: list)
    for k in ("on", "off"):
        if k in sd:
            del sd[k]
    old_w = [{"on": str(w.get("on")), "off": str(w.get("off"))} for w in (sd.get("windows") or [])]
    if old_w != new["windows"]:
        items = [CommentedMap([("on", _time_str(w["on"])), ("off", _time_str(w["off"]))])
                 for w in new["windows"]]
        _put_seq(sd, "windows", items)

    for k in SCALARS:
        if k not in new:
            if k in sd:
                del sd[k]
        elif _plain(sd.get(k)) != new[k]:
            v = new[k]
            if isinstance(v, float) and v.is_integer() and k != "scale":
                v = int(v)
            sd[k] = v

    if _plain(sd.get("rotation")) != new["rotation"]:
        _put_seq(sd, "rotation", [_to_rotation_item(e) for e in cfg["_items"]])

    buf = io.StringIO()
    y.dump(doc, buf)
    text = buf.getvalue()

    # Round-trip check with the runner's own loader before replacing anything.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    try:
        back = _plain(load_config(tmp)).get("schedule", {})
        want = {k: v for k, v in new.items()}
        got_w = [{"on": str(w.get("on")), "off": str(w.get("off"))} for w in back.get("windows", [])]
        if got_w != want["windows"] or back.get("rotation") != want["rotation"]:
            raise ValueError("written config didn't read back the same; not saved")
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
