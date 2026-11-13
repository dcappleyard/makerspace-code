"""Dashboard for the show runner: status, controls, live view, settings.

Runs inside runner.py (uvicorn in a daemon thread). The web side never changes
runner state itself: controls go through Runner.submit() (a queue the control
loop drains every tick) and status comes from Runner.status() (a snapshot the
loop rebuilds every tick).

    ADMIN_PASSWORD=...   # env var: if set, every route needs HTTP Basic auth (any user name)
"""
import asyncio
import base64
import datetime as dt
import json
import logging
import os
import secrets
import threading
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

import pixel_map
import shows
from schedule import Schedule
from testpattern import load_config

from . import config_edit

STATIC = Path(__file__).resolve().parent / "static"
COMMANDS = {"skip", "play", "on", "off", "resume", "scale"}
LIVE_FPS = 15
log = logging.getLogger("web")

_basic = HTTPBasic(auto_error=False)


def require_auth(creds: HTTPBasicCredentials | None = Depends(_basic)):
    pw = os.environ.get("ADMIN_PASSWORD", "")
    if not pw:
        return
    if not creds or not secrets.compare_digest(creds.password.encode(), pw.encode()):
        raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="sculpture"'})


def _parse_options(opts):
    """Option values from the page arrive as text; type them like play.py -o does."""
    out = {}
    for k, v in (opts or {}).items():
        out[k] = shows.parse_option(f"{k}={v}")[1] if isinstance(v, str) else v
    return out


def _windows_preview(cfg, days=7):
    s = Schedule.from_config(cfg)
    today = s.now().date()
    rows = []
    for i in range(days):
        d = today + dt.timedelta(days=i)
        sun = s.loc.sun(d)
        rows.append({"date": d.isoformat(),
                     "sunrise": sun["sunrise"].isoformat(), "sunset": sun["sunset"].isoformat(),
                     "windows": [[a.isoformat(), b.isoformat()] for a, b in s.intervals(d)]})
    return rows


def create_app(runner):
    app = FastAPI(title="Sculpture dashboard", dependencies=[Depends(require_auth)],
                  docs_url=None, redoc_url=None, openapi_url=None)
    pixels = pixel_map.load()

    def cfg_path():
        if runner.cfg_path is None:
            raise HTTPException(409, "runner has no config file")
        return Path(runner.cfg_path)

    async def run_cmd(name, **kw):
        fut = runner.submit(name, **kw)
        try:
            res = await asyncio.wait_for(asyncio.wrap_future(fut), timeout=10)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except asyncio.TimeoutError:
            raise HTTPException(504, "runner didn't respond")
        return {"ok": True, **(res or {}), "status": runner.status()}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/sculpture.js")
    def sculpture_js():
        return FileResponse(STATIC / "sculpture.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/status")
    def status():
        return runner.status()

    @app.get("/api/log")
    def get_log(n: int = 100):
        lines = list(runner.logbuf.lines) if runner.logbuf else []
        return {"lines": lines[-n:]}

    @app.get("/api/pixels")
    def get_pixels():
        return pixels

    @app.get("/api/shows")
    def get_shows():
        out = []
        for name in shows.available():
            try:
                m = shows.load(name)
                out.append({"name": name, "description": getattr(m, "DESCRIPTION", ""),
                             "options": getattr(m, "OPTIONS", None)})
            except Exception as e:
                out.append({"name": name, "description": f"(import error: {e})", "options": None})
        return out

    @app.post("/api/cmd/{name}")
    async def command(name: str, body: dict = Body(default={})):
        if name not in COMMANDS:
            raise HTTPException(404, f"no command {name}")
        if name == "play":
            body = {**body, "options": _parse_options(body.get("options"))}
        return await run_cmd(name, **body)

    @app.get("/api/stream")
    async def stream():
        async def gen():
            last_sent = None
            while True:
                st = runner.status()
                f = runner.mixer.last if st.get("streaming") else None
                if st.get("on") and st.get("entry") and st["entry"]["kind"] == "preset":
                    state = "preset"
                else:
                    state = "live" if f else "idle"
                msg = {"state": state, "frame": base64.b64encode(f).decode() if f else None}
                if msg != last_sent:
                    yield f"data: {json.dumps(msg)}\n\n"
                    last_sent = msg
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1 / LIVE_FPS)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/settings")
    def get_settings():
        return config_edit.read_settings(cfg_path())

    @app.put("/api/settings")
    async def put_settings(body: dict = Body(...), dry_run: bool = False):
        path = cfg_path()
        for e in body.get("rotation") or []:
            e["options"] = _parse_options(e.get("options"))
        try:
            cfg = config_edit.validate(body, load_config(path), runner.layout)
        except ValueError as e:
            raise HTTPException(400, str(e))
        preview = _windows_preview(cfg)
        if dry_run:
            return {"ok": True, "schedule": preview}
        try:
            config_edit.save(path, cfg)
        except ValueError as e:
            raise HTTPException(500, str(e))
        cfg.pop("_items", None)
        log.info("dashboard: settings saved to %s", path)
        res = await run_cmd("apply_config", cfg=load_config(path))
        return {**res, "schedule": preview, "settings": config_edit.read_settings(path)}

    @app.get("/api/schedule")
    def get_schedule(days: int = 7):
        return _windows_preview(runner.cfg, max(1, min(days, 31)))

    return app


def start_web(runner, bind, port):
    import uvicorn
    app = create_app(runner)
    server = uvicorn.Server(uvicorn.Config(app, host=bind, port=port, log_level="warning",
                                           access_log=False))
    threading.Thread(target=server.run, name="web", daemon=True).start()
    logging.getLogger("runner").info("dashboard on http://%s:%d/%s", bind, port,
                                     " (password set)" if os.environ.get("ADMIN_PASSWORD") else "")
    return server
