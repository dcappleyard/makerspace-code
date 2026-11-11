#!/usr/bin/env python3
"""Bloomin8 frame tool: probe status and (re)arm pull mode for every Bloomin8
frame in a devices.yaml -- a small local web page, or the command line.

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

    .venv/bin/python bloomin8_tool.py [--devices path/to/devices.yaml]    # opens a page in the browser
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
import sys
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


def mask(d):
    """Hide all but the last 4 chars of tokens, so the output is safe to paste."""
    if isinstance(d, dict):
        return {k: (f"…{str(v)[-4:]}" if k == "token" and v else mask(v)) for k, v in d.items()}
    return d


def probe_details(st: dict) -> list[str]:
    """The requests a probe sent (as curl commands) and what came back."""
    lines = []
    for url, resp in (st.get("raw") or {}).items():
        lines.append(f"$ curl -s {url}")
        lines.append(json.dumps(mask(resp)) if resp is not None else f"  -> {st.get('error', 'no answer')}")
    if st.get("frame_time"):
        mac = time.time()
        fmt = "%Y-%m-%d %H:%M:%S %Z"
        lines.append(f"frame clock {datetime.fromtimestamp(st['frame_time']).astimezone():{fmt}}  "
                     f"(UTC {datetime.fromtimestamp(st['frame_time'], timezone.utc):%H:%M:%S})")
        lines.append(f"Mac clock   {datetime.fromtimestamp(mac).astimezone():{fmt}}  "
                     f"(UTC {datetime.fromtimestamp(mac, timezone.utc):%H:%M:%S})  -> skew {skew_text(st['skew'])} "
                     f"({st['skew']:+.0f} s)")
    return lines


def probe(frame: Frame, timeout: float = 4) -> dict:
    """Current state, or {'error': ...}. Doesn't change anything."""
    if not frame.ip:
        return {"error": "no frame_ip in devices.yaml"}
    base = f"http://{frame.ip}"
    try:
        info = call("GET", f"{base}/deviceInfo", timeout=timeout)
        ps = call("GET", f"{base}/upstream/pull_settings", timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return {"error": f"no answer ({getattr(e, 'reason', e)}) -- asleep, or wrong IP?",
                "raw": {f"{base}/deviceInfo": None}}
    frame_time = ps.get("time") or info.get("time")
    raw = {f"{base}/deviceInfo": info, f"{base}/upstream/pull_settings": ps}
    return {
        "raw": raw,
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


def pull_off(frame: Frame, log=print) -> dict:
    """Turn pull mode off (keeping the URL and token) so the frame stops calling
    the server; it keeps showing its current image. Pull now turns it back on."""
    if not frame.ip:
        log(f"{frame.id}: no frame_ip in devices.yaml")
        return {"error": "no frame_ip in devices.yaml"}
    st = probe(frame)
    if "error" in st:
        log(f"{frame.id}: {st['error']} -- wake it first")
        return st
    body = {"upstream_on": False, "upstream_url": st.get("url") or (frame.server_url or "").rstrip("/"),
            "token": frame.token}
    try:
        call("PUT", f"http://{frame.ip}/upstream/pull_settings", body)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        log(f"{frame.id}: request failed: {getattr(e, 'reason', e)}")
        return probe(frame)
    after = probe(frame)
    if "error" not in after:
        log(f"{frame.id}: pull {'OFF -- it will stop calling the server' if not after['pull'] else 'still ON (check the log)'}")
    return after


def reboot(frame: Frame, log=print, wait_s: int = 120) -> dict:
    """POST /reboot (a restart is when the frame is most likely to resync its
    clock), then wait for it to come back and return a fresh probe."""
    if not frame.ip:
        log(f"{frame.id}: no frame_ip in devices.yaml")
        return {"error": "no frame_ip in devices.yaml"}
    before = probe(frame)
    if "error" in before:
        log(f"{frame.id}: {before['error']} -- wake it first")
        return before
    try:
        call("POST", f"http://{frame.ip}/reboot", timeout=6)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        log(f"{frame.id}: reboot request: {getattr(e, 'reason', e)} (it may have dropped the connection while restarting)")
    log(f"{frame.id}: reboot sent (clock was {skew_text(before['skew'])}); watching for it to go down")
    t0 = time.time()
    went_down = False
    while time.time() - t0 < 45:              # a real restart drops it off the network
        time.sleep(1)
        if "error" in probe(frame, timeout=2):
            went_down = True
            break
    if not went_down:
        log(f"{frame.id}: still answering after 45 s -- it did NOT reboot (ignored the command?)")
        return probe(frame)
    log(f"{frame.id}: went down after {time.time() - t0:.0f}s; waiting up to {wait_s}s for it to come back")
    deadline = time.time() + wait_s
    st = probe(frame)
    while "error" in st and time.time() < deadline:
        time.sleep(3)
        st = probe(frame)
    if "error" in st:
        log(f"{frame.id}: didn't come back within {wait_s}s -- it may have gone to sleep; probe it later")
    else:
        log(f"{frame.id}: back up after {time.time() - t0:.0f}s -- clock {skew_text(before['skew'])} -> "
            f"{skew_text(st['skew'])} ({before['skew']:+.0f} s -> {st['skew']:+.0f} s)")
    return st


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
            if args.verbose:
                print("\n".join("    " + x for x in probe_details(st)) + "\n")
        elif args.cmd == "off":
            st = pull_off(f)
            rc |= 1 if "error" in st or st.get("pull") else 0
        elif args.cmd == "reboot":
            st = reboot(f)
            rc |= 1 if "error" in st else 0
        else:
            rc |= 0 if pull_now(f, single_image=not args.keep_local_playback) else 1
    return rc


# --- window (a local web page: the macOS system Tk draws blank windows) ---------

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Bloomin8 frames</title>
<style>
 body{font:14px -apple-system,system-ui,sans-serif;margin:16px;color:#222;background:#fff}
 table{border-collapse:collapse;margin:8px 0}th,td{padding:4px 10px;text-align:left;border-bottom:1px solid #ddd}
 th{background:#f3f3f3}td.err{color:#b00}.muted{color:#777}button{margin-right:6px}
 #log{font:12px Menlo,monospace;background:#f7f7f7;padding:8px;white-space:pre-wrap;min-height:6em}
 input.path{width:32em}
</style></head><body>
<h2>Bloomin8 frames</h2>
<form onsubmit="openFile();return false">devices.yaml: <input class="path" id="path"> <button>Load</button></form>
<table><thead><tr><th><input type="checkbox" id="all" onchange="document.querySelectorAll('.pick').forEach(b=>b.checked=this.checked)"></th>
<th>Frame</th><th>IP</th><th>Battery</th><th>Mode</th><th>Pull</th><th>Next wake</th><th>Clock</th><th>Status</th></tr></thead>
<tbody id="rows"></tbody></table>
<p><button onclick="act('probe')">Probe</button><button onclick="act('pull')">Pull now</button><button onclick="if(confirm('Turn pull OFF on the selected frame(s)? They keep their current image until Pull now. (nothing ticked = all)'))act('off')">Pull off</button><button onclick="if(confirm('Reboot the selected frame(s)? (nothing ticked = all)'))act('reboot')">Reboot</button>
<label><input type="checkbox" id="single" checked> also switch to single-image mode</label>
<span class="muted">(nothing ticked = all frames; wake a sleeping frame first -- Pull now waits up to 60 s)</span></p>
<div id="log"></div>
<script>
let frames=[];
const $=id=>document.getElementById(id);
function log(lines){const l=$('log');lines.forEach(x=>l.textContent+=new Date().toLocaleTimeString()+'  '+x+'\\n');}
function row(f){
  let tr=$('r-'+f.id);
  if(!tr){tr=document.createElement('tr');tr.id='r-'+f.id;$('rows').appendChild(tr);}
  const s=f.st||{}, was=tr.querySelector('.pick')?.checked?' checked':'';
  tr.innerHTML=`<td><input type="checkbox" class="pick" value="${f.id}"${was}></td><td>${f.name}</td><td>${f.ip||'(no frame_ip)'}</td>`+
   `<td>${s.battery??''}${s.battery!=null?'%':''}</td><td>${s.mode??''}</td><td>${'pull' in s?(s.pull?'on':'OFF'):''}</td>`+
   `<td>${s.next_text??''}</td><td>${s.skew_text??''}</td><td class="${s.error?'err':''}">${f.status||s.error||''}</td>`;
}
async function api(path,body){const r=await fetch(path,{method:'POST',body:JSON.stringify(body||{})});return r.json();}
async function load(){const d=await api('/api/frames');$('path').value=d.path||'';$('rows').innerHTML='';frames=d.frames;
  frames.forEach(row);log(d.messages);if(frames.length)act('probe',frames.map(f=>f.id));}
async function openFile(){const d=await api('/api/open',{path:$('path').value});log(d.messages);if(d.ok)load();}
function chosen(){const t=[...document.querySelectorAll('.pick:checked')].map(b=>b.value);return t.length?t:frames.map(f=>f.id);}
async function act(what,ids){
  ids=ids||chosen();
  await Promise.all(ids.map(async id=>{
    const f=frames.find(x=>x.id==id);f.status={pull:'arming pull (waits up to 60 s)…',reboot:'rebooting (waits up to 2 min)…',off:'turning pull off…'}[what]||'probing…';row(f);
    const d=await api('/api/'+what,{id,single:$('single').checked});
    f.st=d.st;f.status=d.status;row(f);log(d.messages||[]);
  }));
}
load();
</script></body></html>"""


def _state(st: dict) -> dict:
    out = {k: v for k, v in st.items() if k != "raw"}
    if "next" in st:
        out["next_text"] = local(st["next"]) if st["next"] else "—"
    if "skew" in st:
        out["skew_text"] = skew_text(st["skew"])
    return out


def gui(devices_path: Path | None, port: int = 0) -> None:
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {"path": devices_path}

    def frames() -> tuple[list[Frame], list[str]]:
        p = state["path"]
        if not p or not p.exists():
            return [], ["no devices.yaml -- enter its path above and Load"]
        try:
            fs = load_frames(p)
        except Exception as e:  # malformed yaml, missing keys
            return [], [f"can't read {p}: {e}"]
        msgs = []
        if not fs:
            msgs.append("no Bloomin8 frames (protocol: bloomin8) in that file")
        elif any(not f.server_url for f in fs):
            msgs.append("add a top-level server_url: to devices.yaml (the server as frames reach it)")
        return fs, msgs

    def handle(path: str, body: dict) -> dict:
        if path == "/api/open":
            p = Path(str(body.get("path", ""))).expanduser()
            if not p.exists():
                return {"ok": False, "messages": [f"not found: {p}"]}
            state["path"] = p
            remember_devices_file(p)
            return {"ok": True, "messages": [f"loaded {p}"]}
        fs, msgs = frames()
        if path == "/api/frames":
            return {"path": str(state["path"] or ""), "messages": msgs,
                    "frames": [{"id": f.id, "name": f.name, "ip": f.ip} for f in fs]}
        f = next((x for x in fs if x.id == body.get("id")), None)
        if not f:
            return {"st": {"error": "unknown frame"}, "status": ""}
        if path == "/api/probe":
            st = probe(f)
            return {"st": _state(st), "messages": [f"{f.id}: probe"] + probe_details(st),
                    "status": "" if "error" in st else f"checked {datetime.now():%H:%M:%S}"}
        if path == "/api/off":
            lines = []
            st = pull_off(f, log=lines.append)
            return {"st": _state(st), "messages": lines + probe_details(st),
                    "status": st.get("error", "") or ("pull off" if not st.get("pull") else "pull still ON")}
        if path == "/api/reboot":
            lines = []
            st = reboot(f, log=lines.append)
            return {"st": _state(st), "messages": lines + probe_details(st),
                    "status": "" if "error" in st else f"rebooted {datetime.now():%H:%M:%S}"}
        if path == "/api/pull":
            lines: list[str] = []
            ok = pull_now(f, single_image=bool(body.get("single", True)), log=lines.append)
            return {"st": _state(probe(f)), "messages": lines,
                    "status": f"armed -- pulls in ~{PULL_LEAD_S}s" if ok else "pull NOT armed (see log)"}
        return {"error": "unknown"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, data: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", PAGE.encode())
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            self._send(200, "application/json", json.dumps(handle(self.path, body)).encode())

        def log_message(self, *a):  # keep the terminal quiet
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Bloomin8 frames: {url}  (Ctrl-C to quit)")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--devices", help="path to devices.yaml (remembered once used)")
    ap.add_argument("--port", type=int, default=0, help="port for the page (default: any free one)")
    sub = ap.add_subparsers(dest="cmd")
    p_status = sub.add_parser("status", help="probe frames (default: all)")
    p_status.add_argument("ids", nargs="*")
    p_status.add_argument("-v", "--verbose", action="store_true", help="show the requests (as curl) and raw replies")
    p_off = sub.add_parser("off", help="turn pull mode off (frame keeps its image; 'pull' turns it back on)")
    p_off.add_argument("ids", nargs="+")
    p_reboot = sub.add_parser("reboot", help="restart frames (a chance to resync the clock), then re-probe")
    p_reboot.add_argument("ids", nargs="+")
    p_pull = sub.add_parser("pull", help="arm pull mode with a pull in ~90s")
    p_pull.add_argument("ids", nargs="+")
    p_pull.add_argument("--keep-local-playback", action="store_true", help="don't switch to single-image mode")
    args = ap.parse_args()

    path = find_devices_file(args.devices)
    if not args.cmd:
        gui(path, args.port)
        return
    if not path or not path.exists():
        sys.exit("no devices.yaml found -- pass --devices path/to/devices.yaml")
    remember_devices_file(path)
    sys.exit(cli(args, load_frames(path)))


if __name__ == "__main__":
    main()
