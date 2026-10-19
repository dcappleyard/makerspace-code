"""Pull protocol for the DIY ESP32 frames (esp32-projects/xiao_s3_ee03_pull_frame).

Frame -> GET /esp32/v1/pull    X-Access-Token header; query:
           device_id      the board's id (recorded for reference)
           scheduled_for  the next_check_at it was given last time (ISO UTC), if any
           current        the image name it's showing now, if any
           reason         timer | boot | manual | retry
         <- 200 JSON, always:
           {"status": "show" | "keep" | "none" | "error",
            "pull_id", "next_check_s", "next_check_at",
            "image_url", "image_bytes", "sha256", "name"}      (show only)
Frame -> GET {image_url}       the prepared buffer (e.g. a packed .bin), streamed to SD
Frame -> GET /esp32/v1/signal  pull_id, success=1|0 -- after the panel refresh

"keep" means the frame already shows the right image: no download, no refresh.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import schedule
from . import common

log = logging.getLogger(__name__)
router = APIRouter()
PROTOCOL = "esp32_pull"


def _json(status: str, **fields) -> JSONResponse:
    return JSONResponse({"status": status, **fields})


@router.get("/esp32/v1/pull")
def pull(request: Request):
    q = request.query_params
    now = schedule.utc_now()
    device = common.device_for_token(request.headers.get("X-Access-Token"), PROTOCOL)
    if not device:
        sent = request.headers.get("X-Access-Token")
        log.warning("esp32 pull with bad token from %s (device_id=%s, token=%s)",
                    request.client.host, q.get("device_id"), common.mask(sent))
        common.log_unknown(q.get("device_id"), now, "bad token", token=common.mask(sent), ip=request.client.host)
        return _json("error", message="unauthorized", next_check_s=300)

    p = common.run_pull(request, device, now, scheduled_for=schedule.parse_iso(q.get("scheduled_for")),
                        hw_device_id=q.get("device_id"))
    timing = {"pull_id": p.pull_id, "next_check_s": int((p.sent - now).total_seconds()),
              "next_check_at": p.next_cron}
    if p.error:
        return _json("error", message="failed to prepare image", **timing)
    if not p.photo:
        return _json("none", message=p.reason, **timing)
    if q.get("current") == p.name:
        # Already on screen: nothing to download or display, so close the pull
        # out here (the frame won't signal) and keep the retry guard quiet.
        common.record_signal(p.pull_id, device, True, summary=f"kept {p.name} (already showing)")
        return _json("keep", name=p.name, **timing)
    return _json("show", image_url=p.url, image_bytes=p.path.stat().st_size,
                 sha256=common.sha256_file(p.path), name=p.name, **timing)


@router.get("/esp32/v1/signal")
def signal(request: Request):
    q = request.query_params
    device = common.device_for_token(request.headers.get("X-Access-Token"), PROTOCOL)
    if not device:
        return _json("error", message="unauthorized")
    if not q.get("pull_id"):
        return _json("error", message="pull_id is required")
    success = q.get("success", "1") not in ("0", "false", "")
    if not common.record_signal(q["pull_id"], device, success):
        return _json("error", message="unknown pull_id")
    return _json("ok")
