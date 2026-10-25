"""Admin UI: one page per frame -- status, block schedule, playlist, wake timing, log."""
from __future__ import annotations

import csv
import io
import json
import statistics

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from .. import config as cfg
from .. import db, pipelines, schedule, sources
from .common import FormError, back, device_or_404, require_admin, templates

router = APIRouter(dependencies=[Depends(require_admin)])

LOG_ROWS = 200
DRIFT_SAMPLES = 10
MIN_INTERVAL = 5  # minutes


def drift_stats(conn, device_id: str) -> dict | None:
    """Wake drift (actual pull - scheduled cron_time) over recent pulls.
    Prefers pulls whose cron_time we sent; falls back to any reported one."""
    rows = conn.execute("SELECT data_json FROM events WHERE device_id = ? AND kind = 'pull' ORDER BY id DESC LIMIT 100",
                        (device_id,)).fetchall()
    data = [json.loads(r["data_json"]) for r in rows]
    with_drift = [d for d in data if d.get("drift_s") is not None]
    ours = [d["drift_s"] for d in with_drift if d.get("scheduled_by_server")][:DRIFT_SAMPLES]
    samples = ours or [d["drift_s"] for d in with_drift][:DRIFT_SAMPLES]
    if not samples:
        return None
    median = int(statistics.median(samples))
    return {"n": len(samples), "median": median, "min": min(samples), "max": max(samples),
            "suggested": -median, "ours_only": bool(ours)}


def _events(conn, device_id: str, limit: int | None = LOG_ROWS) -> list[dict]:
    sql = "SELECT * FROM events WHERE device_id = ? ORDER BY id DESC" + (f" LIMIT {int(limit)}" if limit else "")
    return [{**dict(r), "data": json.loads(r["data_json"])} for r in conn.execute(sql, (device_id,))]


@router.get("/frames")
def frames_page(request: Request):
    with db.tx() as conn:
        photo_by_id = {p["id"]: p for p in conn.execute("SELECT * FROM photos")}
        frames = []
        for d in cfg.config.devices.values():
            blocks = schedule.get_blocks(conn, d)
            used = sorted({sources.label(conn, b.source) for b in blocks if b.selection != "specific"})
            frames.append({"dev": d, "state": db.state(conn, d.id), "sources_used": used})
    return templates.TemplateResponse(request, "frames.html", {
        "section": "frames", "page": "frames", "frames": frames, "photo_by_id": photo_by_id,
        "tz": str(cfg.config.tz), "pipelines": pipelines.names(),
    })


@router.get("/frame/{device_id}")
def frame_page(request: Request, device_id: str):
    dev = device_or_404(device_id)
    now = schedule.utc_now()
    with db.tx() as conn:
        st = db.state(conn, dev.id)
        photos = conn.execute("SELECT * FROM photos ORDER BY id DESC").fetchall()
        blocks = schedule.get_blocks(conn, dev)
        ctx = {
            "section": "frames",
            "page": dev.id,
            "dev": dev,
            "state": st,
            "photos": photos,
            "photo_by_id": {p["id"]: p for p in photos},
            "source_choices": sources.choices(conn),
            "block_text": {b.key: b.describe(conn) for b in blocks},
            "blocks": blocks,
            "using_fallback": bool(blocks) and blocks[0].from_yaml,
            "current": schedule.current(blocks, now),
            "plan": schedule.plan_day(conn, dev, now),
            "events": _events(conn, dev.id),
            "drift": drift_stats(conn, dev.id),
            "params": {**pipelines.get(dev.pipeline).default_params, **dev.tuning},
            "selections": schedule.SELECTIONS,
        }
    return templates.TemplateResponse(request, "frame.html", ctx)


# --- status / playlist ------------------------------------------------------

@router.post("/ui/device/{device_id}/pause")
def device_pause(request: Request, device_id: str):
    device_or_404(device_id)
    with db.tx() as conn:
        db.state(conn, device_id)
        conn.execute("UPDATE device_state SET paused = 1 - paused WHERE device_id = ?", (device_id,))
    return back(request)


@router.post("/ui/device/{device_id}/queue")
def device_queue(request: Request, device_id: str, photo_id: int | None = Form(None)):
    """Serve this photo on the device's next pull (one shot). Empty photo_id clears it."""
    device_or_404(device_id)
    with db.tx() as conn:
        db.state(conn, device_id)
        conn.execute("UPDATE device_state SET queued_photo_id = ? WHERE device_id = ?", (photo_id, device_id))
    return back(request)


# --- schedule blocks --------------------------------------------------------

