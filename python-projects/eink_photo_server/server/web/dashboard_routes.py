"""Admin UI: Sources → Dashboards. List and create dashboards, and edit one's
settings with a live preview drawn natively for every configured frame."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from .. import config as cfg
from .. import dashboards, db, pipelines, prepare
from .common import FormError, back, device_or_404, require_admin, templates

router = APIRouter(dependencies=[Depends(require_admin)])


def _frames():
    """Configured frames whose pipeline can draw dashboards."""
    out = []
    for dev in cfg.config.devices.values():
        pipe = pipelines.get(dev.pipeline)
        if type(pipe).encode_rendered is not pipelines.base.Pipeline.encode_rendered:
            out.append(dev)
    return out


def _load(conn, dashboard_id: int):
    dash = db.dashboard(conn, dashboard_id)
    if not dash:
        raise HTTPException(404, "unknown dashboard")
    photo = conn.execute("SELECT * FROM photos WHERE kind = 'dashboard' AND dashboard_id = ?",
                         (dashboard_id,)).fetchone()
    return dash, photo


def dashboards_page(request: Request):
    with db.tx() as conn:
        rows = conn.execute("SELECT d.*, p.id AS photo_id FROM dashboards d "
                            "JOIN photos p ON p.kind = 'dashboard' AND p.dashboard_id = d.id "
                            "ORDER BY d.name COLLATE NOCASE, d.id").fetchall()
    cards = []
    for r in rows:
        try:
            t = dashboards.get(r["type"])
            status = t.status(dashboards.settings_of(r))
        except KeyError:
            t, status = None, {"error": f"unknown type {r['type']}"}
        cards.append({"d": r, "type": t, "status": status})
    return templates.TemplateResponse(request, "dashboards.html", {
        "section": "sources", "page": "dashboards", "cards": cards, "types": dashboards.types(),
        "frames": _frames(),
    })


@router.post("/ui/dashboards/create")
def dashboard_create(type: str = Form(...), name: str = Form(...)):
    try:
        t = dashboards.get(type)
    except KeyError:
        raise FormError("unknown dashboard type")
    name = " ".join(name.split())[:60] or t.label
    now = datetime.now(timezone.utc).isoformat()
    with db.tx() as conn:
        did = conn.execute("INSERT INTO dashboards (type, name, settings_json, created_at) VALUES (?,?,?,?)",
                           (t.name, name, json.dumps(t.default_settings), now)).lastrowid
        # Its item, so schedules/playlists/queueing can use it like a photo.
        conn.execute("INSERT INTO photos (sha, filename, ext, uploaded_at, source, kind, dashboard_id) "
                     "VALUES (?, ?, '', ?, 'dashboards', 'dashboard', ?)", (f"dashboard-{did}", name, now, did))
    _refresh_async(t, t.default_settings)
    return RedirectResponse(f"/dashboard/{did}", status_code=303)


def _refresh_async(t, settings):
    import threading
    threading.Thread(target=t.refresh, args=(settings,), name="dashboard-fetch", daemon=True).start()


@router.get("/dashboard/{dashboard_id}")
def dashboard_page(request: Request, dashboard_id: int):
    with db.tx() as conn:
        dash, photo = _load(conn, dashboard_id)
        uses = [r["device_id"] for r in conn.execute(
            "SELECT DISTINCT device_id FROM schedule_blocks WHERE source = ? OR photo_id = ?",
            (f"dashboard:{dashboard_id}", photo["id"]))]
        in_playlists = conn.execute("SELECT DISTINCT p.id, p.name FROM playlist_items i JOIN playlists p "
                                    "ON p.id = i.playlist_id WHERE i.photo_id = ?", (photo["id"],)).fetchall()
    t = dashboards.get(dash["type"])
    settings = dashboards.settings_of(dash)
    groups: dict[str, list] = {}
    for f in t.form:
        groups.setdefault(f.group or "Settings", []).append(f)
    return templates.TemplateResponse(request, "dashboard.html", {
        "section": "sources", "page": "dashboards", "dash": dash, "photo": photo, "type": t,
        "settings": settings, "groups": groups, "status": t.status(settings), "frames": _frames(),
        "uses": [cfg.config.devices[u] for u in uses if u in cfg.config.devices], "in_playlists": in_playlists,
    })


@router.post("/dashboard/{dashboard_id}/save")
async def dashboard_save(request: Request, dashboard_id: int):
    form = await request.form()
    with db.tx() as conn:
        dash, photo = _load(conn, dashboard_id)
        t = dashboards.get(dash["type"])
        settings = {**dashboards.settings_of(dash), **t.coerce(form)}
        name = " ".join(str(form.get("name", "")).split())[:60] or dash["name"]
        conn.execute("UPDATE dashboards SET name = ?, settings_json = ? WHERE id = ?",
                     (name, json.dumps(settings), dashboard_id))
        conn.execute("UPDATE photos SET filename = ? WHERE id = ?", (name, photo["id"]))
    _refresh_async(t, settings)   # a new location needs data before the next pull
    return back(request)


@router.post("/dashboard/{dashboard_id}/fetch")
def dashboard_fetch(request: Request, dashboard_id: int):
    with db.tx() as conn:
        dash, _ = _load(conn, dashboard_id)
    t = dashboards.get(dash["type"])
    entry = t.refresh(dashboards.settings_of(dash))
    if entry.get("error"):
        return back(request, error=f"Fetch failed: {entry['error']}")
    return back(request)


@router.post("/dashboard/{dashboard_id}/delete")
def dashboard_delete(dashboard_id: int):
    with db.tx() as conn:
        _, photo = _load(conn, dashboard_id)
        conn.execute("DELETE FROM photos WHERE id = ?", (photo["id"],))
        conn.execute("DELETE FROM dashboards WHERE id = ?", (dashboard_id,))
    return RedirectResponse("/sources/dashboards", status_code=303)


@router.get("/ui/dashboard/{dashboard_id}/preview/{device_id}")
def dashboard_preview(request: Request, dashboard_id: int, device_id: str):
    """The dashboard as this frame's panel will show it. With live=1 the query
    string carries unsaved form settings (the edit page's live preview)."""
    dev = device_or_404(device_id)
    with db.tx() as conn:
        dash, photo = _load(conn, dashboard_id)
        battery = db.state(conn, dev.id)["battery"]
    t = dashboards.get(dash["type"])
    settings = dashboards.settings_of(dash)
    if request.query_params.get("live"):
        settings = {**settings, **t.coerce(request.query_params)}
    try:
        _, model, _, _ = prepare.dashboard_model(dev, photo, battery, settings, dash)
        img = prepare.render_dashboard(dev, dash, settings, model)
    except NotImplementedError as e:
        raise HTTPException(404, str(e))
    buf = io.BytesIO()
    pipelines.get(dev.pipeline).rendered_preview(img, dev).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})
