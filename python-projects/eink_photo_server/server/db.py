"""SQLite storage for photos, playlists, per-device runtime state, and pull history."""
from __future__ import annotations

import json
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
    hw_device_id    TEXT,
    queued_photo_id INTEGER,
    wake_offset_s   INTEGER NOT NULL DEFAULT 0,
    block_instance  TEXT,
    block_photo_id  INTEGER,
    next_target     TEXT,
    next_cron_sent  TEXT
);
CREATE TABLE IF NOT EXISTS schedule_blocks (
    id               INTEGER PRIMARY KEY,
    device_id        TEXT NOT NULL,
    start_time       TEXT NOT NULL,
    kind             TEXT NOT NULL,
    interval_minutes INTEGER,
    photo_id         INTEGER REFERENCES photos(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    at        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    summary   TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_device ON events (device_id, id);
CREATE TABLE IF NOT EXISTS photo_tags (
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (photo_id, tag)
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

# Columns added after a table was first created: (table, column, decl). CREATE
# TABLE IF NOT EXISTS won't add them to an existing db, so init() does.
MIGRATIONS = [
    ("device_state", "hw_device_id", "TEXT"),
    ("device_state", "queued_photo_id", "INTEGER"),
    ("device_state", "wake_offset_s", "INTEGER NOT NULL DEFAULT 0"),
    ("device_state", "block_instance", "TEXT"),
    ("device_state", "block_photo_id", "INTEGER"),
    ("device_state", "next_target", "TEXT"),
    ("device_state", "next_cron_sent", "TEXT"),
]
EVENTS_KEEP = 5000  # per device

_lock = threading.RLock()  # re-entrant: a sidecar write may run inside a tx
_conn: sqlite3.Connection | None = None


def init() -> None:
    global _conn
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(cfg.DATA_DIR / "db.sqlite", check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.executescript(SCHEMA)
    for table, col, decl in MIGRATIONS:
        have = {r["name"] for r in _conn.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
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


def log_event(conn, device_id: str, kind: str, summary: str, at: str, **data) -> None:
    """Append to a device's log (shown on its tab), keeping the newest EVENTS_KEEP."""
    conn.execute("INSERT INTO events (device_id, at, kind, summary, data_json) VALUES (?,?,?,?,?)",
                 (device_id, at, kind, summary, json.dumps(data, default=str)))
    conn.execute(
        "DELETE FROM events WHERE device_id = ? AND id <= "
        "(SELECT id FROM events WHERE device_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
        (device_id, device_id, EVENTS_KEEP))


def photo(conn, photo_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
