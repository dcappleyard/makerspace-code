"""Admin UI: the Playlists section -- curated, ordered selections of photos from
any source, shared by however many frames' schedule blocks point at them."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import config as cfg
from .. import db, sources
from .common import FormError, back, require_admin, templates

router = APIRouter(dependencies=[Depends(require_admin)])


def _playlist_or_404(conn, playlist_id: int):
    pl = db.playlist(conn, playlist_id)
    if not pl:
        raise HTTPException(404, "unknown playlist")
    return pl


def _users(conn, playlist_id: int) -> list:
    """Frames whose schedule blocks draw on this playlist."""
    ids = [r["device_id"] for r in conn.execute(
        "SELECT DISTINCT device_id FROM schedule_blocks WHERE source = ?", (f"playlist:{playlist_id}",))]
    return [d for d in cfg.config.devices.values() if d.id in ids]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/playlists")
def playlists_page(request: Request):
    with db.tx() as conn:
        cards = []
        for pl in conn.execute("SELECT * FROM playlists ORDER BY name COLLATE NOCASE, id").fetchall():
            items = db.playlist_items(conn, pl["id"])
            cards.append({"pl": pl, "count": len(items), "thumbs": [i["photo_id"] for i in items[:6]],
                          "users": _users(conn, pl["id"])})
    return templates.TemplateResponse(request, "playlists.html",
                                      {"section": "playlists", "page": "playlists", "cards": cards})


@router.get("/playlist/{playlist_id}")
def playlist_page(request: Request, playlist_id: int):
    with db.tx() as conn:
        pl = _playlist_or_404(conn, playlist_id)
        items = db.playlist_items(conn, playlist_id)
        photo_by_id = {p["id"]: p for p in conn.execute("SELECT * FROM photos")}
        users = _users(conn, playlist_id)
    return templates.TemplateResponse(request, "playlist.html", {
        "section": "playlists", "page": f"playlist:{playlist_id}", "pl": pl, "items": items,
        "photo_by_id": photo_by_id, "users": users, "devices": list(cfg.config.devices.values()),
        "source_names": dict(sources.raw_sources()),
    })


@router.post("/ui/playlists/new")
def playlist_new(name: str = Form(...)):
    name = " ".join(name.split()) or "Untitled"
    with db.tx() as conn:
        pid = conn.execute("INSERT INTO playlists (name, created_at) VALUES (?, ?)", (name, _now())).lastrowid
    return RedirectResponse(f"/playlist/{pid}", status_code=303)


@router.post("/ui/playlist/{playlist_id}/rename")
def playlist_rename(request: Request, playlist_id: int, name: str = Form(...)):
    name = " ".join(name.split())
    if not name:
        raise FormError("a playlist needs a name")
    with db.tx() as conn:
        _playlist_or_404(conn, playlist_id)
        conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id))
    return back(request)


@router.post("/ui/playlist/{playlist_id}/duplicate")
def playlist_duplicate(playlist_id: int):
    with db.tx() as conn:
        pl = _playlist_or_404(conn, playlist_id)
        new_id = conn.execute("INSERT INTO playlists (name, created_at) VALUES (?, ?)",
                              (f"{pl['name']} (copy)", _now())).lastrowid
        conn.execute("INSERT INTO playlist_items (device_id, photo_id, position, playlist_id) "
                     "SELECT '', photo_id, position, ? FROM playlist_items WHERE playlist_id = ?",
                     (new_id, playlist_id))
    return RedirectResponse(f"/playlist/{new_id}", status_code=303)


@router.post("/ui/playlist/{playlist_id}/delete")
def playlist_delete(request: Request, playlist_id: int):
    with db.tx() as conn:
        pl = _playlist_or_404(conn, playlist_id)
        users = _users(conn, playlist_id)
        if users:
            raise FormError(f"\"{pl['name']}\" is used by {', '.join(d.name for d in users)} -- "
                            "change those frames' schedule blocks first")
        conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
        conn.execute("DELETE FROM source_cursors WHERE source = ?", (f"playlist:{playlist_id}",))
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    return RedirectResponse("/playlists", status_code=303)


@router.post("/ui/playlist/{playlist_id}/add")
def playlist_add(request: Request, playlist_id: int, photo_id: int = Form(...)):
    with db.tx() as conn:
        _playlist_or_404(conn, playlist_id)
        if not db.photo(conn, photo_id):
            raise HTTPException(404, "unknown photo")
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_items WHERE playlist_id = ?",
                           (playlist_id,)).fetchone()[0]
        conn.execute("INSERT INTO playlist_items (device_id, photo_id, position, playlist_id) VALUES ('', ?, ?, ?)",
                     (photo_id, pos, playlist_id))
    return back(request)


@router.post("/ui/playlist-item/{item_id}/move")
def item_move(request: Request, item_id: int, direction: str = Form(...)):
    with db.tx() as conn:
        it = conn.execute("SELECT * FROM playlist_items WHERE id = ?", (item_id,)).fetchone()
        if not it:
            raise HTTPException(404)
        ids = [i["id"] for i in db.playlist_items(conn, it["playlist_id"])]
        i = ids.index(item_id)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        for pos, iid in enumerate(ids):
            conn.execute("UPDATE playlist_items SET position = ? WHERE id = ?", (pos, iid))
    return back(request)


@router.post("/ui/playlist-item/{item_id}/remove")
def item_remove(request: Request, item_id: int):
    with db.tx() as conn:
        conn.execute("DELETE FROM playlist_items WHERE id = ?", (item_id,))
    return back(request)
