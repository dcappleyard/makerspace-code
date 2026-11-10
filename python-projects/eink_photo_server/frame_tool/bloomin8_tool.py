#!/usr/bin/env python3
"""Bloomin8 frame tool: probe status and (re)arm pull mode for every Bloomin8
frame in a devices.yaml -- a small Tk window, or the command line.

Runs on a machine that can reach the frames' network (on this setup, the Mac;
the Pi can't reach the IoT VLAN). Reads the server's devices.yaml -- keep a copy
on the Mac -- using two optional keys the server itself ignores:

    server_url: http://192.168.30.10:8080     # top level: the server as frames reach it
    devices:
      - id: living_room_73
        protocol: bloomin8
        token: ...                            # already there
        frame_ip: 192.168.20.219              # add this per Bloomin8 frame
        # server_url: ...                     # optional per-frame override

    .venv/bin/python bloomin8_tool.py [--devices path/to/devices.yaml]    # window
    .venv/bin/python bloomin8_tool.py status [frame-id ...]               # command line
    .venv/bin/python bloomin8_tool.py pull <frame-id> [...]

"Pull now" sets pull mode (this server, the frame's token) with the first wake
90 s ahead **by the frame's own clock** -- so it works even when that clock has
drifted -- and switches the frame to single-image mode so its own slideshow
can't overwrite pulled images. There is no API to set a Bloomin8's clock; the
tool shows how far off it is instead (Clock skew).

APIs: https://github.com/ARPOBOT-BLOOMIN8/eink_canvas_home_assistant_component
(docs/Schedule_Pull_API.md, openapi.yaml).
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

PREFS = Path.home() / ".bloomin8_tool.json"
DEFAULT_PATHS = [Path("data/devices.yaml"), Path("../data/devices.yaml"), Path.home() / "eink-data-copy/devices.yaml"]
PULL_LEAD_S = 90          # first wake this far ahead of the frame's clock (spec: >= 1 min)
WAIT_FOR_WAKE_S = 60      # how long "Pull now" waits for a sleeping frame to answer
PLAY_MODES = {0: "single image", 1: "gallery", 2: "playlist"}


# --- frames and devices.yaml --------------------------------------------------

@dataclass
class Frame:
    id: str
    name: str
    ip: str | None
    token: str
    server_url: str | None


def load_frames(path: Path) -> list[Frame]:
    raw = yaml.safe_load(path.read_text()) or {}
    top_server = raw.get("server_url")
    frames = []
    for d in raw.get("devices") or []:
        if str(d.get("protocol")) != "bloomin8":
            continue
        frames.append(Frame(id=str(d["id"]), name=str(d.get("name", d["id"])), ip=d.get("frame_ip"),
                            token=str(d.get("token", "")), server_url=d.get("server_url") or top_server))
    return frames


def find_devices_file(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser()
    try:
        saved = json.loads(PREFS.read_text()).get("devices")
        if saved and Path(saved).exists():
            return Path(saved)
    except (OSError, ValueError):
        pass
    if os.environ.get("BLOOMIN8_DEVICES"):
        return Path(os.environ["BLOOMIN8_DEVICES"]).expanduser()
    return next((p.resolve() for p in DEFAULT_PATHS if p.exists()), None)


def remember_devices_file(path: Path) -> None:
    try:
        PREFS.write_text(json.dumps({"devices": str(path.resolve())}))
    except OSError:
        pass


# --- frame API ----------------------------------------------------------------

def call(method: str, url: str, body: dict | None = None, timeout: float = 6) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode(errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


def local(epoch) -> str:
    return datetime.fromtimestamp(int(epoch)).strftime("%a %H:%M:%S") if epoch else "—"


def skew_text(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    if abs(s) < 5:
        return "ok"
    sign = "+" if s > 0 else "-"
    s = abs(s)
    return f"{sign}{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{sign}{s // 60}m{s % 60:02d}s"


def probe(frame: Frame, timeout: float = 4) -> dict:
    """Current state, or {'error': ...}. Doesn't change anything."""
    if not frame.ip:
        return {"error": "no frame_ip in devices.yaml"}
    base = f"http://{frame.ip}"
    try:
        info = call("GET", f"{base}/deviceInfo", timeout=timeout)
        ps = call("GET", f"{base}/upstream/pull_settings", timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return {"error": f"no answer ({getattr(e, 'reason', e)}) -- asleep, or wrong IP?"}
    frame_time = ps.get("time") or info.get("time")
    return {
        "battery": info.get("battery"),
        "mode": PLAY_MODES.get(info.get("play_type"), info.get("play_type")),
        "play_type": info.get("play_type"),
        "image": info.get("image"),
        "pull": ps.get("upstream_on"),
        "url": ps.get("upstream_url"),
        "next": ps.get("next_cron_time"),
        "frame_time": frame_time,
        "skew": (frame_time - time.time()) if frame_time else None,
        "name": info.get("name"),
    }


def pull_now(frame: Frame, single_image: bool = True, log=print, wait_s: int = WAIT_FOR_WAKE_S) -> bool:
    """Arm pull mode with the first wake PULL_LEAD_S ahead on the frame's clock."""
    if not frame.ip or not frame.server_url or not frame.token:
        log(f"{frame.id}: needs frame_ip, server_url and token in devices.yaml")
        return False
    deadline = time.time() + wait_s
    st = probe(frame)
    if "error" in st:
        log(f"{frame.id}: waiting up to {wait_s}s -- wake the frame now (button or Bloomin8 app)")
        while "error" in st and time.time() < deadline:
            time.sleep(2)
            st = probe(frame)
        if "error" in st:
            log(f"{frame.id}: {st['error']}")
            return False
    base = f"http://{frame.ip}"
    # The frame judges "future" by its own clock, so schedule against that.
    when = int((st["frame_time"] or time.time()) + PULL_LEAD_S)
    cron = datetime.fromtimestamp(when, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {"upstream_on": True, "upstream_url": frame.server_url.rstrip("/"), "token": frame.token, "cron_time": cron}
    try:
        call("PUT", f"{base}/upstream/pull_settings", body)
        if single_image and st.get("play_type") != 0:
            show = {"play_type": 0, **({"image": st["image"]} if st.get("image") else {})}
            call("POST", f"{base}/show", show)
            log(f"{frame.id}: switched to single-image mode (was {st['mode']})")
        after = call("GET", f"{base}/upstream/pull_settings")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        log(f"{frame.id}: request failed: {getattr(e, 'reason', e)}")
        return False
    ok = after.get("upstream_on") and after.get("upstream_url") == body["upstream_url"]
    log(f"{frame.id}: {'armed' if ok else 'CHECK'} -- pull {'on' if after.get('upstream_on') else 'OFF'} -> "
        f"{after.get('upstream_url')}, pulls in ~{PULL_LEAD_S}s (frame clock {skew_text(st['skew'])})")
    return bool(ok)


# --- command line ---------------------------------------------------------------

def cli(args, frames: list[Frame]) -> int:
    chosen = [f for f in frames if not args.ids or f.id in args.ids]
    missing = set(args.ids or []) - {f.id for f in frames}
    if missing:
        print(f"not Bloomin8 frames in devices.yaml: {', '.join(sorted(missing))}")
    rc = 0
    for f in chosen:
        if args.cmd == "status":
            st = probe(f)
            if "error" in st:
                print(f"{f.id:20} {f.ip or '-':16} {st['error']}")
            else:
                print(f"{f.id:20} {f.ip:16} battery {st['battery']}%  {st['mode']}  pull "
                      f"{'ON' if st['pull'] else 'OFF'} -> {st['url'] or '-'}  next {local(st['next'])}  "
                      f"clock {skew_text(st['skew'])}")
        else:
            rc |= 0 if pull_now(f, single_image=not args.keep_local_playback) else 1
    return rc


# --- window ---------------------------------------------------------------------

def gui(devices_path: Path | None) -> None:
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title("Bloomin8 frames")
    events: queue.Queue = queue.Queue()
    state = {"path": devices_path, "frames": []}

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    path_var = tk.StringVar()
    ttk.Label(top, text="devices.yaml:").pack(side="left")
    ttk.Label(top, textvariable=path_var, foreground="#555").pack(side="left", padx=6)

    cols = ("frame", "ip", "battery", "mode", "pull", "next", "clock", "status")
    heads = ("Frame", "IP", "Battery", "Mode", "Pull", "Next wake", "Clock", "Status")
    widths = (150, 120, 60, 90, 60, 100, 70, 260)
    tree = ttk.Treeview(root, columns=cols, show="headings", height=6, selectmode="extended")
    for c, h, w in zip(cols, heads, widths):
        tree.heading(c, text=h)
        tree.column(c, width=w, anchor="w")
    tree.pack(fill="both", expand=True, padx=8)

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill="x")
    single = tk.BooleanVar(value=True)
    logbox = tk.Text(root, height=8, width=110, state="disabled", font=("Menlo", 11))
    logbox.pack(fill="both", padx=8, pady=(0, 8))

    def log(msg):
        events.put(("log", f"{datetime.now():%H:%M:%S}  {msg}"))

    def selected() -> list[Frame]:
        ids = tree.selection() or tree.get_children()   # nothing selected = all
        return [f for f in state["frames"] if f.id in ids]

    def set_row(f: Frame, st: dict | None = None, status: str = ""):
        st = st or {}
        values = (f.name, f.ip or "(no frame_ip)",
                  f"{st['battery']}%" if st.get("battery") is not None else "",
                  st.get("mode", "") or "", ("on" if st.get("pull") else "OFF") if "pull" in st else "",
                  local(st.get("next")) if st.get("next") else "", skew_text(st.get("skew")) if "skew" in st else "",
                  status or st.get("error", ""))
        events.put(("row", f.id, values))

    def load(path: Path | None):
        state["path"] = path
        tree.delete(*tree.get_children())
        state["frames"] = []
        if not path or not path.exists():
            path_var.set("(none -- click Open…)")
            return
        try:
            state["frames"] = load_frames(path)
        except Exception as e:  # malformed yaml, missing keys
            log(f"can't read {path}: {e}")
        path_var.set(str(path))
        remember_devices_file(path)
        for f in state["frames"]:
            tree.insert("", "end", iid=f.id, values=(f.name, f.ip or "(no frame_ip)", "", "", "", "", "", ""))
        if not state["frames"]:
            log("no Bloomin8 frames (protocol: bloomin8) in that file")
        elif any(not f.server_url for f in state["frames"]):
            log("add a top-level server_url: to devices.yaml (the server as frames reach it)")

    def run(job, frames):
        def worker():
            for f in frames:
                job(f)
        threading.Thread(target=worker, daemon=True).start()

    def do_probe(f: Frame):
        set_row(f, status="probing…")
        st = probe(f)
        set_row(f, st, "" if "error" in st else f"checked {datetime.now():%H:%M:%S}")

    def do_pull(f: Frame):
        set_row(f, status="arming pull…")
        ok = pull_now(f, single_image=single.get(), log=log)
        st = probe(f)
        set_row(f, st, "armed -- pulls in ~90s" if ok else "pull NOT armed (see log)")

    def choose_file():
        p = filedialog.askopenfilename(title="devices.yaml", filetypes=[("YAML", "*.yaml *.yml"), ("All", "*")])
        if p:
            load(Path(p))

    ttk.Button(top, text="Open…", command=choose_file).pack(side="right")
    ttk.Button(top, text="Reload", command=lambda: load(state["path"])).pack(side="right", padx=4)
    ttk.Button(btns, text="Probe", command=lambda: run(do_probe, selected())).pack(side="left")
    ttk.Button(btns, text="Pull now", command=lambda: run(do_pull, selected())).pack(side="left", padx=6)
    ttk.Checkbutton(btns, text="also switch to single-image mode", variable=single).pack(side="left", padx=6)
    ttk.Label(btns, text="(no selection = all frames; wake a sleeping frame first)", foreground="#777").pack(side="left")

    def pump():
        try:
            while True:
                ev = events.get_nowait()
                if ev[0] == "log":
                    logbox.configure(state="normal")
                    logbox.insert("end", ev[1] + "\n")
                    logbox.see("end")
                    logbox.configure(state="disabled")
                elif ev[0] == "row" and tree.exists(ev[1]):
                    tree.item(ev[1], values=ev[2])
        except queue.Empty:
            pass
        root.after(150, pump)

    load(devices_path)
    pump()
    if state["frames"]:
        run(do_probe, state["frames"])   # quick look at start-up
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--devices", help="path to devices.yaml (remembered once used)")
    sub = ap.add_subparsers(dest="cmd")
    p_status = sub.add_parser("status", help="probe frames (default: all)")
    p_status.add_argument("ids", nargs="*")
    p_pull = sub.add_parser("pull", help="arm pull mode with a pull in ~90s")
    p_pull.add_argument("ids", nargs="+")
    p_pull.add_argument("--keep-local-playback", action="store_true", help="don't switch to single-image mode")
    args = ap.parse_args()

    path = find_devices_file(args.devices)
    if not args.cmd:
        gui(path)
        return
    if not path or not path.exists():
        sys.exit("no devices.yaml found -- pass --devices path/to/devices.yaml")
    remember_devices_file(path)
    sys.exit(cli(args, load_frames(path)))


if __name__ == "__main__":
    main()
