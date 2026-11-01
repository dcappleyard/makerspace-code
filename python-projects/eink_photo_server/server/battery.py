"""Battery CSV logs pushed by a folder source's device (the photobooth).

Stored as <DATA_DIR>/battery/<source_id>/<log_id>.csv. The device appends by
byte offset (see protocols/source_upload.py); this module stores, summarises and
charts them.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg

LOG_ID_RE = re.compile(r"[0-9a-f]{8,16}")
MIN_EPOCH = 1735689600   # 2025-01-01; anything below means the clock wasn't set


def log_dir(source_id: str) -> Path:
    return cfg.DATA_DIR / "battery" / source_id


def log_path(source_id: str, log_id: str) -> Path:
    if not LOG_ID_RE.fullmatch(log_id):
        raise ValueError("bad log id")
    return log_dir(source_id) / f"{log_id}.csv"


def append(source_id: str, log_id: str, offset: int, body: bytes) -> tuple[bool, int]:
    """Idempotent append. Returns (ok, length); ok False means offset > length."""
    path = log_path(source_id, log_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    length = path.stat().st_size if path.exists() else 0
    if offset > length:
        return False, length
    new = body[length - offset:]
    if new:
        with open(path, "ab") as f:
            f.write(new)
        length += len(new)
    return True, length


def _rows(path: Path) -> list[dict]:
    text = path.read_bytes().decode("utf-8", "replace")
    return [r for r in csv.DictReader(io.StringIO(text)) if r.get("epoch") is not None]


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def list_logs(source_id: str) -> list[dict]:
    """Newest first (by file mtime)."""
    d = log_dir(source_id)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not LOG_ID_RE.fullmatch(p.stem):
            continue
        rows = _rows(p)
        out.append({
            "id": p.stem, "size": p.stat().st_size, "rows": len(rows),
            "first": rows[0].get("local_time", "") if rows else "",
            "last": rows[-1].get("local_time", "") if rows else "",
            "last_mv": _int(rows[-1].get("battery_mv"), None) if rows else None,
        })
    return out


def delete(source_id: str, log_id: str) -> None:
    log_path(source_id, log_id).unlink(missing_ok=True)


def chart_svg(source_id: str, log_id: str, tz) -> str:
    """Single-series line of battery_mv (V) over time; boot rows marked."""
    pts = []
    for r in _rows(log_path(source_id, log_id)):
        ep, mv = _int(r.get("epoch")), _int(r.get("battery_mv"))
        if ep >= MIN_EPOCH and mv > 0:
            pts.append((ep, mv / 1000.0, r.get("event", "") == "boot"))
    title = "Battery voltage (battery_mv)"
    if len(pts) < 2:
        return ('<p class="muted">Not enough rows with a clock to chart yet '
                '(need 2+ with a valid epoch).</p>')
    W, H, L, R, T, B = 720, 260, 48, 12, 28, 30
    x0, x1 = pts[0][0], pts[-1][0]
    lo, hi = min(p[1] for p in pts), max(p[1] for p in pts)
    lo, hi = (lo - 0.05, hi + 0.05) if hi - lo < 0.1 else (lo, hi)
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    sx = lambda e: L + (e - x0) / (x1 - x0 or 1) * (W - L - R)
    sy = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    g = []
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="var(--line)" stroke-width="1"/>'
                 f'<text x="{L - 6}" y="{sy(v) + 4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{v:.2f}</text>')
    for i in range(5):
        e = x0 + (x1 - x0) * i / 4
        lbl = datetime.fromtimestamp(e, tz).strftime("%b %d %H:%M" if x1 - x0 > 86400 else "%H:%M")
        anc = "start" if i == 0 else "end" if i == 4 else "middle"
        g.append(f'<text x="{sx(e):.1f}" y="{H - 10}" text-anchor="{anc}" font-size="11" fill="var(--muted)">{lbl}</text>')
    line = " ".join(f"{sx(e):.1f},{sy(v):.1f}" for e, v, _ in pts)
    boots = "".join(f'<circle cx="{sx(e):.1f}" cy="{sy(v):.1f}" r="3.5" fill="var(--warn)"/>' for e, v, b in pts if b)
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px" role="img" aria-label="{title}">'
            f'<text x="{L}" y="16" font-size="13" font-weight="600" fill="var(--ink)">{title}</text>'
            f'<text x="{W - R}" y="16" text-anchor="end" font-size="11" fill="var(--warn)">● boot</text>'
            f'<text x="10" y="{(T + H - B) / 2:.0f}" font-size="11" fill="var(--muted)" '
            f'transform="rotate(-90 10 {(T + H - B) / 2:.0f})" text-anchor="middle">V</text>'
            + "".join(g) +
            f'<polyline points="{line}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>'
            + boots + '</svg>')
