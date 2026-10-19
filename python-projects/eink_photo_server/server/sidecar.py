"""Per-photo metadata sidecars: the flat <meta> .xml format prepare_image.py
writes, plus a comma-separated <tags> element.

    <meta>
      <artist>…</artist>
      <date>YYYY-MM-DD</date>
      <location>…</location>
      <title>…</title>
      <film>…</film>
      <tags>beach, family</tags>
    </meta>

The file next to the original (originals/<sha>.xml) is the canonical copy; the
photo_tags table is just an index of it for filtering. Elements we don't know
(e.g. prepare_image.py's text_color_*) are kept as-is when the file is
rewritten. Flat elements only, so firmware-style readTag() parsers still work.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

from . import db

FIELDS = ("artist", "date", "location", "title", "film")
LABELS = {"artist": "Artist", "date": "Date", "location": "Location", "title": "Title", "film": "Film"}
_TAG_RE = re.compile(r"<(\w+)>(.*?)</\1>", re.S)


def path_for(originals_dir: Path, sha: str) -> Path:
    return originals_dir / f"{sha}.xml"


def normalize_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    out = []
    for t in tags:
        t = " ".join(str(t).split()).lower()
        if t and t not in out:
            out.append(t)
    return out


def parse(data: bytes | str) -> dict:
    """Parse a sidecar into {field: str, "tags": [..], "extra": {name: str}}.
    Tolerant: missing fields are blank, and malformed XML falls back to a
    regex scan of flat <name>value</name> elements."""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    pairs: list[tuple[str, str]] = []
    try:
        root = ET.fromstring(text)
        pairs = [(el.tag, (el.text or "").strip()) for el in root]
    except ET.ParseError:
        pairs = [(m[1], m[2].strip()) for m in _TAG_RE.finditer(text)]
    meta = {f: "" for f in FIELDS}
    meta["tags"], meta["extra"] = [], {}
    for name, value in pairs:
        if name in FIELDS:
            meta[name] = value
        elif name == "tags":
            meta["tags"] = normalize_tags(value)
        else:
            meta["extra"][name] = value
    return meta


def render(meta: dict) -> str:
    lines = ["<meta>"]
    for f in FIELDS:
        lines.append(f"  <{f}>{escape(meta.get(f, '') or '')}</{f}>")
    lines.append(f"  <tags>{escape(', '.join(normalize_tags(meta.get('tags', []))))}</tags>")
    for name, value in (meta.get("extra") or {}).items():
        if re.fullmatch(r"\w+", name):
            lines.append(f"  <{name}>{escape(value)}</{name}>")
    lines.append("</meta>")
    return "\n".join(lines) + "\n"


def from_exif(image_path: Path) -> dict:
    """A fresh sidecar seeded from EXIF: date (DateTimeOriginal) and artist."""
    meta = {f: "" for f in FIELDS}
    meta["tags"], meta["extra"] = [], {}
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            sub = exif.get_ifd(0x8769)  # Exif IFD
            stamp = sub.get(36867) or sub.get(36868) or exif.get(306)  # DateTimeOriginal/Digitized/DateTime
            if stamp:
                m = re.match(r"(\d{4})[:-](\d{2})[:-](\d{2})", str(stamp))
                if m:
                    meta["date"] = f"{m[1]}-{m[2]}-{m[3]}"
            artist = exif.get(315)
            if artist:
                meta["artist"] = str(artist).strip("\x00 ").strip()
    except Exception:
        pass
    return meta


def caption_fields(meta: dict) -> dict:
    """Just the fields captions use (part of the image cache key)."""
    return {f: meta.get(f, "") for f in FIELDS}


# --- storage ---------------------------------------------------------------

def _originals() -> Path:
    from . import photos
    return photos.originals_dir()


def read(photo) -> dict:
    """The photo's sidecar, created from EXIF if it doesn't exist yet."""
    from . import photos
    path = path_for(_originals(), photo["sha"])
    if path.exists():
        return parse(path.read_bytes())
    meta = from_exif(photos.original_path(photo))
    write(photo, meta)
    return meta


def write(photo, meta: dict) -> dict:
    meta = {**{f: "" for f in FIELDS}, "tags": [], "extra": {}, **meta}
    meta["tags"] = normalize_tags(meta["tags"])
    path = path_for(_originals(), photo["sha"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".xml.tmp")
    tmp.write_text(render(meta), encoding="utf-8")
    tmp.replace(path)
    with db.tx() as conn:
        conn.execute("DELETE FROM photo_tags WHERE photo_id = ?", (photo["id"],))
        conn.executemany("INSERT OR IGNORE INTO photo_tags (photo_id, tag) VALUES (?, ?)",
                         [(photo["id"], t) for t in meta["tags"]])
    return meta


def backfill() -> int:
    """Create missing sidecars (from EXIF) and re-index every photo's tags."""
    with db.tx() as conn:
        rows = conn.execute("SELECT * FROM photos").fetchall()
    for p in rows:
        write(p, read(p))
    return len(rows)
