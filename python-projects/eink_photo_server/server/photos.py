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
    return originals_dir() / f"{photo['sha']}{photo['ext']}"


def thumb_path(photo) -> Path:
    return thumbs_dir() / f"{photo['sha']}.jpg"


def ingest(filename: str, data: bytes, sidecar_xml: bytes | None = None) -> int:
    """Store an uploaded file and return its photo id (existing id if a duplicate).
    A sidecar uploaded alongside it is stored; otherwise one is created from EXIF
    (a duplicate keeps its existing sidecar unless a new one came with it)."""
    sha = hashlib.sha256(data).hexdigest()
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM photos WHERE sha = ?", (sha,)).fetchone()
    if row:
        if sidecar_xml is not None:
            sidecar.write(row, sidecar.parse(sidecar_xml))
        return row["id"]

    originals_dir().mkdir(parents=True, exist_ok=True)
    thumbs_dir().mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or ".jpg"
    path = originals_dir() / f"{sha}{ext}"
    path.write_bytes(data)
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            w, h = img.size
            thumb = img.convert("RGB")
            thumb.thumbnail(THUMB_SIZE)
            thumb.save(thumbs_dir() / f"{sha}.jpg", quality=85)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO photos (sha, filename, ext, uploaded_at, width, height) VALUES (?,?,?,?,?,?)",
            (sha, Path(filename).name, ext, datetime.now(timezone.utc).isoformat(), w, h),
        )
        photo = db.photo(conn, cur.lastrowid)
    sidecar.write(photo, sidecar.parse(sidecar_xml) if sidecar_xml is not None else sidecar.from_exif(path))
    return photo["id"]


def delete(photo_id: int) -> None:
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
        if not p:
            return
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    original_path(p).unlink(missing_ok=True)
    thumb_path(p).unlink(missing_ok=True)
    sidecar.path_for(originals_dir(), p["sha"]).unlink(missing_ok=True)
