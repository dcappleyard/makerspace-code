"""Photo ingest: originals are stored by content hash, so re-uploads are no-ops."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from . import config as cfg
from . import db

THUMB_SIZE = (320, 320)


def originals_dir() -> Path:
    return cfg.DATA_DIR / "originals"


def thumbs_dir() -> Path:
    return cfg.DATA_DIR / "thumbs"


def original_path(photo) -> Path:
    return originals_dir() / f"{photo['sha']}{photo['ext']}"


def thumb_path(photo) -> Path:
    return thumbs_dir() / f"{photo['sha']}.jpg"


def ingest(filename: str, data: bytes) -> int:
    """Store an uploaded file and return its photo id (existing id if a duplicate)."""
    sha = hashlib.sha256(data).hexdigest()
    with db.tx() as conn:
        row = conn.execute("SELECT id FROM photos WHERE sha = ?", (sha,)).fetchone()
        if row:
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
        return cur.lastrowid


def delete(photo_id: int) -> None:
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
        if not p:
            return
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    original_path(p).unlink(missing_ok=True)
    thumb_path(p).unlink(missing_ok=True)
