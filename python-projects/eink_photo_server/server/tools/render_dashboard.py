"""Render a dashboard for every pipeline to PNGs, without the server running.

  DATA_DIR=/tmp/wx python -m server.tools.render_dashboard --out /tmp/wx/out
  python -m server.tools.render_dashboard --set split=side_by_side --set current=0 --out out/

It fetches weather.gov into DATA_DIR/dashboards/ (or uses what's already there
with --cached), then draws the dashboard on each pipeline's surface. For each
pipeline it writes:
  <pipeline>.png       what the panel shows (rendered_preview)
  <pipeline>-sent.png  the encoded bytes decoded back, as sent (for .bin pipelines)
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# Geometry of the frames in devices.example.yaml.
DEVICES = {
    "ee04_bw1": dict(width=800, height=480, output_rotation=0, options={}),
    "ee03_gray16": dict(width=1872, height=1404, output_rotation=0, options={}),
    "bloomin8_spectra6": dict(width=800, height=480, output_rotation=90, options={}),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", default="weather")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a setting")
    ap.add_argument("--pipeline", action="append", help="only these (default: all)")
    ap.add_argument("--portrait", action="store_true", help="render 480x800 for the 800x480 panels")
    ap.add_argument("--cached", action="store_true", help="don't fetch, use DATA_DIR's cached data")
    ap.add_argument("--battery", type=int)
    ap.add_argument("--tz", default="America/Chicago")
    ap.add_argument("--out", default=".")
    a = ap.parse_args(argv)

    os.environ.setdefault("DATA_DIR", str(Path(a.out) / "data"))
    from .. import dashboards, pipelines

    t = dashboards.get(a.type)
    form = {k: v for k, v in (s.split("=", 1) for s in a.set)}
    settings = {**t.default_settings}
    for k, v in t.coerce({**{f.key: _as_form(settings.get(f.key)) for f in t.form}, **form}).items():
        settings[k] = v
    if not a.cached:
        entry = t.refresh(settings)
        if entry.get("error"):
            print("fetch failed:", entry["error"], file=sys.stderr)
    ctx = {"now": datetime.now(timezone.utc), "tz": ZoneInfo(a.tz), "battery": a.battery}
    model = t.model(settings, ctx)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in a.pipeline or pipelines.names():
        pipe = pipelines.get(name)
        geo = dict(DEVICES.get(name, dict(width=800, height=480, output_rotation=0, options={})))
        if a.portrait and geo["width"] == 800:
            geo.update(width=480, height=800, output_rotation=(geo["output_rotation"] + 90) % 360)
        dev = SimpleNamespace(id=name, **geo)
        surface = pipe.surface(dev)
        img = t.render(model, surface, settings)
        pipe.rendered_preview(img, dev).save(out / f"{name}.png")
        data = pipe.encode_rendered(img, dev)
        sent = pipe.decode(data, dev)
        if sent is not None:
            sent.save(out / f"{name}-sent.png")
        print(f"{name}: {surface.width}x{surface.height} -> {len(data)} bytes")
    return 0


def _as_form(v):
    if isinstance(v, bool):
        return "1" if v else ""
    return "" if v is None else str(v)


if __name__ == "__main__":
    raise SystemExit(main())
