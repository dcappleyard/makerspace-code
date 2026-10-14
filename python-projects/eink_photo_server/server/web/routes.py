"""Minimal server-rendered admin UI: upload, playlists, pause, previews.

Every action is a form POST that redirects back to the page.
"""
from __future__ import annotations

import io
import json
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .. import config as cfg
from .. import db, photos, pipelines, prepare, testcards
from ..pipelines.base import NEUTRAL_TUNING, load_oriented

_basic = HTTPBasic(auto_error=False)


def require_admin(creds: HTTPBasicCredentials | None = Depends(_basic)):
    if not cfg.ADMIN_PASSWORD:
        return
    if not creds or not secrets.compare_digest(creds.password.encode(), cfg.ADMIN_PASSWORD.encode()):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


router = APIRouter(dependencies=[Depends(require_admin)])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

TUNING_KEYS = ("saturation", "contrast", "brightness", "gamma")


def _local(ts: str | None) -> str:
    if not ts:
        return "—"
    return datetime.fromisoformat(ts).astimezone(cfg.config.tz).strftime("%a %b %d %H:%M")


templates.env.filters["local"] = _local


def _back() -> RedirectResponse:
    return RedirectResponse("/", status_code=303)


def _device(device_id: str):
    dev = cfg.config.devices.get(device_id)
    if not dev:
        raise HTTPException(404, "unknown device")
    return dev


@router.get("/")
def index(request: Request):
    with db.tx() as conn:
        all_photos = conn.execute("SELECT * FROM photos ORDER BY id DESC").fetchall()
        devices = []
        for dev in cfg.config.devices.values():
            devices.append({
                "dev": dev,
                "state": db.state(conn, dev.id),
                "playlist": db.playlist(conn, dev.id),
                "params": {**pipelines.get(dev.pipeline).default_params, **dev.tuning},
            })
    return templates.TemplateResponse(request, "index.html", {
        "devices": devices,
        "photos": all_photos,
        "photo_by_id": {p["id"]: p for p in all_photos},
        "tz": str(cfg.config.tz),
        "pipelines": pipelines.names(),
        "tuning_keys": TUNING_KEYS,
        "json": json,
    })


@router.post("/ui/upload")
async def upload(files: list[UploadFile] = File(...)):
    for f in files:
        if f.filename:
            photos.ingest(f.filename, await f.read())
    return _back()


@router.get("/ui/thumb/{photo_id}")
def thumb(photo_id: int):
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
    if not p:
        raise HTTPException(404)
    return FileResponse(photos.thumb_path(p), media_type="image/jpeg")


@router.get("/ui/preview/{device_id}/{photo_id}/{kind}")
def preview(device_id: str, photo_id: int, kind: str):
    dev = _device(device_id)
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
    if not p:
        raise HTTPException(404)
    if kind == "prepared":
        return FileResponse(prepare.get_prepared(dev, p), media_type=pipelines.get(dev.pipeline).content_type)
    path = prepare.get_preview(dev, p)
    if not path:
        raise HTTPException(404, "pipeline has no preview")
    return FileResponse(path, media_type="image/png")


@router.post("/ui/photo/{photo_id}/delete")
def photo_delete(photo_id: int):
    photos.delete(photo_id)
    return _back()


@router.post("/ui/photo/{photo_id}/focal")
def photo_focal(photo_id: int, x: float = Form(...), y: float = Form(...)):
    with db.tx() as conn:
        conn.execute("UPDATE photos SET focal_x = ?, focal_y = ? WHERE id = ?",
                     (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0), photo_id))
    return _back()


@router.post("/ui/photo/{photo_id}/tuning")
async def photo_tuning(photo_id: int, request: Request):
    form = await request.form()
    params = {}
    for k in TUNING_KEYS:
        v = str(form.get(k, "")).strip()
        if v:
            params[k] = float(v)
    with db.tx() as conn:
        conn.execute("UPDATE photos SET params_json = ? WHERE id = ?", (json.dumps(params), photo_id))
    return _back()


@router.post("/ui/device/{device_id}/pause")
def device_pause(device_id: str):
    _device(device_id)
    with db.tx() as conn:
        db.state(conn, device_id)
        conn.execute("UPDATE device_state SET paused = 1 - paused WHERE device_id = ?", (device_id,))
    return _back()


@router.post("/ui/device/{device_id}/add")
def device_add(device_id: str, photo_id: int = Form(...)):
    _device(device_id)
    with db.tx() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_items WHERE device_id = ?",
                           (device_id,)).fetchone()[0]
        conn.execute("INSERT INTO playlist_items (device_id, photo_id, position) VALUES (?,?,?)",
                     (device_id, photo_id, pos))
    return _back()


@router.post("/ui/item/{item_id}/move")
def item_move(item_id: int, direction: str = Form(...)):
    with db.tx() as conn:
        it = conn.execute("SELECT * FROM playlist_items WHERE id = ?", (item_id,)).fetchone()
        if not it:
            raise HTTPException(404)
        items = db.playlist(conn, it["device_id"])
        ids = [i["id"] for i in items]
        i = ids.index(item_id)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        for pos, iid in enumerate(ids):
            conn.execute("UPDATE playlist_items SET position = ? WHERE id = ?", (pos, iid))
    return _back()


