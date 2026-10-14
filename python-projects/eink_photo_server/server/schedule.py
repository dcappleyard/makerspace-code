"""Playlist selection and next-wake computation. Protocol-agnostic.

Timing is deliberately loose: a frame wakes on its own timer and we answer with
whatever is appropriate *now*, plus a hint for when it should wake next.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from . import config as cfg
from . import db

# Frames have been observed waking up to ~30 min before the requested time, so
# a window counts as active from this long before its start.
WINDOW_LEAD = timedelta(minutes=30)
# A pull this soon after an unconfirmed one is treated as a retry of it.
RETRY_GUARD = timedelta(minutes=5)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hhmm(s: str | None) -> time | None:
    return cfg.parse_hhmm(s) if s else None


def _in_span(t: time, start: time, end: time) -> bool:
    """start <= t < end, wrapping past midnight when start > end."""
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def window_active(item, local: datetime) -> bool:
    start, end = _hhmm(item["window_start"]), _hhmm(item["window_end"])
    if not (start and end):
        return False
    return _in_span(local.time(), start, end) or _in_span((local + WINDOW_LEAD).time(), start, end)


def _next_occurrence(t: time, after_local: datetime) -> datetime:
    cand = after_local.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    return cand if cand > after_local else cand + timedelta(days=1)


def choose(conn, device, now: datetime) -> tuple[int | None, str]:
    """Return (photo_id or None, reason) and advance the cursor if appropriate."""
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

    items = db.playlist(conn, device.id)
    if not items:
        return None, "playlist empty"

    local = now.astimezone(cfg.config.tz)
    windowed = [it for it in items if it["window_start"] and it["window_end"]]
    active = [it for it in windowed if window_active(it, local)]
    if active:
        candidates, reason = active, "time window"
    else:
        candidates = [it for it in items if not (it["window_start"] and it["window_end"])]
        reason = "next in playlist"
        if not candidates:
            return None, "only windowed items, none active"

    # Cursor is the playlist_item id last shown; pick the first candidate after
    # it in playlist order, wrapping around.
    order = {it["id"]: i for i, it in enumerate(items)}
    cur_pos = order.get(st["cursor"], -1)
    after = [it for it in candidates if order[it["id"]] > cur_pos]
    pick = (after or candidates)[0]
    conn.execute("UPDATE device_state SET cursor = ? WHERE device_id = ?", (pick["id"], device.id))
    return pick["photo_id"], reason


def next_wake(conn, device, now: datetime) -> datetime:
    tz = cfg.config.tz
    local_now = now.astimezone(tz)
    nxt = local_now + timedelta(minutes=device.interval_minutes)

    if device.wake_start and device.wake_end and not _in_span(nxt.time(), device.wake_start, device.wake_end):
        nxt = _next_occurrence(device.wake_start, local_now)

    # Wake for the start of any time window that opens before then.
    for it in db.playlist(conn, device.id):
        start = _hhmm(it["window_start"])
        if start and it["window_end"]:
            occ = _next_occurrence(start, local_now + WINDOW_LEAD)
            if occ < nxt:
                nxt = occ
    return nxt.astimezone(timezone.utc)
