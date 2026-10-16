"""FastAPI entrypoint: protocol adapters for the frames + the admin web UI."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from . import config as cfg
from . import db, pipelines
from .protocols import ROUTERS
from .web.common import FormError, form_error_handler
from .web.frame_routes import router as frame_router
from .web.routes import router as web_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eink_photo_server")

db.init()
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


for r in ROUTERS.values():
    app.include_router(r)
app.include_router(web_router)
app.include_router(frame_router)
