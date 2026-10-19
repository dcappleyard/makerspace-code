"""Bloomin8 "Schedule Pull" protocol adapter.

Frame -> GET /eink_pull   (X-Access-Token header; device_id, pull_id, cron_time, battery query)
Frame -> GET {image_url}  (may not send the header -- hence the secret in the path)
Frame -> GET /eink_signal (pull_id, success) -- optional confirmation

Response bodies follow the reference implementations (Lukafin/bloomin8-pull-server,
fwmone/bloomin8_pull): HTTP is always 200 and the real status is in the JSON.
The pull logic itself is shared with other adapters (protocols/common.py).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import schedule
from . import common

log = logging.getLogger(__name__)
router = APIRouter()
PROTOCOL = "bloomin8"


def _body(status: int, message: str, **extra) -> JSONResponse:
    body = {"status": status, "message": message, **extra}
    if status >= 400:
        body["type"] = "ERROR"
    return JSONResponse(body, headers={"X-Server-Timestamp": schedule.iso_z(schedule.utc_now())})


@router.get("/eink_pull")
def eink_pull(request: Request):
    q = request.query_params
    now = schedule.utc_now()
    # Devices are identified by their token; the frame's own device_id is recorded
    # for reference only, so it doesn't need to be known ahead of time.
    device = common.device_for_token(request.headers.get("X-Access-Token"), PROTOCOL)
    if not device:
        sent = request.headers.get("X-Access-Token")
        log.warning("eink_pull with bad token from %s (device_id=%s, X-Access-Token=%s, headers=%s)",
                    request.client.host, q.get("device_id"), common.mask(sent), sorted(request.headers.keys()))
        common.log_unknown(q.get("device_id"), now, "bad token", token=common.mask(sent), ip=request.client.host)
        return _body(401, "Unauthorized")

    try:
        battery = int(q.get("battery")) if q.get("battery") is not None else None
    except ValueError:
        battery = None
    p = common.run_pull(request, device, now, scheduled_for=schedule.parse_iso(q.get("cron_time")),
                        battery=battery, hw_device_id=q.get("device_id"), pull_id=q.get("pull_id"))
    if p.error:
        return _body(500, "Failed to prepare image")
    if not p.photo:
        return _body(204, f"No image to show ({p.reason})", data={"next_cron_time": p.next_cron})
    return _body(200, "Image retrieved successfully", type="SHOW",
                 data={"next_cron_time": p.next_cron, "image_url": p.url})


@router.get("/eink_signal")
def eink_signal(request: Request):
    q = request.query_params
    pull_id = q.get("pull_id")
    if not pull_id:
        return _body(400, "pull_id is required")
    token = request.headers.get("X-Access-Token")
    device = common.device_for_token(token, PROTOCOL) if token else None
    if token and not device:
        return _body(401, "Unauthorized")
    success = q.get("success", "1") not in ("0", "false", "")
    device_id = common.record_signal(pull_id, device, success)
    if not device_id:
        log.warning("eink_signal for unknown pull_id %s (%s)", pull_id, dict(q))
        return _body(404, "Unknown pull_id")
    log.info("signal %s: pull %s success=%s (%s)", device_id, pull_id, success, dict(q))
    return _body(200, "Feedback recorded")
