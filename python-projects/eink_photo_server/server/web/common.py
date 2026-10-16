"""Shared bits for the admin UI routers: auth, templates, redirects."""
from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .. import config as cfg

_basic = HTTPBasic(auto_error=False)


def require_admin(creds: HTTPBasicCredentials | None = Depends(_basic)):
    if not cfg.ADMIN_PASSWORD:
        return
    if not creds or not secrets.compare_digest(creds.password.encode(), cfg.ADMIN_PASSWORD.encode()):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _local(ts) -> str:
    if not ts:
        return "—"
    dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt.astimezone(cfg.config.tz).strftime("%a %b %d %H:%M")


def _duration(seconds) -> str:
    if seconds is None:
        return "—"
    sign = "-" if seconds < 0 else "+"
    s = abs(int(seconds))
    if s < 60:
        return f"{sign}{s}s"
    if s < 3600:
        return f"{sign}{s // 60}m{s % 60:02d}s"
    return f"{sign}{s // 3600}h{s % 3600 // 60:02d}m"


templates.env.filters["local"] = _local
templates.env.filters["duration"] = _duration
# Every page's nav lists the frames.
templates.env.globals["nav_devices"] = lambda: list(cfg.config.devices.values())


def back(request: Request, fallback: str = "/", error: str | None = None) -> RedirectResponse:
    """Redirect to the page the form was posted from (path only, same site),
    optionally carrying an error message for the page's banner."""
    ref = urlsplit(request.headers.get("referer", ""))
    path = ref.path if ref.path.startswith("/") else fallback
    query = [(k, v) for k, v in parse_qsl(ref.query) if k != "error"] if path == ref.path else []
    if error:
        query.append(("error", error))
    return RedirectResponse(path + (f"?{urlencode(query)}" if query else ""), status_code=303)


class FormError(Exception):
    """A user-fixable form problem: shown as a banner on the page it came from."""


async def form_error_handler(request: Request, exc: FormError):
    return back(request, error=str(exc))


def device_or_404(device_id: str):
    dev = cfg.config.devices.get(device_id)
    if not dev:
        raise HTTPException(404, "unknown device")
    return dev
