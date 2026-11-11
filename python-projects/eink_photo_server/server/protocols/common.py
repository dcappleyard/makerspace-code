"""Pull logic shared by every protocol adapter.

An adapter parses its frame's request, calls run_pull(), and shapes the
response. This module owns the rest: picking the photo (schedule blocks),
the next wake (target + wake offset), preparing the image, the pulls table,
the per-frame event log, the /image route and signal handling.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from .. import config as cfg
from .. import db, pipelines, prepare, schedule

log = logging.getLogger(__name__)
router = APIRouter()


def mask(token: str | None) -> str:
    if token is None:
        return "<missing>"
    return f"{token[:4]}…({len(token)} chars)" if len(token) > 4 else f"<{len(token)} chars>"


def device_for_token(token: str | None, protocol: str):
    return next((d for d in cfg.config.devices.values()
                 if d.protocol == protocol and token and d.token == token), None)


def log_unknown(hw_device_id, now, summary, **data):
    """Attribute a failed pull to a device by the hardware id it reported before."""
    if not hw_device_id:
        return
    with db.tx() as conn:
        row = conn.execute("SELECT device_id FROM device_state WHERE hw_device_id = ?", (hw_device_id,)).fetchone()
        if row:
            db.log_event(conn, row["device_id"], "error", summary, now.isoformat(), **data)


def image_url(request: Request, device, photo, battery: int | None = None) -> str:
    base = cfg.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return f"{base}/image/{device.image_secret}/{prepare.image_name(device, photo, battery)}"


@dataclass
class Pull:
    device: object
    pull_id: str
    now: datetime
    reason: str = ""
    photo: object = None
    url: str | None = None
    name: str | None = None          # public image filename
    path: object = None              # prepared file
    target: datetime | None = None
    sent: datetime | None = None     # next wake sent to the frame (target + offset)
    error: str | None = None
    keep: bool = False               # early pull: no new image, re-aimed at the next change
    event: dict = field(default_factory=dict)

    @property
    def next_cron(self) -> str:
        return schedule.iso_z(self.sent)


def run_pull(request: Request, device, now: datetime, *, scheduled_for: datetime | None,
             battery: int | None = None, hw_device_id: str | None = None,
             pull_id: str | None = None) -> Pull:
    """Choose what this frame shows now and when it wakes next; prepare the
    image; record the pull, state and log event. `scheduled_for` is the wake
    time the frame says it was given (for drift and early-wake handling)."""
    p = Pull(device=device, pull_id=pull_id or uuid.uuid4().hex, now=now)
    drift_s = int((now - scheduled_for).total_seconds()) if scheduled_for else None
    with db.tx() as conn:
        st = db.state(conn, device.id)
        ours = bool(scheduled_for and schedule.parse_iso(st["next_cron_sent"]) == scheduled_for)
        conn.execute(
            "UPDATE device_state SET battery = COALESCE(?, battery), last_pull_at = ?, "
            "hw_device_id = COALESCE(?, hw_device_id) WHERE device_id = ?",
            (battery, now.isoformat(), hw_device_id, device.id))
        # This pull's reading (or the last known one) goes on the image it's served.
        known_battery = db.state(conn, device.id)["battery"]
        prev_target = schedule.parse_iso(st["next_target"])
        clock = {}
        if device.adaptive_clock:
            keep_until, at, clock = _adaptive(conn, device, st, now, scheduled_for, ours, prev_target)
            offset = clock["clock_offset_s"]
            if keep_until:
                p.keep, p.target, photo_id = True, keep_until, None
                p.reason = clock.pop("why")
            else:
                photo_id, p.reason = schedule.choose(conn, device, now, at)
                if at != now:
                    p.reason += f", early by {_mins(at - now)} min -> treated as {at.astimezone(cfg.config.tz):%H:%M}"
                p.target = schedule.next_target(conn, device, at)
            # Sent on the frame's clock.
            p.sent = max(p.target, now + schedule.MIN_GAP) + timedelta(seconds=offset)
            p.reason += f" · frame clock {_dur(offset)}" + (f" ({clock['clock_note']})" if clock["clock_note"] else "")
        else:
            # An early scheduled wake counts as its target slot (see schedule.EARLY_CAP).
            at = schedule.effective_time(now, prev_target, ours)
            photo_id, p.reason = schedule.choose(conn, device, now, at)
            if at != now:
                p.reason += f", early by {_mins(at - now)} min -> treated as {at.astimezone(cfg.config.tz):%H:%M}"
            p.target = schedule.next_target(conn, device, at)
            offset = st["wake_offset_s"] or 0
            p.sent = max(p.target + timedelta(seconds=offset), now + schedule.MIN_GAP)
        conn.execute("UPDATE device_state SET next_target = ?, next_cron_sent = ? WHERE device_id = ?",
                     (p.target.isoformat(), p.next_cron, device.id))
        p.photo = db.photo(conn, photo_id) if photo_id else None
    p.event = dict(pull_id=p.pull_id, cron_time=schedule.iso_z(scheduled_for) if scheduled_for else None,
                   drift_s=drift_s, scheduled_by_server=ours, battery=battery, reason=p.reason,
                   effective_at=schedule.iso_z(at), next_target=schedule.iso_z(p.target),
                   next_cron_sent=p.next_cron, offset_s=offset, **clock)

    if not p.photo:
        what = "keep current image" if p.keep else "nothing to show"
        log.info("pull %s: %s battery=%s -> %s (%s), next %s", device.id, p.pull_id, battery, what, p.reason, p.next_cron)
        with db.tx() as conn:
            if not p.keep:   # an early pull isn't a pull to retry or confirm
                conn.execute("INSERT OR REPLACE INTO pulls (pull_id, device_id, at, battery) VALUES (?,?,?,?)",
                             (p.pull_id, device.id, now.isoformat(), battery))
            db.log_event(conn, device.id, "pull", f"{what} ({p.reason})", now.isoformat(), **p.event)
        return p

    try:
        p.path = prepare.get_prepared(device, p.photo, known_battery)
    except Exception as e:
        log.exception("failed to prepare photo %s for %s", p.photo["id"], device.id)
        p.error = f"failed to prepare #{p.photo['id']} {p.photo['filename']}: {e}"
        with db.tx() as conn:
            db.log_event(conn, device.id, "error", p.error, now.isoformat(), **p.event)
        return p

    p.name = prepare.image_name(device, p.photo, known_battery)
    p.url = image_url(request, device, p.photo, known_battery)
    with db.tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pulls (pull_id, device_id, photo_id, image_url, at, battery) VALUES (?,?,?,?,?,?)",
            (p.pull_id, device.id, p.photo["id"], p.url, now.isoformat(), battery))
        conn.execute("UPDATE device_state SET last_photo_id = ?, last_image_url = ? WHERE device_id = ?",
                     (p.photo["id"], p.url, device.id))
        db.log_event(conn, device.id, "pull", f"#{p.photo['id']} {p.photo['filename']} ({p.reason})",
                     now.isoformat(), photo_id=p.photo["id"], **p.event)
    log.info("pull %s: %s battery=%s -> photo %s (%s), next %s",
             device.id, p.pull_id, battery, p.photo["id"], p.reason, p.next_cron)
    return p


def _mins(td: timedelta) -> int:
    return int(td.total_seconds() // 60)


def _dur(seconds: int) -> str:
    s = abs(int(seconds))
    sign = "-" if seconds < 0 else "+"
    return f"{sign}{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{sign}{s // 60}m{s % 60:02d}s"


def _adaptive(conn, device, st, now, scheduled_for, ours, prev_target):
    """Adaptive-clock part of a pull: update the learned frame-clock offset and
    decide between keeping the current image (early) and a normal pull.
    Returns (keep-until time or None, effective time, clock event fields)."""
    reading = int((scheduled_for - now).total_seconds()) if scheduled_for else None
    last_pull = schedule.parse_iso(st["last_pull_at"])
    offset, note = schedule.learn_clock_offset(st["clock_offset_s"], reading, ours,
                                               now - last_pull if last_pull else None)
    if offset is not None and reading is not None and offset == reading:
        conn.execute("UPDATE device_state SET clock_offset_s = ?, clock_offset_at = ? WHERE device_id = ?",
                     (offset, now.isoformat(), device.id))
    if offset is None:
        note = "unknown -- use frame_tool's Pull now to teach it"
    clock = {"clock_offset_s": offset or 0, "clock_reading_s": reading, "clock_note": note}

    # The change this pull is heading for: the one we last aimed at (already due
    # if it has passed), or sooner if the schedule was edited since.
    upcoming = schedule.next_target(conn, device, now)
    if prev_target:
        upcoming = min(upcoming, prev_target)
    showing = st["last_photo_id"] and db.photo(conn, st["last_photo_id"])
    # Only wakes we scheduled are held back; one armed elsewhere (frame_tool's
    # Pull now, the app) is someone asking for an image now.
    if (ours and upcoming - now > schedule.EARLY_WINDOW and showing and not st["queued_photo_id"]
            and not st["paused"] and not schedule.pending_retry(conn, device, now)):
        clock["why"] = (f"early by {_mins(upcoming - now)} min -> keeping the current image until "
                        f"{upcoming.astimezone(cfg.config.tz):%H:%M}")
        return upcoming, now, clock
    at = upcoming if timedelta(0) < upcoming - now <= schedule.EARLY_WINDOW else now
    return None, at, clock


def record_signal(pull_id: str, device, success: bool, summary: str | None = None) -> str | None:
    """Mark a pull as displayed (or failed). Returns the device id, or None if
    the pull_id is unknown. `device` narrows the lookup when the frame is known."""
    now = schedule.utc_now().isoformat()
    with db.tx() as conn:
        sql = ("SELECT * FROM pulls WHERE pull_id = ?" + (" AND device_id = ?" if device else "")
               + " ORDER BY at DESC, rowid DESC LIMIT 1")
        row = conn.execute(sql, (pull_id, device.id) if device else (pull_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE pulls SET signaled_at = ?, success = ? WHERE device_id = ? AND pull_id = ?",
                     (now, int(success), row["device_id"], pull_id))
        if success:
            conn.execute("UPDATE device_state SET last_success_at = ? WHERE device_id = ?", (now, row["device_id"]))
        db.log_event(conn, row["device_id"], "signal",
                     summary or ("displayed" if success else "frame reported failure"),
                     now, pull_id=pull_id, success=success)
    return row["device_id"]


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


_NAME = re.compile(r"^(\d+)-([0-9a-f]+)(_[A-Za-z]\.\w+)$")


@router.get("/image/{secret}/{name}")
def image(secret: str, name: str):
    """Prepared images for any frame. The secret in the path stands in for the
    token, since frames may not send their header on the download."""
    device = cfg.config.by_secret(secret)
    m = _NAME.match(name)
    if not device or not m:
        return Response(status_code=404)
    photo_id, key, suffix = int(m[1]), m[2], m[3]
    pipe = pipelines.get(device.pipeline)
    with db.tx() as conn:
        photo = db.photo(conn, photo_id)
        battery = db.state(conn, device.id)["battery"]
    if not photo or suffix != pipe.file_suffix:
        return Response(status_code=404)
    path = prepare.cached_path(device, key)
    if not path.exists():
        # Cache was cleared: rebuild, but only if the URL still names the current
        # version (a stale URL -- tuning, caption or battery changed since -- 404s).
        if prepare.cache_key(device, photo, battery) != key:
            return Response(status_code=404)
        path = prepare.get_prepared(device, photo, battery)
    size = path.stat().st_size
    log.info("image %s -> %s (%d bytes)", device.id, name, size)
    with db.tx() as conn:
        db.log_event(conn, device.id, "image", f"downloaded {name} ({size // 1024} KB)",
                     schedule.utc_now().isoformat(), photo_id=photo_id, bytes=size)
    return FileResponse(path, media_type=pipe.content_type)
