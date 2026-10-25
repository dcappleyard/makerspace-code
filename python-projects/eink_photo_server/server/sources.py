"""Photo sources: where photos come from, and what a schedule block can draw on.

Raw sources hold photos (each photo belongs to exactly one):
  library     uploaded through the web UI (content-addressed in originals/)
  testcards   tuning cards saved from the Test card page
  <folder id> a folder under DATA_DIR from devices.yaml `sources:`, e.g. the
              photobooth repository -- filled by HTTP upload and/or dropped files
Curated sources:
  playlist:<id>  an ordered selection of photos from any raw source

A schedule block names a source key (one of the above) and a selection.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config as cfg
from . import db, photos

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
BUILTIN = {"library": "Library", "testcards": "Test cards"}


@dataclass(frozen=True)
class Item:
    key: int        # playlist_items.id for playlists, photos.id for raw sources
    photo_id: int


def raw_sources() -> list[tuple[str, str]]:
    """(key, name) for every raw source, in tab order."""
    return ([("library", "Library")] + [(s.id, s.name) for s in cfg.config.sources.values()]
            + [("testcards", "Test cards")])


def is_raw(key: str) -> bool:
    return key in BUILTIN or key in cfg.config.sources


def playlist_id(key: str) -> int | None:
    m = re.fullmatch(r"playlist:(\d+)", key or "")
    return int(m[1]) if m else None


def label(conn, key: str) -> str:
    pid = playlist_id(key)
    if pid is not None:
        pl = db.playlist(conn, pid)
        return f"Playlist: {pl['name']}" if pl else "Playlist (deleted)"
    if key in BUILTIN:
        return BUILTIN[key]
    src = cfg.config.sources.get(key)
    return src.name if src else f"{key} (not configured)"


def choices(conn) -> list[tuple[str, str]]:
    """All sources a block can use: raw sources, then playlists."""
    pls = conn.execute("SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE, id").fetchall()
    return raw_sources() + [(f"playlist:{p['id']}", f"Playlist: {p['name']}") for p in pls]


def items(conn, key: str) -> list[Item]:
    """A source's photos in its natural order: playlist order, or arrival order."""
    pid = playlist_id(key)
    if pid is not None:
        return [Item(r["id"], r["photo_id"]) for r in db.playlist_items(conn, pid)]
    rows = conn.execute("SELECT id FROM photos WHERE source = ? ORDER BY id", (key,)).fetchall()
    return [Item(r["id"], r["id"]) for r in rows]


# --- folder sources ----------------------------------------------------------

# Photobooth names: 2026-10-24_19-02-11_A.jpg (date, time, shot letter).
_BOOTH_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})_\d{2}-\d{2}-\d{2}(?:_([A-Za-z]))?")


def seed_from_name(src: cfg.FolderSource, name: str) -> dict:
    seed = {"tags": list(src.tags)}
    m = _BOOTH_NAME.search(name)
    if m:
        seed["date"] = f"{m[1]}-{m[2]}-{m[3]}"
        if m[4]:
            seed["tags"].append(f"shot-{m[4].lower()}")
    return seed


_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(name: str) -> str | None:
    name = _SAFE.sub("_", Path(name or "").name).lstrip(".")[:80]
    return name if Path(name).suffix.lower() in IMAGE_EXTS else None


def store_upload(src: cfg.FolderSource, name: str, data: bytes) -> tuple[int, str, str]:
    """Write an uploaded image into the folder and ingest it.
    Returns (photo id, "stored" | "duplicate", stored filename)."""
    import hashlib
    sha = hashlib.sha256(data).hexdigest()
    with db.tx() as conn:
        row = conn.execute("SELECT id, filename FROM photos WHERE sha = ?", (sha,)).fetchone()
    if row:
        return row["id"], "duplicate", row["filename"]
    src.path.mkdir(parents=True, exist_ok=True)
    path = src.path / name
    n = 2
    while path.exists():   # same name, different content: keep both
        path = src.path / f"{Path(name).stem}-{n}{Path(name).suffix}"
        n += 1
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    with _scan_lock:
        pid, status = photos.ingest_in_place(src.id, path, seed_from_name(src, path.name))
    return pid, status, path.name


_scan_lock = threading.Lock()
last_scan: dict[str, float] = {}
_skipped: dict[str, set] = {}   # files seen to be duplicates of other photos


def scan(src: cfg.FolderSource) -> dict:
    """Bring the database in line with the folder: ingest new image files,
    drop photos whose file has gone. Returns counts."""
    added = removed = 0
    with _scan_lock:
        src.path.mkdir(parents=True, exist_ok=True)
        with db.tx() as conn:
            known = {r["rel_path"]: r["id"] for r in conn.execute(
                "SELECT id, rel_path FROM photos WHERE source = ? AND rel_path IS NOT NULL", (src.id,))}
        on_disk = {}
        for f in sorted(src.path.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.name.startswith("."):
                on_disk[str(f.relative_to(cfg.DATA_DIR))] = f
        skipped = _skipped.setdefault(src.id, set())
        for rel, f in on_disk.items():
            if rel in known or rel in skipped:
                continue
            try:
                _, status = photos.ingest_in_place(src.id, f, seed_from_name(src, f.name))
            except Exception as e:
                log.warning("source %s: can't ingest %s: %s", src.id, f.name, e)
                skipped.add(rel)
                continue
            if status == "duplicate":
                skipped.add(rel)
            else:
                added += 1
        for rel, pid in known.items():
            if rel not in on_disk:
                with db.tx() as conn:
                    conn.execute("DELETE FROM photos WHERE id = ?", (pid,))
                removed += 1
        last_scan[src.id] = time.time()
    if added or removed:
        log.info("source %s: +%d, -%d", src.id, added, removed)
    return {"added": added, "removed": removed}


def scan_all() -> None:
    for src in list(cfg.config.sources.values()):
        try:
            scan(src)
        except Exception:
            log.exception("scan of source %s failed", src.id)


def start_scanner(interval_s: int) -> None:
    """Rescan every folder source in the background (picks up dropped files)."""
    if interval_s <= 0:
        return

    def loop():
        while True:
            time.sleep(interval_s)
            scan_all()

    threading.Thread(target=loop, name="source-scanner", daemon=True).start()
