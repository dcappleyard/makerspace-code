"""Daily block schedule: what a frame shows on a pull, and when it should wake next.

Each device has a timeline of blocks. A block starts at a local clock time and
runs until the next block starts, wrapping past midnight:

  sleep     show one photo (fixed, or random from the playlist) until the block ends
  image     show one fixed photo until the block ends
  random    a random playlist photo every `interval` minutes
  playlist  the next playlist photo every `interval` minutes

Interval ticks are aligned to the block's start (07:00, 08:00, ...). Devices
without blocks get a fallback built from devices.yaml (interval_minutes +
wake_hours). Protocol-agnostic: callers add the device's wake offset.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from . import config as cfg
from . import db

KINDS = {
    "sleep": "Sleep",
    "image": "Load image",
    "random": "Random image",
    "playlist": "Play playlist",
}
INTERVAL_KINDS = ("random", "playlist")
# A pull this close before a block starts counts as belonging to that block
# (frames wake a little early).
BOUNDARY_GRACE = timedelta(minutes=5)
# Never ask a frame to wake sooner than this.
MIN_GAP = timedelta(minutes=2)
# A scheduled pull up to this long before its target is treated as happening at
# the target, so an early wake gets that slot's photo and doesn't re-wake for it.
EARLY_CAP = timedelta(minutes=60)
# A pull this soon after an unconfirmed one is treated as a retry of it.
RETRY_GUARD = timedelta(minutes=5)


@dataclass(frozen=True)
class Block:
    key: str                 # stable id: db row id, or "yaml:<kind>" for the fallback
    start: time
    kind: str
    interval: int | None     # minutes, for random/playlist
    photo_id: int | None     # image: required; sleep: None = random from playlist
    from_yaml: bool = False


@dataclass(frozen=True)
class Occurrence:
    block: Block
    start: datetime          # local, tz-aware
    end: datetime

    @property
    def instance(self) -> str:
        return f"{self.block.key}@{self.start.isoformat()}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- blocks -----------------------------------------------------------------

def get_blocks(conn, device) -> list[Block]:
    rows = conn.execute("SELECT * FROM schedule_blocks WHERE device_id = ? ORDER BY start_time, id",
                        (device.id,)).fetchall()
    if rows:
        return [Block(str(r["id"]), cfg.parse_hhmm(r["start_time"]), r["kind"],
                      r["interval_minutes"], r["photo_id"]) for r in rows]
    return fallback_blocks(device)


def fallback_blocks(device) -> list[Block]:
    """The old behaviour, from devices.yaml: playlist every interval_minutes
    during wake_hours, sleep (random photo) outside them."""
    play = Block("yaml:playlist", device.wake_start or time(0, 0), "playlist",
                 device.interval_minutes, None, from_yaml=True)
    if device.wake_start and device.wake_end:
        return [play, Block("yaml:sleep", device.wake_end, "sleep", None, None, from_yaml=True)]
    return [play]


def occurrence_at(blocks: list[Block], local: datetime) -> Occurrence:
    """The block occurrence containing local time `local`."""
    def latest_start(b):
        s = local.replace(hour=b.start.hour, minute=b.start.minute, second=0, microsecond=0)
        return s if s <= local else s - timedelta(days=1)

    block, start = max(((b, latest_start(b)) for b in blocks), key=lambda p: p[1])
    ends = []
    for b in blocks:
        e = start.replace(hour=b.start.hour, minute=b.start.minute)
        ends.append(e if e > start else e + timedelta(days=1))
    return Occurrence(block, start, min(ends))


def current(blocks, now: datetime) -> Occurrence:
    """Occurrence for a pull at `now`, counting a pull just before a block
    start as part of that block."""
    return occurrence_at(blocks, now.astimezone(cfg.config.tz) + BOUNDARY_GRACE)


def target_after(blocks, now: datetime) -> datetime:
    """Next wake target (UTC) for a pull at `now`, before any wake offset."""
    occ = current(blocks, now)
    local_now = now.astimezone(cfg.config.tz)
    target = occ.end
    if occ.block.kind in INTERVAL_KINDS and occ.block.interval:
        step = timedelta(minutes=occ.block.interval)
        k = max(1, -(-(local_now + MIN_GAP - occ.start) // step))  # ceil
        target = min(occ.start + k * step, occ.end)
    if target - local_now < MIN_GAP:
        target = local_now + MIN_GAP
    return target.astimezone(timezone.utc)


# --- choosing what to show --------------------------------------------------

def _random_pick(items, exclude: int | None, rng=random) -> int | None:
    ids = [it["photo_id"] for it in items]
    if not ids:
        return None
    choices = [i for i in ids if i != exclude] or ids
    return rng.choice(choices)


def _next_in_playlist(items, cursor) -> tuple[object, int] | None:
    """(item, index) after `cursor` (a playlist_item id), wrapping."""
    if not items:
        return None
    ids = [it["id"] for it in items]
    i = ids.index(cursor) + 1 if cursor in ids else 0
    i %= len(items)
    return items[i], i


def effective_time(now: datetime, prev_target: datetime | None, scheduled: bool) -> datetime:
    """The time a pull counts as. A scheduled wake (the frame reported the
    cron_time we sent) arriving shortly before its target counts as the target."""
    if scheduled and prev_target and timedelta(0) < prev_target - now <= EARLY_CAP:
        return prev_target
    return now


def choose(conn, device, now: datetime, at: datetime | None = None) -> tuple[int | None, str]:
    """Return (photo_id or None, reason) and update cursor/block state.
    `now` is the real time (retry guard); `at` the effective time for the schedule."""
    at = at or now
    st = db.state(conn, device.id)
    queued = st["queued_photo_id"]
    if queued and db.photo(conn, queued):
        # One-shot "show next" override; wins over pause and leaves the cursor alone.
        conn.execute("UPDATE device_state SET queued_photo_id = NULL WHERE device_id = ?", (device.id,))
        return queued, "queued"
    if st["paused"]:
        return st["last_photo_id"], "paused"

    last = conn.execute(
        "SELECT * FROM pulls WHERE device_id = ? ORDER BY at DESC, rowid DESC LIMIT 1", (device.id,)
    ).fetchone()
    if (last and last["photo_id"] and not last["signaled_at"]
            and now - datetime.fromisoformat(last["at"]) < RETRY_GUARD
            and db.photo(conn, last["photo_id"])):
        return last["photo_id"], "retry of unconfirmed pull"

    occ = current(get_blocks(conn, device), at)
    b = occ.block
    label = f"{KINDS[b.kind]} {b.start:%H:%M}"
    items = db.playlist(conn, device.id)

    if b.kind in ("sleep", "image"):
        held = st["block_photo_id"]
        if st["block_instance"] == occ.instance and held and db.photo(conn, held):
            return held, f"{label} (holding)"
        if b.photo_id:
            pick = b.photo_id if db.photo(conn, b.photo_id) else None
        elif b.kind == "sleep":
            pick = _random_pick(items, st["last_photo_id"])
        else:
            pick = None
        if pick is None:
            return None, f"{label}: no photo"
        conn.execute("UPDATE device_state SET block_instance = ?, block_photo_id = ? WHERE device_id = ?",
                     (occ.instance, pick, device.id))
        return pick, label

    if not items:
        return None, f"{label}: playlist empty"
    conn.execute("UPDATE device_state SET block_instance = ?, block_photo_id = NULL WHERE device_id = ?",
                 (occ.instance, device.id))
    if b.kind == "random":
        return _random_pick(items, st["last_photo_id"]), label
    item, _ = _next_in_playlist(items, st["cursor"])
    conn.execute("UPDATE device_state SET cursor = ? WHERE device_id = ?", (item["id"], device.id))
    return item["photo_id"], label


def next_target(conn, device, now: datetime) -> datetime:
    return target_after(get_blocks(conn, device), now)


# --- planning ---------------------------------------------------------------

def plan_day(conn, device, now: datetime, hours: int = 24) -> list[dict]:
    """Simulate the next `hours` of wake targets without touching state.
    Returns [{"at": local datetime, "block": Block, "shows": str}, ...]."""
    blocks = get_blocks(conn, device)
    items = db.playlist(conn, device.id)
    st = db.state(conn, device.id)
    names = {r["id"]: r["filename"] for r in conn.execute("SELECT id, filename FROM photos")}
    cursor = st["cursor"]
    end = now + timedelta(hours=hours)
    t, out = now, []
    while True:
        t = target_after(blocks, t)
        if t > end:
            break
        occ = current(blocks, t)
        b = occ.block
        if b.kind == "playlist":
            nxt = _next_in_playlist(items, cursor)
            if nxt:
                cursor = nxt[0]["id"]
                shows = names.get(nxt[0]["photo_id"], "?")
            else:
                shows = "— (playlist empty)"
        elif b.kind == "random":
            shows = "random from playlist"
        elif b.photo_id:
            shows = names.get(b.photo_id, "— (photo missing)")
        else:
            shows = "random from playlist"
        if b.kind in ("sleep", "image"):
            shows += f" until {occ.end:%H:%M}"
        out.append({"at": t.astimezone(cfg.config.tz), "block": b, "shows": shows})
        if len(out) > 500:
            break
    return out
