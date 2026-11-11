#!/usr/bin/env python3
"""Browser preview: a stand-in for the Dig-Uno.

Listens for DDP on UDP (like WLED) and shows the frames on a 3D view of the
sculpture built from pixels.csv. Point anything that speaks DDP at this
machine instead of the controller:

    python3 preview/server.py                     # http://localhost:8048
    python3 testpattern.py --host 127.0.0.1 parts

Stdlib only; the page draws with a plain <canvas>, so it works offline.
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

    def ddp_packet(self, pkt, addr):
        if len(pkt) < 10:
            return
        flags, seq, _dtype, _dest, offset, length = struct.unpack("!BBBBIH", pkt[:10])
        hdr = 14 if flags & 0x10 else 10          # timecode flag adds 4 bytes
        data = pkt[hdr:hdr + length]
        with self.cond:
            self.packets += 1
            self.sender = addr[0]
            self.last_rx = time.monotonic()
            if seq and self._last_seq and seq != self._last_seq % 15 + 1:
                self.seq_gaps += 1
            self._last_seq = seq
            end = min(len(self.buf), offset + len(data))
            if offset < end:
                self.buf[offset:end] = data[:end - offset]
            if flags & 0x01:                       # PUSH: frame complete
                self.version += 1
                self.frames += 1
                now = self.last_rx
                self._fps_window.append(now)
                while self._fps_window and now - self._fps_window[0] > 1.0:
                    self._fps_window.pop(0)
                self.cond.notify_all()

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
            }


def udp_loop(fb, bind, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind, port))
    while True:
        pkt, addr = sock.recvfrom(2048)
        fb.ddp_packet(pkt, addr)


def make_handler(fb, pixels):
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
            else:
                self.send_error(404)

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
    a = ap.parse_args()

    pixels = pixel_map.load(a.pixels)
    fb = FrameBuffer(len(pixels))
    threading.Thread(target=udp_loop, args=(fb, a.bind, a.ddp_port), daemon=True).start()
    httpd = ThreadingHTTPServer((a.bind, a.http_port), make_handler(fb, pixels))
    httpd.daemon_threads = True
    print(f"DDP on udp/{a.ddp_port}, preview at http://localhost:{a.http_port}  ({len(pixels)} px)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
