"""Admin UI: the library (upload, photos, add to frame) and the test card page.

Frame pages live in frame_routes.py. Every action is a form POST that
redirects back to the page it came from.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from .. import config as cfg
from .. import db, photos, pipelines, prepare, testcards
from ..pipelines.base import NEUTRAL_TUNING, TUNING_KEYS, load_oriented
from .common import back, device_or_404, require_admin, templates

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/")
def index(request: Request):
    with db.tx() as conn:
        all_photos = conn.execute("SELECT * FROM photos ORDER BY id DESC").fetchall()
        in_playlists = {}
        for r in conn.execute("SELECT DISTINCT device_id, photo_id FROM playlist_items"):
            in_playlists.setdefault(r["photo_id"], []).append(r["device_id"])
    return templates.TemplateResponse(request, "index.html", {
        "page": "home",
        "devices": list(cfg.config.devices.values()),
        "photos": all_photos,
        "in_playlists": in_playlists,
        "tz": str(cfg.config.tz),
        "pipelines": pipelines.names(),
        "tuning_keys": TUNING_KEYS,
        "json": json,
    })


@router.post("/ui/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    for f in files:
        if f.filename:
            photos.ingest(f.filename, await f.read())
    return back(request)


@router.get("/ui/thumb/{photo_id}")
def thumb(photo_id: int):
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
    if not p:
        raise HTTPException(404)
    return FileResponse(photos.thumb_path(p), media_type="image/jpeg")


@router.get("/ui/preview/{device_id}/{photo_id}/{kind}")
def preview(device_id: str, photo_id: int, kind: str):
    dev = device_or_404(device_id)
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
def photo_delete(request: Request, photo_id: int):
    photos.delete(photo_id)
    return back(request)


@router.post("/ui/photo/{photo_id}/focal")
def photo_focal(request: Request, photo_id: int, x: float = Form(...), y: float = Form(...)):
    with db.tx() as conn:
        conn.execute("UPDATE photos SET focal_x = ?, focal_y = ? WHERE id = ?",
                     (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0), photo_id))
    return back(request)


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
    return back(request)


@router.post("/ui/reload")
def reload_config(request: Request):
    cfg.reload()
    return back(request)


# --- Test cards -------------------------------------------------------------

SEGMENTS = "ABC"
# Starting offsets either side of the device's current tuning.
_VARIANT = {"saturation": 0.2, "contrast": 0.1, "brightness": 0.0, "gamma": 0.0,
            "lift": 0.0, "lift_threshold": 0.0}


def _card_args(form) -> tuple:
    """(device, kind, photo row or None, segments) from query/form fields."""
    dev = device_or_404(form.get("device") or next(iter(cfg.config.devices), ""))
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
            params[k] = float(v) if v else round(float(base.get(k, NEUTRAL_TUNING[k])) + (i - 1) * _VARIANT[k], 3)
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
        return RedirectResponse("/?" + urlencode({"error": "Add a frame to devices.yaml (and Reload) before making test cards."}),
                                status_code=303)
    dev, kind, photo, segments = _card_args(q)
    with db.tx() as conn:
        all_photos = conn.execute("SELECT id, filename FROM photos ORDER BY id DESC").fetchall()
    return templates.TemplateResponse(request, "testcard.html", {
        "devices": list(cfg.config.devices.values()),
        "dev": dev, "kind": kind, "photo": photo, "photos": all_photos,
        "page": "testcard",
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
    if form.get("queue"):
        return RedirectResponse(f"/frame/{dev.id}", status_code=303)
    return RedirectResponse("/", status_code=303)
