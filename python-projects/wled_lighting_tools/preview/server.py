#!/usr/bin/env python3
"""Browser preview: a stand-in for the Dig-Uno.

Listens for DDP on UDP (like WLED) and shows the frames on a 3D view of the
sculpture built from pixels.csv. Point anything that speaks DDP at this
machine instead of the controller:

    python3 preview/server.py                     # http://localhost:8048
    python3 testpattern.py --host 127.0.0.1 parts

The page can also run a show from shows/ locally (no DDP), re-importing the
show file whenever it's saved, for a quick edit -> look loop.

The DDP side is stdlib only; local shows need numpy. The page draws with a
plain <canvas>, so it works offline.
"""
import argparse
import base64
import json
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pixel_map  # noqa: E402

REALTIME_TIMEOUT = 2.5    # WLED's default; after this the real sculpture reverts


class FrameBuffer:
    """Latest DDP frame plus receive stats, shared between threads."""

    def __init__(self, n):
        self.n = n
        self.buf = bytearray(3 * n)
        self.version = 0
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.last_rx = 0.0
        self.sender = None
        self.packets = 0
        self.frames = 0
        self.seq_gaps = 0
        self._last_seq = 0
        self._fps_window = []
        self.source = "ddp"        # "ddp" = show what arrives on UDP; "show" = local show
        self.show = None
        self.show_error = None

    def _commit(self):
        """Frame complete (lock held)."""
        self.version += 1
        self.frames += 1
        now = self.last_rx
        self._fps_window.append(now)
        while self._fps_window and now - self._fps_window[0] > 1.0:
            self._fps_window.pop(0)
        self.cond.notify_all()

    def ddp_packet(self, pkt, addr):
        if len(pkt) < 10:
            return
        flags, seq, _dtype, _dest, offset, length = struct.unpack("!BBBBIH", pkt[:10])
        hdr = 14 if flags & 0x10 else 10          # timecode flag adds 4 bytes
        data = pkt[hdr:hdr + length]
        with self.cond:
            self.packets += 1
            if self.source != "ddp":               # a local show has the display
                return
            self.sender = addr[0]
            self.last_rx = time.monotonic()
            if seq and self._last_seq and seq != self._last_seq % 15 + 1:
                self.seq_gaps += 1
            self._last_seq = seq
            end = min(len(self.buf), offset + len(data))
            if offset < end:
                self.buf[offset:end] = data[:end - offset]
            if flags & 0x01:                       # PUSH: frame complete
                self._commit()

    def local_frame(self, data, error):
        with self.cond:
            self.buf[:] = data
            self.sender = f"show '{self.show}'"
            self.last_rx = time.monotonic()
            self.show_error = error
            self._commit()

    def status(self):
        with self.lock:
            age = time.monotonic() - self.last_rx if self.last_rx else None
            live = age is not None and age < REALTIME_TIMEOUT
            return {
                "live": live,
                "age": None if age is None else round(age, 1),
                "sender": self.sender,
                "fps": len(self._fps_window) if live else 0,
                "frames": self.frames,
                "seq_gaps": self.seq_gaps,
                "source": self.source,
                "show": self.show,
                "error": self.show_error,
            }


class LocalShow(threading.Thread):
    """Renders a show from shows/ straight into the frame buffer (no DDP),
    re-importing the show file whenever it changes."""

    def __init__(self, fb, name, fps=40):
        super().__init__(daemon=True)
        import shows                      # numpy needed only for local shows
        from layout import Layout
        self.fb, self.period = fb, 1.0 / fps
        self.player = shows.Player(name, Layout.load(), reload=True)
        self.halt = threading.Event()

    def run(self):
        nxt = time.monotonic()
        while not self.halt.is_set():
            f = self.player.frame()
            self.fb.local_frame(f, self.player.error)
            nxt += self.period
            delay = nxt - time.monotonic()
            if delay > 0:
                self.halt.wait(delay)
            else:
                nxt = time.monotonic()


