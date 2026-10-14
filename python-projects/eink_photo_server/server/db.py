"""SQLite storage for photos, playlists, per-device runtime state, and pull history."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from . import config as cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY,
    sha         TEXT UNIQUE NOT NULL,
    filename    TEXT NOT NULL,
    ext         TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER,
    focal_x     REAL NOT NULL DEFAULT 0.5,
    focal_y     REAL NOT NULL DEFAULT 0.5,
    params_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS playlist_items (
    id           INTEGER PRIMARY KEY,
    device_id    TEXT NOT NULL,
    photo_id     INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    window_start TEXT,
    window_end   TEXT
);
CREATE TABLE IF NOT EXISTS device_state (
    device_id       TEXT PRIMARY KEY,
    paused          INTEGER NOT NULL DEFAULT 0,
    cursor          INTEGER NOT NULL DEFAULT -1,
    last_photo_id   INTEGER,
    last_image_url  TEXT,
    battery         INTEGER,
    last_pull_at    TEXT,
    last_success_at TEXT,
    hw_device_id    TEXT
);
CREATE TABLE IF NOT EXISTS pulls (
    pull_id     TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    photo_id    INTEGER,
    image_url   TEXT,
    at          TEXT NOT NULL,
    battery     INTEGER,
    signaled_at TEXT,
    success     INTEGER,
    PRIMARY KEY (device_id, pull_id)
);
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def init() -> None:
    global _conn
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(cfg.DATA_DIR / "db.sqlite", check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.executescript(SCHEMA)
    _conn.commit()


@contextmanager
def tx():
    """Serialized transaction. Traffic is a handful of frames + one UI user, so a
    single connection behind a lock is plenty."""
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


def state(conn, device_id: str) -> sqlite3.Row:
    conn.execute("INSERT OR IGNORE INTO device_state (device_id) VALUES (?)", (device_id,))
    return conn.execute("SELECT * FROM device_state WHERE device_id = ?", (device_id,)).fetchone()


def playlist(conn, device_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM playlist_items WHERE device_id = ? ORDER BY position, id", (device_id,)
    ).fetchall()


def photo(conn, photo_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
