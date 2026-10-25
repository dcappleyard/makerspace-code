"""Photo ingest: originals are stored by content hash, so re-uploads are no-ops."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from . import config as cfg
from . import db, sidecar

THUMB_SIZE = (320, 320)


def originals_dir() -> Path:
    return cfg.DATA_DIR / "originals"


def thumbs_dir() -> Path:
    return cfg.DATA_DIR / "thumbs"


def original_path(photo) -> Path:
    if photo["rel_path"]:
        return cfg.DATA_DIR / photo["rel_path"]
    return originals_dir() / f"{photo['sha']}{photo['ext']}"


def thumb_path(photo) -> Path:
    return thumbs_dir() / f"{photo['sha']}.jpg"


def _thumbnail(path: Path, sha: str) -> tuple[int, int]:
    thumbs_dir().mkdir(parents=True, exist_ok=True)
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        thumb = img.convert("RGB")
        thumb.thumbnail(THUMB_SIZE)
        thumb.save(thumbs_dir() / f"{sha}.jpg", quality=85)
    return w, h


def _register(sha: str, filename: str, path: Path, w: int, h: int, source: str,
              rel_path: str | None) -> dict:
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO photos (sha, filename, ext, uploaded_at, width, height, source, rel_path) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sha, Path(filename).name, path.suffix.lower(), datetime.now(timezone.utc).isoformat(),
             w, h, source, rel_path))
        return db.photo(conn, cur.lastrowid)


def ingest(filename: str, data: bytes, sidecar_xml: bytes | None = None, source: str = "library") -> int:
    """Store an uploaded file (content-addressed in originals/) and return its
    photo id (existing id if a duplicate). A sidecar uploaded alongside it is
    stored; otherwise one is created from EXIF (a duplicate keeps its existing
    sidecar unless a new one came with it)."""
    sha = hashlib.sha256(data).hexdigest()
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM photos WHERE sha = ?", (sha,)).fetchone()
    if row:
        if sidecar_xml is not None:
            sidecar.write(row, sidecar.parse(sidecar_xml))
        return row["id"]

    originals_dir().mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or ".jpg"
    path = originals_dir() / f"{sha}{ext}"
    path.write_bytes(data)
    try:
        w, h = _thumbnail(path, sha)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    photo = _register(sha, filename, path, w, h, source, None)
    sidecar.write(photo, sidecar.parse(sidecar_xml) if sidecar_xml is not None else sidecar.from_exif(path))
    return photo["id"]


def ingest_in_place(source_id: str, path: Path, seed: dict | None = None) -> tuple[int, str]:
    """Register a file that already lives in a folder source (it stays where it
    is). Returns (photo id, "stored" | "duplicate"). A same-named .xml beside it
    is used as its sidecar; otherwise `seed` (or EXIF) starts one."""
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    with db.tx() as conn:
        row = conn.execute("SELECT id FROM photos WHERE sha = ?", (sha,)).fetchone()
    if row:
        return row["id"], "duplicate"
    w, h = _thumbnail(path, sha)
    photo = _register(sha, path.name, path, w, h, source_id, str(path.relative_to(cfg.DATA_DIR)))
    existing = sidecar.path_for(photo)
    if existing.exists():
        sidecar.write(photo, sidecar.parse(existing.read_bytes()))   # index its tags
    else:
        meta = sidecar.from_exif(path)
        for k, v in (seed or {}).items():
            if k == "tags":
                meta["tags"] = sidecar.normalize_tags(list(meta.get("tags", [])) + list(v))
            elif v and not meta.get(k):
                meta[k] = v
        sidecar.write(photo, meta)
    return photo["id"], "stored"


def delete(photo_id: int) -> None:
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
        if not p:
            return
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    # For a folder source this removes the file from the folder too, or the
    # next scan would bring it straight back.
    original_path(p).unlink(missing_ok=True)
    thumb_path(p).unlink(missing_ok=True)
    sidecar.path_for(p).unlink(missing_ok=True)