class SourceControl:
    def __init__(self, fb):
        self.fb, self.thread, self.lock = fb, None, threading.Lock()

    def set(self, source, name=None):
        with self.lock:
            if self.thread:
                self.thread.halt.set()
                self.thread.join(timeout=1)
                self.thread = None
            with self.fb.lock:
                self.fb.source, self.fb.show, self.fb.show_error = source, name, None
                self.fb.last_rx = 0.0
                self.fb._fps_window.clear()
            if source == "show":
                self.thread = LocalShow(self.fb, name)
                self.thread.start()

    def restart(self):
        if self.thread:
            self.thread.player.restart()


def udp_loop(fb, bind, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind, port))
    while True:
        pkt, addr = sock.recvfrom(2048)
        fb.ddp_packet(pkt, addr)


def list_shows():
    try:
        import shows
    except ImportError as e:              # numpy missing: DDP mode still works
        return {"error": f"local shows unavailable: {e}", "shows": []}
    out = []
    for name in shows.available():
        try:
            desc = getattr(shows.load(name), "DESCRIPTION", "")
        except Exception as e:
            desc = f"(import error: {e})"
        out.append({"name": name, "description": desc})
    return {"shows": out}


def make_handler(fb, pixels, control):
    pixels_json = json.dumps(pixels).encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                # read per request so page edits show on reload
                self._send((HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/pixels.json":
                self._send(pixels_json, "application/json")
            elif self.path == "/stream":
                self.stream()
            elif self.path == "/shows":
                self._send(json.dumps(list_shows()).encode(), "application/json")
            else:
                self.send_error(404)

        def do_POST(self):
            """/source {"source": "ddp"} or {"source": "show", "name": ...};
            /restart restarts the local show's clock."""
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path == "/source":
                    src = body.get("source")
                    if src == "ddp":
                        control.set("ddp")
                    elif src == "show" and body.get("name") in [s["name"] for s in list_shows()["shows"]]:
                        control.set("show", body["name"])
                    else:
                        raise ValueError(f"bad source: {body}")
                elif self.path == "/restart":
                    control.restart()
                else:
                    return self.send_error(404)
                self._send(json.dumps(fb.status()).encode(), "application/json")
            except Exception as e:
                msg = json.dumps({"error": f"{type(e).__name__}: {e}"}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        def stream(self):
            """Server-sent events: frames as they arrive (max ~60/s), status every 0.5 s."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            seen = -1
            next_status = 0.0
            try:
                while True:
                    with fb.cond:
                        if fb.version == seen:
                            fb.cond.wait(timeout=0.5)
                        frame = bytes(fb.buf) if fb.version != seen else None
                        seen = fb.version
                    msg = {}
                    if frame is not None:
                        msg["f"] = base64.b64encode(frame).decode()
                    now = time.monotonic()
                    if now >= next_status:
                        msg["st"] = fb.status()
                        next_status = now + 0.5
                    if msg:
                        self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                        self.wfile.flush()
                    time.sleep(1 / 60)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pixels", default=str(HERE.parent / "pixels.csv"))
    ap.add_argument("--http-port", type=int, default=8048)
    ap.add_argument("--ddp-port", type=int, default=4048)
    ap.add_argument("--bind", default="0.0.0.0",
                    help="address for both listeners (0.0.0.0 lets the Pi stream to this machine)")
    ap.add_argument("--show", help="start with this local show instead of DDP input")
    a = ap.parse_args()

    pixels = pixel_map.load(a.pixels)
    fb = FrameBuffer(len(pixels))
    control = SourceControl(fb)
    if a.show:
        control.set("show", a.show)
    threading.Thread(target=udp_loop, args=(fb, a.bind, a.ddp_port), daemon=True).start()
    httpd = ThreadingHTTPServer((a.bind, a.http_port), make_handler(fb, pixels, control))
    httpd.daemon_threads = True
    print(f"DDP on udp/{a.ddp_port}, preview at http://localhost:{a.http_port}  ({len(pixels)} px)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
