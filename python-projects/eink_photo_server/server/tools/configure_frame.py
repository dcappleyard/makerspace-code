"""Point a Bloomin8 frame at this server (one-time setup, run from the LAN).

    python -m server.tools.configure_frame <device_id> <frame-ip> --server http://<pi-ip>:8080

1. PUTs /upstream/pull_settings with the device's token from devices.yaml and a
   first wake a couple of minutes from now.
2. Switches the frame to single-image mode (POST /show play_type 0), keeping
   whatever it currently shows. A frame left in gallery/playlist mode keeps
   running its own slideshow timer, overwriting pulled images (and draining the
   battery). Skip with --keep-local-playback.

The frame must be awake (e.g. just woken via its button/app) to accept requests.
If the server can't reach the frame's VLAN, use --print-curl and run the printed
commands from a machine that can (e.g. the workstation the Bloomin8 app runs on).
"""
from __future__ import annotations

import argparse
import json
import shlex
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from .. import config as cfg

# Turns a /deviceInfo response into the /show body for single-image mode.
SHOW_BODY_PY = ('import json,sys; i=json.load(sys.stdin); '
                'print(json.dumps({"play_type": 0, **({"image": i["image"]} if i.get("image") else {})}))')


def _call(method: str, url: str, body: dict | None = None) -> str:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode(errors="replace")


def single_image_body(info: dict) -> dict:
    body = {"play_type": 0}
    if info.get("image"):
        body["image"] = info["image"]
    return body


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("device_id")
    ap.add_argument("frame_ip")
    ap.add_argument("--server", default=cfg.PUBLIC_BASE_URL, help="base URL the frame should pull from")
    ap.add_argument("--first-wake-minutes", type=int, default=2)
    ap.add_argument("--keep-local-playback", action="store_true",
                    help="don't switch the frame to single-image mode")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print-curl", action="store_true",
                    help="print equivalent curl commands (includes the token) instead of sending")
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
    base = f"http://{args.frame_ip}"
    if args.print_curl:
        # cron_time is fixed when printed; run these within a minute or so.
        print("# 1. point the frame at this server")
        print(f"curl -s -m 10 -X PUT {base}/upstream/pull_settings -H 'Content-Type: application/json' "
              f"-d {shlex.quote(json.dumps(body))}")
        if not args.keep_local_playback:
            print("# 2. stop the frame's own slideshow (single-image mode, keeps the current image)")
            print(f"curl -s -m 5 {base}/deviceInfo | python3 -c {shlex.quote(SHOW_BODY_PY)} | "
                  f"curl -s -m 10 -X POST {base}/show -H 'Content-Type: application/json' --data @-")
        return

    print(f"PUT {base}/upstream/pull_settings\n{json.dumps({**body, 'token': '***'}, indent=2)}")
    if args.dry_run:
        return
    try:
        print(_call("PUT", f"{base}/upstream/pull_settings", body))
        if args.keep_local_playback:
            return
        info = json.loads(_call("GET", f"{base}/deviceInfo"))
        print(f"frame play_type={info.get('play_type')} (0 single, 1 gallery, 2 playlist), "
              f"playlist={info.get('playlist')!r}, gallery={info.get('gallery')!r}")
        if info.get("play_type") != 0:
            show = single_image_body(info)
            print(f"POST {base}/show {json.dumps(show)}\n{_call('POST', f'{base}/show', show)}")
        else:
            print("already in single-image mode")
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(
            f"couldn't reach the frame at {args.frame_ip}: {getattr(e, 'reason', e)}\n"
            "Is it awake? Can this machine reach its VLAN (firewall)? "
            "If not, rerun with --print-curl and send it from a machine that can."
        )


if __name__ == "__main__":
    main()
