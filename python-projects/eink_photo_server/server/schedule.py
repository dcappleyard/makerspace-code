"""Daily block schedule: what a frame shows on a pull, and when it should wake next.

Each device has a timeline of blocks. A block starts at a local clock time and
runs until the next block starts, wrapping past midnight. A block is:

  source     where photos come from: a raw source (library, a folder source
             like the photobooth, testcards) or a playlist (playlist:<id>)
  selection  random    any photo but the one showing
             newest    the most recently added
             next      the next in order (each frame keeps its own position)
             specific  one chosen photo
  refresh    every N minutes (ticks aligned to the block's start: 07:00,
             08:00, ...), or hold one photo until the block ends

Devices without blocks get a fallback built from devices.yaml (interval_minutes
+ wake_hours). Protocol-agnostic: callers add the device's wake offset.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from . import config as cfg
from . import db, sources

SELECTIONS = {
    "next": "Next",
    "random": "Random",
    "newest": "Most recent",
    "specific": "Specific photo",
}
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
    key: str                 # stable id: db row id, or "yaml:<n>" for the fallback
    start: time
    source: str              # library | <folder id> | testcards | playlist:<id>
    selection: str           # next | random | newest | specific
    interval: int | None     # minutes between photos; None = hold until the block ends
    photo_id: int | None     # for selection == specific
    from_yaml: bool = False

    @property
    def hold(self) -> bool:
        return not self.interval

    def describe(self, conn) -> str:
        what = SELECTIONS.get(self.selection, self.selection)
        if self.selection == "specific":
            p = db.photo(conn, self.photo_id) if self.photo_id else None
            what = p["filename"] if p else "— (photo missing)"
        else:
            what = f"{what} · {sources.label(conn, self.source)}"
        return what + (" · hold" if self.hold else f" · every {self.interval} min")


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
        return [Block(str(r["id"]), cfg.parse_hhmm(r["start_time"]), r["source"] or "library",
                      r["selection"] or "next", None if r["hold"] else r["interval_minutes"],
                      r["photo_id"]) for r in rows]
    return fallback_blocks(device)


def fallback_blocks(device) -> list[Block]:
    """For a frame with no blocks yet, from devices.yaml: the Library in order
    every interval_minutes during wake_hours, and one random photo held outside them."""
    day = Block("yaml:1", device.wake_start or time(0, 0), "library", "next",
                device.interval_minutes, None, from_yaml=True)
    if device.wake_start and device.wake_end:
        return [day, Block("yaml:2", device.wake_end, "library", "random", None, None, from_yaml=True)]
    return [day]


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
    if not occ.block.hold:
        step = timedelta(minutes=occ.block.interval)
        k = max(1, -(-(local_now + MIN_GAP - occ.start) // step))  # ceil
        target = min(occ.start + k * step, occ.end)
    if target - local_now < MIN_GAP:
        target = local_now + MIN_GAP
    return target.astimezone(timezone.utc)


# --- choosing what to show --------------------------------------------------

def _random_pick(items, exclude: int | None, rng=random) -> int | None:
    ids = [it.photo_id for it in items]
    if not ids:
        return None
    choices = [i for i in ids if i != exclude] or ids
    return rng.choice(choices)


def _next_after(items, cursor):
    """The item after `cursor` (an Item.key), wrapping; the first if not found."""
    if not items:
        return None
    keys = [it.key for it in items]
    return items[(keys.index(cursor) + 1) % len(items)] if cursor in keys else items[0]


def _cursor(conn, device_id: str, source: str):
    row = conn.execute("SELECT last_item FROM source_cursors WHERE device_id = ? AND source = ?",
                       (device_id, source)).fetchone()
    return row["last_item"] if row else None


def _pick(conn, device, b: Block, last_photo_id: int | None) -> tuple[int | None, str]:
    """Apply a block's selection to its source; advances the frame's cursor for 'next'."""
    if b.selection == "specific":
        return (b.photo_id if b.photo_id and db.photo(conn, b.photo_id) else None), "photo missing"
    items = sources.items(conn, b.source)
    if not items:
        return None, "source empty"
    if b.selection == "newest":
        return max(items, key=lambda it: it.photo_id).photo_id, ""
    if b.selection == "random":
        return _random_pick(items, last_photo_id), ""
    item = _next_after(items, _cursor(conn, device.id, b.source))
    conn.execute("INSERT OR REPLACE INTO source_cursors (device_id, source, last_item) VALUES (?, ?, ?)",
                 (device.id, b.source, item.key))
    return item.photo_id, ""


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
    label = f"{b.start:%H:%M} {SELECTIONS.get(b.selection, b.selection)} · {sources.label(conn, b.source)}"

    if b.hold:
        held = st["block_photo_id"]
        if st["block_instance"] == occ.instance and held and db.photo(conn, held):
            return held, f"{label} (holding)"
    pick, why = _pick(conn, device, b, st["last_photo_id"])
    if pick is None:
        return None, f"{label}: {why}"
    conn.execute("UPDATE device_state SET block_instance = ?, block_photo_id = ? WHERE device_id = ?",
                 (occ.instance, pick if b.hold else None, device.id))
    return pick, label


def next_target(conn, device, now: datetime) -> datetime:
    return target_after(get_blocks(conn, device), now)


# --- planning ---------------------------------------------------------------

def plan_day(conn, device, now: datetime, hours: int = 24) -> list[dict]:
    """Simulate the next `hours` of wake targets without touching state.
    Returns [{"at": local datetime, "block": Block, "shows": str}, ...]."""
    blocks = get_blocks(conn, device)
    names = {r["id"]: r["filename"] for r in conn.execute("SELECT id, filename FROM photos")}
    cursors, item_cache = {}, {}
    end = now + timedelta(hours=hours)
    t, out = now, []
    while True:
        t = target_after(blocks, t)
        if t > end:
            break
        occ = current(blocks, t)
        b = occ.block
        src = sources.label(conn, b.source)
        if b.selection == "specific":
            shows = names.get(b.photo_id, "— (photo missing)")
        elif b.selection == "next":
            if b.source not in item_cache:
                item_cache[b.source] = sources.items(conn, b.source)
                cursors[b.source] = _cursor(conn, device.id, b.source)
            item = _next_after(item_cache[b.source], cursors[b.source])
            if item:
                cursors[b.source] = item.key
                shows = f"{names.get(item.photo_id, '?')} ({src})"
            else:
                shows = f"— ({src} is empty)"
        else:
            shows = f"{SELECTIONS[b.selection].lower()} from {src}"
        if b.hold:
            shows += f" until {occ.end:%H:%M}"
        out.append({"at": t.astimezone(cfg.config.tz), "block": b, "shows": shows})
        if len(out) > 500:
            break
    return out
