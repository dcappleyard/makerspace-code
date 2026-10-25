"""SQLite storage for photos, sources, playlists, per-device runtime state, and pull history."""
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
CREATE TABLE IF NOT EXISTS playlists (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- "next" position per frame per source (source = library | <folder id> |
-- testcards | playlist:<id>); last_item = playlist_items.id for playlists,
-- photos.id for raw sources.
CREATE TABLE IF NOT EXISTS source_cursors (
    device_id TEXT NOT NULL,
    source    TEXT NOT NULL,
    last_item INTEGER,
    PRIMARY KEY (device_id, source)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
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
    ("photos", "source", "TEXT NOT NULL DEFAULT 'library'"),
    ("photos", "rel_path", "TEXT"),          # NULL = originals/<sha><ext>; else under DATA_DIR
    ("playlist_items", "playlist_id", "INTEGER"),
    ("schedule_blocks", "source", "TEXT"),
    ("schedule_blocks", "selection", "TEXT"),
    ("schedule_blocks", "hold", "INTEGER NOT NULL DEFAULT 0"),
]
SCHEMA_VERSION = "2"
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
    row = _conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
    if not row or row["value"] != SCHEMA_VERSION:
        _migrate_v2(_conn)
        _conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema', ?)", (SCHEMA_VERSION,))
    _conn.commit()


# Old block kinds -> (selection, hold, needs the frame's playlist)
_V1_KINDS = {"sleep": ("random", True), "image": ("specific", True),
             "random": ("random", False), "playlist": ("next", False)}


def _migrate_v2(conn) -> None:
    """v1 -> v2: playlists move out of frames into their own table, and schedule
    blocks become source + selection (+ hold). Behaviour is preserved: each
    frame's old playlist becomes a playlist named after the frame, and blocks
    (including the devices.yaml fallback, which used that playlist) point at it."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    names = {d.id: d.name for d in cfg.config.devices.values()}
    pl_for: dict[str, int] = {}

    def playlist_of(device_id: str) -> int:
        if device_id not in pl_for:
            cur = conn.execute("INSERT INTO playlists (name, created_at) VALUES (?, ?)",
                               (names.get(device_id, device_id), now))
            pl_for[device_id] = cur.lastrowid
        return pl_for[device_id]

    for r in conn.execute("SELECT DISTINCT device_id FROM playlist_items WHERE playlist_id IS NULL "
                          "AND device_id != ''").fetchall():
        conn.execute("UPDATE playlist_items SET playlist_id = ? WHERE device_id = ? AND playlist_id IS NULL",
                     (playlist_of(r["device_id"]), r["device_id"]))

    for b in conn.execute("SELECT * FROM schedule_blocks WHERE source IS NULL").fetchall():
        selection, hold = _V1_KINDS.get(b["kind"], ("next", False))
        if b["kind"] == "sleep" and b["photo_id"]:
            selection = "specific"
        source = "library" if selection == "specific" else f"playlist:{playlist_of(b['device_id'])}"
        conn.execute("UPDATE schedule_blocks SET source = ?, selection = ?, hold = ?, "
                     "interval_minutes = CASE WHEN ? THEN NULL ELSE interval_minutes END WHERE id = ?",
                     (source, selection, int(hold), int(hold), b["id"]))

    # Frames still on the devices.yaml fallback played their own playlist; make
    # that explicit so they keep doing so (the new fallback plays the Library).
    for device_id, pl in list(pl_for.items()):
        d = next((d for d in cfg.config.devices.values() if d.id == device_id), None)
        if not d or conn.execute("SELECT 1 FROM schedule_blocks WHERE device_id = ?", (device_id,)).fetchone():
            continue
        start = f"{d.wake_start:%H:%M}" if d.wake_start else "00:00"
        conn.execute("INSERT INTO schedule_blocks (device_id, start_time, kind, interval_minutes, photo_id, "
                     "source, selection, hold) VALUES (?, ?, 'next', ?, NULL, ?, 'next', 0)",
                     (device_id, start, d.interval_minutes, f"playlist:{pl}"))
        if d.wake_start and d.wake_end:
            conn.execute("INSERT INTO schedule_blocks (device_id, start_time, kind, interval_minutes, photo_id, "
                         "source, selection, hold) VALUES (?, ?, 'random', NULL, NULL, ?, 'random', 1)",
                         (device_id, f"{d.wake_end:%H:%M}", f"playlist:{pl}"))

    # Each frame's playlist position becomes its cursor on that playlist.
    for st in conn.execute("SELECT device_id, cursor FROM device_state").fetchall():
        if st["device_id"] in pl_for and st["cursor"] not in (None, -1):
            conn.execute("INSERT OR REPLACE INTO source_cursors (device_id, source, last_item) VALUES (?, ?, ?)",
                         (st["device_id"], f"playlist:{pl_for[st['device_id']]}", st["cursor"]))


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


def playlist_items(conn, playlist_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY position, id", (playlist_id,)
    ).fetchall()


def playlist(conn, playlist_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()


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
