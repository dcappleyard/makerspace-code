"""Point a Bloomin8 frame at this server (one-time setup, run from the LAN).

    python -m server.tools.configure_frame <device_id> <frame-ip> --server http://<pi-ip>:8080

Reads the device's token from devices.yaml and PUTs /upstream/pull_settings on
the frame, with the first wake a couple of minutes from now. The frame must be
awake (e.g. just woken via its button/app) to accept the request.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timedelta, timezone

from .. import config as cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("device_id")
    ap.add_argument("frame_ip")
    ap.add_argument("--server", default=cfg.PUBLIC_BASE_URL, help="base URL the frame should pull from")
    ap.add_argument("--first-wake-minutes", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dev = cfg.config.devices.get(args.device_id)
    if not dev:
        raise SystemExit(f"unknown device {args.device_id!r}; have {', '.join(cfg.config.devices)}")
    if not args.server:
        raise SystemExit("--server is required (or set PUBLIC_BASE_URL)")

    first = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=args.first_wake_minutes)
    body = {
        "upstream_on": True,
        "upstream_url": args.server.rstrip("/"),
        "token": dev.token,
        "cron_time": first.isoformat().replace("+00:00", "Z"),
    }
    url = f"http://{args.frame_ip}/upstream/pull_settings"
    print(f"PUT {url}\n{json.dumps({**body, 'token': '***'}, indent=2)}")
    if args.dry_run:
        return
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="PUT",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(resp.status, resp.read().decode(errors="replace"))


if __name__ == "__main__":
    main()
