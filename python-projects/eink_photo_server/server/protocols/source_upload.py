"""Uploads into a folder source (e.g. the photobooth camera after each sequence).

POST /sources/{id}/upload
  X-Access-Token: the source's upload_token (devices.yaml `sources:`)
  X-Filename:     the camera's name for it, e.g. 2026-10-24_19-02-11_A.jpg
  body:           the image bytes (Content-Type image/jpeg)
<- 200 {"status": "stored" | "duplicate", "id": <photo id>, "name": <stored filename>}
   4xx {"status": "error", "message": ...}

The file lands in the source's folder on the server (human-readable name), is
ingested with a sidecar seeded from its name (date, shot letter) and the
source's tags, and is then available to playlists and schedule blocks.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import config as cfg
from .. import sources

log = logging.getLogger(__name__)
router = APIRouter()
MAX_BYTES = 25 * 1024 * 1024


def _err(code: int, message: str) -> JSONResponse:
    return JSONResponse({"status": "error", "message": message}, status_code=code)


@router.post("/sources/{source_id}/upload")
async def upload(source_id: str, request: Request):
    src = cfg.config.sources.get(source_id)
    token = request.headers.get("X-Access-Token", "")
    if not src or not src.upload_token or not secrets.compare_digest(token.encode(), src.upload_token.encode()):
        log.warning("source upload refused for %r from %s", source_id, request.client.host)
        return _err(401, "unauthorized")
    name = sources.safe_name(request.headers.get("X-Filename", ""))
    if not name:
        return _err(400, "X-Filename must be an image file name (.jpg, .png, ...)")
    data = await request.body()
    if not data:
        return _err(400, "empty body")
    if len(data) > MAX_BYTES:
        return _err(413, "too large")
    try:
        pid, status, stored = sources.store_upload(src, name, data)
    except Exception as e:
        log.exception("source %s: upload of %s failed", source_id, name)
        return _err(422, f"not a readable image: {e}")
    log.info("source %s: %s %s as #%s", source_id, status, stored, pid)
    return {"status": status, "id": pid, "name": stored}
