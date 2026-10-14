"""Bloomin8 "Schedule Pull" protocol adapter.

Frame -> GET /eink_pull   (X-Access-Token header; device_id, pull_id, cron_time, battery query)
Frame -> GET {image_url}  (may not send the header -- hence the secret in the path)
Frame -> GET /eink_signal (pull_id, success) -- optional confirmation

Response bodies follow the reference implementations (Lukafin/bloomin8-pull-server,
fwmone/bloomin8_pull): HTTP is always 200 and the real status is in the JSON.
"""
from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .. import config as cfg
from .. import db, pipelines, prepare, schedule

log = logging.getLogger(__name__)
router = APIRouter()
PROTOCOL = "bloomin8"


def _body(status: int, message: str, **extra) -> JSONResponse:
    body = {"status": status, "message": message, **extra}
    if status >= 400:
        body["type"] = "ERROR"
    return JSONResponse(body, headers={"X-Server-Timestamp": schedule.iso_z(schedule.utc_now())})


def _device_for_token(token: str):
    return next((d for d in cfg.config.devices.values()
                 if d.protocol == PROTOCOL and token and d.token == token), None)


def image_url(request: Request, device, photo) -> str:
    base = cfg.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return f"{base}/image/{device.image_secret}/{prepare.image_name(device, photo)}"


@router.get("/eink_pull")
def eink_pull(request: Request):
    q = request.query_params
    # Devices are identified by their token; the frame's own device_id is recorded
    # for reference only, so it doesn't need to be known ahead of time.
    device = _device_for_token(request.headers.get("X-Access-Token", ""))
    if not device:
        log.warning("eink_pull with bad token from %s (device_id=%s)", request.client.host, q.get("device_id"))
        return _body(401, "Unauthorized")

    now = schedule.utc_now()
    pull_id = q.get("pull_id") or uuid.uuid4().hex
    try:
        battery = int(q.get("battery")) if q.get("battery") is not None else None
    except ValueError:
        battery = None

    with db.tx() as conn:
        db.state(conn, device.id)
        conn.execute(
            "UPDATE device_state SET battery = COALESCE(?, battery), last_pull_at = ?, hw_device_id = COALESCE(?, hw_device_id) WHERE device_id = ?",
            (battery, now.isoformat(), q.get("device_id"), device.id),
        )
        photo_id, reason = schedule.choose(conn, device, now)
        next_cron = schedule.iso_z(schedule.next_wake(conn, device, now))
        photo = db.photo(conn, photo_id) if photo_id else None

    if not photo:
        log.info("pull %s: %s battery=%s -> 204 (%s), next %s", device.id, pull_id, battery, reason, next_cron)
        with db.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO pulls (pull_id, device_id, at, battery) VALUES (?,?,?,?)",
                         (pull_id, device.id, now.isoformat(), battery))
        return _body(204, f"No image to show ({reason})", data={"next_cron_time": next_cron})

    try:
        prepare.get_prepared(device, photo)
    except Exception:
        log.exception("failed to prepare photo %s for %s", photo["id"], device.id)
        return _body(500, "Failed to prepare image")

    url = image_url(request, device, photo)
    with db.tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pulls (pull_id, device_id, photo_id, image_url, at, battery) VALUES (?,?,?,?,?,?)",
            (pull_id, device.id, photo["id"], url, now.isoformat(), battery),
        )
        conn.execute("UPDATE device_state SET last_photo_id = ?, last_image_url = ? WHERE device_id = ?",
                     (photo["id"], url, device.id))
    log.info("pull %s: %s battery=%s -> photo %s (%s), next %s", device.id, pull_id, battery, photo["id"], reason, next_cron)
    return _body(200, "Image retrieved successfully", type="SHOW",
                 data={"next_cron_time": next_cron, "image_url": url})


@router.get("/eink_signal")
def eink_signal(request: Request):
    q = request.query_params
    pull_id = q.get("pull_id")
    if not pull_id:
        return _body(400, "pull_id is required")
    token = request.headers.get("X-Access-Token")
    device = _device_for_token(token) if token else None
    if token and not device:
        return _body(401, "Unauthorized")

    now = schedule.utc_now().isoformat()
    success = q.get("success", "1") not in ("0", "false", "")
    with db.tx() as conn:
        sql = "SELECT * FROM pulls WHERE pull_id = ?" + (" AND device_id = ?" if device else "") + " ORDER BY at DESC, rowid DESC LIMIT 1"
        row = conn.execute(sql, (pull_id, device.id) if device else (pull_id,)).fetchone()
        if not row:
            log.warning("eink_signal for unknown pull_id %s (%s)", pull_id, dict(q))
            return _body(404, "Unknown pull_id")
        conn.execute("UPDATE pulls SET signaled_at = ?, success = ? WHERE device_id = ? AND pull_id = ?",
                     (now, int(success), row["device_id"], pull_id))
        if success:
            conn.execute("UPDATE device_state SET last_success_at = ? WHERE device_id = ?", (now, row["device_id"]))
    log.info("signal %s: pull %s success=%s (%s)", row["device_id"], pull_id, success, dict(q))
    return _body(200, "Feedback recorded")


_NAME = re.compile(r"^(\d+)-([0-9a-f]+)(_[A-Za-z]\.\w+)$")


@router.get("/image/{secret}/{name}")
def image(secret: str, name: str):
    device = cfg.config.by_secret(secret)
    m = _NAME.match(name)
    if not device or not m:
        return Response(status_code=404)
    photo_id, key, suffix = int(m[1]), m[2], m[3]
    pipe = pipelines.get(device.pipeline)
    with db.tx() as conn:
        photo = db.photo(conn, photo_id)
    # Only serve the version the URL names; a stale URL (tuning changed since) 404s.
    if not photo or suffix != pipe.file_suffix or prepare.cache_key(device, photo) != key:
        return Response(status_code=404)
    path = prepare.get_prepared(device, photo)
    log.info("image %s -> %s (%d bytes)", device.id, name, path.stat().st_size)
    return FileResponse(path, media_type=pipe.content_type)