@router.post("/ui/item/{item_id}/remove")
def item_remove(item_id: int):
    with db.tx() as conn:
        conn.execute("DELETE FROM playlist_items WHERE id = ?", (item_id,))
    return _back()


@router.post("/ui/item/{item_id}/window")
def item_window(item_id: int, start: str = Form(""), end: str = Form("")):
    start, end = start.strip() or None, end.strip() or None
    if bool(start) != bool(end):
        raise HTTPException(400, "set both start and end, or neither")
    for v in (start, end):
        if v:
            cfg.parse_hhmm(v)
    with db.tx() as conn:
        conn.execute("UPDATE playlist_items SET window_start = ?, window_end = ? WHERE id = ?",
                     (start, end, item_id))
    return _back()


@router.post("/ui/reload")
def reload_config():
    cfg.reload()
    return _back()


@router.post("/ui/device/{device_id}/queue")
def device_queue(device_id: str, photo_id: int | None = Form(None)):
    """Serve this photo on the device's next pull (one shot). Empty photo_id clears it."""
    _device(device_id)
    with db.tx() as conn:
        db.state(conn, device_id)
        conn.execute("UPDATE device_state SET queued_photo_id = ? WHERE device_id = ?", (photo_id, device_id))
    return _back()


# --- Test cards -------------------------------------------------------------

SEGMENTS = "ABC"
# Starting offsets either side of the device's current tuning.
_VARIANT = {"saturation": 0.2, "contrast": 0.1, "brightness": 0.0, "gamma": 0.0}


def _card_args(form) -> tuple:
    """(device, kind, photo row or None, segments) from query/form fields."""
    dev = _device(form.get("device") or next(iter(cfg.config.devices), ""))
    kind = form.get("kind") or "color"
    if kind not in testcards.KINDS:
        raise HTTPException(400, "unknown card kind")
    photo = None
    if form.get("photo_id"):
        with db.tx() as conn:
            photo = db.photo(conn, int(form["photo_id"]))
    base = {**pipelines.get(dev.pipeline).default_params, **dev.tuning}
    segments = []
    for i, seg in enumerate(SEGMENTS):
        params = {}
        for k in TUNING_KEYS:
            v = str(form.get(f"{seg}_{k}", "")).strip()
            params[k] = float(v) if v else round(float(base.get(k, 1.0)) + (i - 1) * _VARIANT[k], 3)
        segments.append(params)
    return dev, kind, photo, segments


def _render(form):
    dev, kind, photo, segments = _card_args(form)
    photo_img = load_oriented(photos.original_path(photo)) if photo else None
    focal = (photo["focal_x"], photo["focal_y"]) if photo else (0.5, 0.5)
    return dev, kind, testcards.render_card(kind, dev.width, dev.height, segments, photo_img, focal)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@router.get("/testcard")
def testcard_page(request: Request):
    q = request.query_params
    if not cfg.config.devices:
        raise HTTPException(400, "no devices configured")
    dev, kind, photo, segments = _card_args(q)
    with db.tx() as conn:
        all_photos = conn.execute("SELECT id, filename FROM photos ORDER BY id DESC").fetchall()
    return templates.TemplateResponse(request, "testcard.html", {
        "devices": list(cfg.config.devices.values()),
        "dev": dev, "kind": kind, "photo": photo, "photos": all_photos,
        "segments": list(zip(SEGMENTS, segments)), "tuning_keys": TUNING_KEYS,
        "kinds": testcards.KINDS,
        "query": urlencode({
            "device": dev.id, "kind": kind, "photo_id": photo["id"] if photo else "",
            **{f"{seg}_{k}": params[k] for seg, params in zip(SEGMENTS, segments) for k in TUNING_KEYS},
        }),
    })


@router.get("/testcard/render")
def testcard_render(request: Request, view: str = "card"):
    dev, kind, card = _render(request.query_params)
    if view == "sim":
        pipe = pipelines.get(dev.pipeline)
        sim = pipe.preview(card, dev, {**pipe.default_params, **NEUTRAL_TUNING})
        if sim is None:
            raise HTTPException(404, "pipeline has no preview")
        card = sim
    return Response(_png(card), media_type="image/png")


@router.post("/testcard/save")
async def testcard_save(request: Request):
    form = await request.form()
    dev, kind, card = _render(form)
    name = f"testcard-{kind}-{datetime.now(cfg.config.tz):%Y%m%d-%H%M}.png"
    photo_id = photos.ingest(name, _png(card))
    with db.tx() as conn:
        # The card is already tuned per column; bypass device/pipeline tuning.
        conn.execute("UPDATE photos SET params_json = ? WHERE id = ?", (json.dumps(NEUTRAL_TUNING), photo_id))
        if form.get("queue"):
            db.state(conn, dev.id)
            conn.execute("UPDATE device_state SET queued_photo_id = ? WHERE device_id = ?", (photo_id, dev.id))
    return _back()
