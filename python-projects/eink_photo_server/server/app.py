"""FastAPI entrypoint: protocol adapters for the frames + the admin web UI."""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from . import config as cfg
from . import db, pipelines, sidecar, sources
from .protocols import ROUTERS, SHARED_ROUTER
from .protocols.source_upload import router as source_upload_router
from .web.common import FormError, form_error_handler
from .web.frame_routes import router as frame_router
from .web.playlist_routes import router as playlist_router
from .web.routes import router as web_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eink_photo_server")

db.init()
sidecar.backfill()  # create missing sidecars (from EXIF) and rebuild the tag index
sources.scan_all()  # pick up anything dropped into folder sources while we were down
sources.start_scanner(int(os.environ.get("SCAN_INTERVAL", "60")))
for dev in cfg.config.devices.values():
    pipelines.get(dev.pipeline)  # fail fast on a typo'd pipeline name
    if dev.protocol not in ROUTERS:
        raise SystemExit(f"device {dev.id}: unknown protocol {dev.protocol!r}")
log.info("devices: %s; pipelines: %s", ", ".join(cfg.config.devices) or "none", ", ".join(pipelines.names()))

app = FastAPI(title="eInk Photo Server", docs_url=None, redoc_url=None)
app.add_exception_handler(FormError, form_error_handler)


@app.get("/health")
def health():
    return {"status": "ok", "devices": len(cfg.config.devices)}


app.include_router(SHARED_ROUTER)   # /image/{secret}/{name}
app.include_router(source_upload_router)   # /sources/{id}/upload (token auth, not the admin UI)
for r in ROUTERS.values():
    app.include_router(r)
app.include_router(web_router)
app.include_router(playlist_router)
app.include_router(frame_router)