def _block_fields(conn, device_id, start: str, source: str, selection: str, interval: str, photo_id: str,
                  exclude_id: int | None = None) -> tuple:
    """Validated (start, source, selection, interval or None, photo_id, hold)."""
    try:
        start_t = cfg.parse_hhmm(start)
    except (ValueError, AttributeError):
        raise FormError("start time must be HH:MM")
    if selection not in schedule.SELECTIONS:
        raise FormError("unknown selection")
    pid = None
    if selection == "specific":
        pid = int(photo_id) if photo_id else None
        if not pid or not db.photo(conn, pid):
            raise FormError("pick the photo to show")
        source = source or "library"
    elif source not in dict(sources.choices(conn)):
        raise FormError("pick a source")
    iv = None
    if interval.strip():
        try:
            iv = int(interval)
        except ValueError:
            raise FormError("every N minutes must be a whole number (leave it blank to hold)")
        if iv < MIN_INTERVAL:
            raise FormError(f"every N minutes must be at least {MIN_INTERVAL}")
    start_s = f"{start_t:%H:%M}"
    clash = conn.execute("SELECT id FROM schedule_blocks WHERE device_id = ? AND start_time = ? AND id IS NOT ?",
                         (device_id, start_s, exclude_id)).fetchone()
    if clash:
        raise FormError(f"another block already starts at {start_s}")
    return start_s, source, selection, iv, pid, int(iv is None)


_BLOCK_COLS = "start_time, source, selection, interval_minutes, photo_id, hold"


@router.post("/frame/{device_id}/blocks/add")
def block_add(request: Request, device_id: str, start: str = Form(...), source: str = Form(""),
              selection: str = Form(...), interval: str = Form(""), photo_id: str = Form("")):
    device_or_404(device_id)
    with db.tx() as conn:
        f = _block_fields(conn, device_id, start, source, selection, interval, photo_id)
        conn.execute(f"INSERT INTO schedule_blocks (device_id, kind, {_BLOCK_COLS}) VALUES (?,?,?,?,?,?,?,?)",
                     (device_id, f[2], *f))
    return back(request)


@router.post("/frame/{device_id}/blocks/{block_id}/update")
def block_update(request: Request, device_id: str, block_id: int, start: str = Form(...), source: str = Form(""),
                 selection: str = Form(...), interval: str = Form(""), photo_id: str = Form("")):
    device_or_404(device_id)
    with db.tx() as conn:
        f = _block_fields(conn, device_id, start, source, selection, interval, photo_id, exclude_id=block_id)
        conn.execute("UPDATE schedule_blocks SET kind = ?, start_time = ?, source = ?, selection = ?, "
                     "interval_minutes = ?, photo_id = ?, hold = ? WHERE id = ? AND device_id = ?",
                     (f[2], *f, block_id, device_id))
    return back(request)


@router.post("/frame/{device_id}/blocks/{block_id}/delete")
def block_delete(request: Request, device_id: str, block_id: int):
    with db.tx() as conn:
        conn.execute("DELETE FROM schedule_blocks WHERE id = ? AND device_id = ?", (block_id, device_id))
    return back(request)


@router.post("/frame/{device_id}/blocks/from-defaults")
def blocks_from_defaults(request: Request, device_id: str):
    """Turn the devices.yaml fallback into editable blocks."""
    dev = device_or_404(device_id)
    with db.tx() as conn:
        if not conn.execute("SELECT 1 FROM schedule_blocks WHERE device_id = ?", (dev.id,)).fetchone():
            for b in schedule.fallback_blocks(dev):
                conn.execute(f"INSERT INTO schedule_blocks (device_id, kind, {_BLOCK_COLS}) VALUES (?,?,?,?,?,?,?,?)",
                             (dev.id, b.selection, f"{b.start:%H:%M}", b.source, b.selection, b.interval,
                              b.photo_id, int(b.hold)))
    return back(request)


# --- wake timing ------------------------------------------------------------

@router.post("/frame/{device_id}/offset")
def offset_set(request: Request, device_id: str, minutes: float = Form(...)):
    device_or_404(device_id)
    with db.tx() as conn:
        db.state(conn, device_id)
        conn.execute("UPDATE device_state SET wake_offset_s = ? WHERE device_id = ?", (round(minutes * 60), device_id))
    return back(request)


@router.post("/frame/{device_id}/offset/apply")
def offset_apply(request: Request, device_id: str):
    device_or_404(device_id)
    with db.tx() as conn:
        stats = drift_stats(conn, device_id)
        if stats:
            db.state(conn, device_id)
            conn.execute("UPDATE device_state SET wake_offset_s = ? WHERE device_id = ?",
                         (stats["suggested"], device_id))
    return back(request)


# --- log --------------------------------------------------------------------

@router.post("/frame/{device_id}/log/clear")
def log_clear(request: Request, device_id: str):
    with db.tx() as conn:
        conn.execute("DELETE FROM events WHERE device_id = ?", (device_id,))
    return back(request)


@router.get("/frame/{device_id}/log.csv")
def log_csv(device_id: str):
    device_or_404(device_id)
    with db.tx() as conn:
        events = list(reversed(_events(conn, device_id, limit=None)))
    keys = sorted({k for e in events for k in e["data"]})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["at", "kind", "summary", *keys])
    for e in events:
        w.writerow([e["at"], e["kind"], e["summary"], *(e["data"].get(k, "") for k in keys)])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{device_id}-log.csv"'})
