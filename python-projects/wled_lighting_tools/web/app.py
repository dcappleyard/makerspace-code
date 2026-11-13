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

import effects
import pixel_map
import program
import shows
from schedule import Schedule
from testpattern import load_config

from . import config_edit
from .audition import Auditioner

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
        out[k] = effects.parse_option(f"{k}={v}")[1] if isinstance(v, str) else v
    return out


def _windows_preview(cfg, days=7):
    s = Schedule.from_config(cfg, shows.default_show_name(cfg, list(shows.raw_shows(cfg))))
    today = s.now().date()
    rows = []
    for i in range(days):
        d = today + dt.timedelta(days=i)
        sun = s.loc.sun(d)
        rows.append({"date": d.isoformat(),
                     "sunrise": sun["sunrise"].isoformat(), "sunset": sun["sunset"].isoformat(),
                     "windows": [[iv.start.isoformat(), iv.end.isoformat(), iv.show] for iv in s.intervals(d)]})
    return rows


def create_app(runner):
    app = FastAPI(title="Sculpture dashboard", dependencies=[Depends(require_auth)],
                  docs_url=None, redoc_url=None, openapi_url=None)
    pixels = pixel_map.load()
    audition = Auditioner(runner.layout)

    def cfg_path():
        """The file settings are read from and saved to: the program file
        (program/program.yaml), or the machine config if there isn't one."""
        if runner.settings_path is None:
            raise HTTPException(409, "runner has no config file")
        return Path(runner.settings_path)

    def merged(path):
        return program.merge(runner.machine_cfg, load_config(path))

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

    @app.get("/api/effects")
    def get_effects():
        out = []
        for name in effects.available():
            try:
                m = effects.load(name)
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
            body = {k: v for k, v in body.items() if v not in (None, "")}
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

    # ------------------------------------------------------------ audition
    @app.post("/api/audition")
    def audition_start(body: dict = Body(...)):
        """{effect, options} | {show: saved name} | {show_body: unsaved show}, plus seconds_each."""
        secs = body.get("seconds_each")
        secs = float(secs) if secs not in (None, "", 0) else None
        sc = runner.cfg.get("schedule", {})
        g_scale, g_fade = float(sc.get("scale", 1.0)), float(sc.get("transition_seconds", 2))
        try:
            if body.get("effect"):
                spec = {"effect": body["effect"], "options": _parse_options(body.get("options"))}
                ents = shows.parse_entries([spec], 1, where="audition", strict=True)
                audition.start(ents, body["effect"], scale=g_scale, fade_s=g_fade, seconds_each=None)
            elif body.get("show_body") is not None:
                sb = body["show_body"]
                items = [config_edit._entry_out({**e, "options": _parse_options(e.get("options"))})
                         for e in sb.get("effects") or []]
                minutes = float(sb.get("minutes_each") or sc.get("minutes_each", 10))
                ents = shows.parse_entries(items, minutes, where="show", strict=True)
                audition.start(ents, body.get("label") or "unsaved show",
                               scale=float(sb["scale"]) if sb.get("scale") not in (None, "") else g_scale,
                               fade_s=float(sb["transition_seconds"]) if sb.get("transition_seconds") not in (None, "") else g_fade,
                               seconds_each=secs)
            elif body.get("show"):
                sh = runner.shows.get(body["show"])
                if sh is None:
                    raise ValueError(f"no show {body['show']!r}")
                audition.start(sh.entries, sh.name, scale=sh.scale, fade_s=sh.fade_s, seconds_each=secs)
            else:
                raise ValueError("say which effect or show to audition")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, **{k: v for k, v in audition.status().items() if k != "frame"}}

    @app.post("/api/audition/next")
    def audition_next():
        audition.next()
        return {"ok": True}

    @app.post("/api/audition/stop")
    def audition_stop():
        audition.stop()
        return {"ok": True}

    @app.get("/api/audition/stream")
    async def audition_stream():
        async def gen():
            audition.watch(+1)
            last = None
            try:
                while True:
                    st = audition.status()
                    f = st.pop("frame")
                    msg = {**st, "state": "live" if f else ("preset" if st["kind"] == "preset" else "idle"),
                           "frame": base64.b64encode(f).decode() if f else None}
                    if msg != last:
                        yield f"data: {json.dumps(msg)}\n\n"
                        last = msg
                    else:
                        yield ": keepalive\n\n"
                    await asyncio.sleep(1 / 15)
            finally:
                audition.watch(-1)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------ settings
    @app.get("/api/settings")
    def get_settings():
        return settings_payload(cfg_path())

    def settings_payload(path):
        """Settings plus which file/version they came from. The page sends
        `mtime` back on save, so a file changed on disk since (git pull, hand
        edit) isn't silently overwritten."""
        return {**config_edit.read_settings(path), "file": str(path),
                "tracked": path == runner.watch_path, "mtime": program.mtime(path)}

    @app.put("/api/settings")
    async def put_settings(body: dict = Body(...), dry_run: bool = False, force: bool = False):
        path = cfg_path()
        if not dry_run and not force and body.get("mtime") is not None \
                and body["mtime"] != program.mtime(path):
            raise HTTPException(409, f"{path.name} changed on disk since this page loaded it "
                                     "(git pull or a hand edit?). Reload, or save anyway to overwrite.")
        for sh in (body.get("shows") or {}).values():
            for e in (sh or {}).get("effects") or []:
                e["options"] = _parse_options(e.get("options"))
        try:
            cfg = config_edit.validate(body, merged(path), runner.layout)
        except ValueError as e:
            raise HTTPException(400, str(e))
        preview = _windows_preview(cfg)
        if dry_run:
            return {"ok": True, "schedule": preview}
        try:
            config_edit.save(path, cfg)
        except ValueError as e:
            raise HTTPException(500, str(e))
        log.info("dashboard: settings saved to %s", path)
        res = await run_cmd("apply_config", cfg=merged(path))
        return {**res, "schedule": preview, "settings": settings_payload(path)}

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
