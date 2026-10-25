"""Admin UI: the Sources section -- one page per raw source (Library, folder
sources such as the Photobooth, Test cards) plus the photo actions they share.

Playlists and frames live in playlist_routes.py / frame_routes.py. Every action
is a form POST that redirects back to the page it came from.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from .. import config as cfg
from .. import db, photos, pipelines, prepare, sidecar, sources, testcards
from ..pipelines.base import NEUTRAL_TUNING, TUNING_KEYS, load_oriented
from .common import back, device_or_404, require_admin, templates

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/")
def index():
    return RedirectResponse("/sources/library", status_code=303)


def grid_context(conn, rows) -> dict:
    """What _photo_grid.html needs for a list of photo rows."""
    in_playlists = {}
    for r in conn.execute("SELECT DISTINCT i.photo_id, p.id, p.name FROM playlist_items i "
                          "JOIN playlists p ON p.id = i.playlist_id"):
        in_playlists.setdefault(r["photo_id"], []).append((r["id"], r["name"]))
    return {
        "photos": rows,
        "metas": {p["id"]: sidecar.read(p) for p in rows},
        "in_playlists": in_playlists,
        "devices": list(cfg.config.devices.values()),
        "all_playlists": conn.execute("SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE").fetchall(),
        "fields": sidecar.FIELDS,
        "labels": sidecar.LABELS,
        "tuning_keys": TUNING_KEYS,
        "json": json,
    }


@router.get("/sources/{key}")
def source_page(request: Request, key: str, tag: str = ""):
    if key == "testcards":
        return testcard_page(request)
    if not sources.is_raw(key):
        raise HTTPException(404, "unknown source")
    tag = " ".join(tag.split()).lower()
    with db.tx() as conn:
        if tag:
            rows = conn.execute(
                "SELECT p.* FROM photos p JOIN photo_tags t ON t.photo_id = p.id "
                "WHERE p.source = ? AND t.tag = ? ORDER BY p.id DESC", (key, tag)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM photos WHERE source = ? ORDER BY id DESC", (key,)).fetchall()
        tag_counts = conn.execute(
            "SELECT t.tag, COUNT(*) AS n FROM photo_tags t JOIN photos p ON p.id = t.photo_id "
            "WHERE p.source = ? GROUP BY t.tag ORDER BY t.tag", (key,)).fetchall()
        ctx = grid_context(conn, rows)
    folder = cfg.config.sources.get(key)
    scanned = sources.last_scan.get(key)
    base = cfg.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return templates.TemplateResponse(request, "source.html", {
        **ctx, "section": "sources", "page": key, "source_key": key,
        "source_name": sources.label(None, key) if key in sources.BUILTIN else folder.name,
        "folder": folder, "folder_path": str(folder.path) if folder else None,
        "upload_url": f"{base}/sources/{key}/upload" if folder else None,
        "last_scan": datetime.fromtimestamp(scanned, cfg.config.tz).strftime("%a %b %d %H:%M:%S") if scanned else None,
        "tag": tag, "tag_counts": tag_counts,
    })


@router.post("/ui/source/{key}/rescan")
def source_rescan(request: Request, key: str):
    src = cfg.config.sources.get(key)
    if not src:
        raise HTTPException(404)
    sources.scan(src)
    return back(request)


@router.get("/testcard")
def testcard_redirect(request: Request):
    q = str(request.query_params)
    return RedirectResponse("/sources/testcards" + (f"?{q}" if q else ""), status_code=303)


@router.post("/ui/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    """Images, optionally with same-named .xml sidecars (e.g. harbor.jpg +
    harbor.xml from prepare_image.py) in the same batch."""
    images, sidecars = [], {}
    for f in files:
        if not f.filename:
            continue
        name = Path(f.filename).name
        if name.lower().endswith(".xml"):
            sidecars[Path(name).stem.lower()] = await f.read()
        else:
            images.append((name, await f.read()))
    for name, data in images:
        photos.ingest(name, data, sidecars.pop(Path(name).stem.lower(), None))
    if sidecars:
        return back(request, error=f"No matching image for sidecar(s): {', '.join(sorted(sidecars))}.xml "
                                   "-- upload each .xml together with its image.")
    return back(request)


@router.post("/ui/photo/{photo_id}/meta")
async def photo_meta(request: Request, photo_id: int):
    form = await request.form()
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
    if not p:
        raise HTTPException(404)
    meta = sidecar.read(p)
    for f in sidecar.FIELDS:
        meta[f] = " ".join(str(form.get(f, "")).split())
    meta["tags"] = sidecar.normalize_tags(str(form.get("tags", "")))
    sidecar.write(p, meta)
    return back(request)


@router.get("/ui/photo/{photo_id}/sidecar.xml")
def photo_sidecar(photo_id: int):
    with db.tx() as conn:
        p = db.photo(conn, photo_id)
    if not p:
        raise HTTPException(404)
    sidecar.read(p)  # creates it if missing
    return FileResponse(sidecar.path_for(p), media_type="application/xml",
                        filename=f"{Path(p['filename']).stem}.xml")


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
        pipe = pipelines.get(dev.pipeline)
        path = prepare.get_prepared(dev, p)
        if not pipe.content_type.startswith("image/"):
            img = pipe.decode(path.read_bytes(), dev)
            if img is None:
                return FileResponse(path, media_type=pipe.content_type, filename=path.name)
            return Response(_png(img), media_type="image/png")
        return FileResponse(path, media_type=pipe.content_type)
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
    w, h = pipelines.get(dev.pipeline).content_size(dev)   # e.g. just the panorama strip
    return dev, kind, testcards.render_card(kind, w, h, segments, photo_img, focal)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def testcard_page(request: Request):
    q = request.query_params
    if not cfg.config.devices:
        return RedirectResponse("/frames?" + urlencode({"error": "Add a frame to devices.yaml (and Reload) before making test cards."}),
                                status_code=303)
    dev, kind, photo, segments = _card_args(q)
    with db.tx() as conn:
        all_photos = conn.execute("SELECT id, filename FROM photos ORDER BY id DESC").fetchall()
        ctx = grid_context(conn, conn.execute(
            "SELECT * FROM photos WHERE source = 'testcards' ORDER BY id DESC").fetchall())
    return templates.TemplateResponse(request, "testcard.html", {
        **ctx,
        "dev": dev, "kind": kind, "photo": photo, "strip_photos": all_photos,
        "section": "sources", "page": "testcards",
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
    photo_id = photos.ingest(name, _png(card), source="testcards")
    with db.tx() as conn:
        # The card is already tuned per column; bypass device/pipeline tuning.
        conn.execute("UPDATE photos SET params_json = ? WHERE id = ?", (json.dumps(NEUTRAL_TUNING), photo_id))
        if form.get("queue"):
            db.state(conn, dev.id)
            conn.execute("UPDATE device_state SET queued_photo_id = ? WHERE device_id = ?", (photo_id, dev.id))
    if form.get("queue"):
        return RedirectResponse(f"/frame/{dev.id}", status_code=303)
    return RedirectResponse("/sources/testcards", status_code=303)
