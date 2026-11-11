"""DDP sender for WLED realtime ("Receive UDP realtime" must be enabled in WLED).

One packet per frame: 10-byte header + RGB bytes. 200 px = 600 bytes, well
under one MTU, so no fragmentation across packets is needed.
"""
import socket
import struct
import threading
import time

DDP_PORT = 4048
FLAG_V1_PUSH = 0x41      # version 1 + PUSH (display this frame now)
TYPE_RGB = 0x01
DEST_DEFAULT = 1
MAX_DATA = 1440          # DDP's usual per-packet data limit (480 RGB px)


class DDPSender:
    def __init__(self, host, port=DDP_PORT):
        # Resolve once (mDNS lookups per packet would be slow).
        self.addr = (socket.gethostbyname(host), port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0

    def send(self, data):
        """Send one frame. `data` is bytes-like RGB, 3 bytes per pixel
        (a numpy uint8 array works via bytes(arr) / arr.tobytes())."""
        data = bytes(data)
        if len(data) > MAX_DATA:
            raise ValueError(f"frame is {len(data)} bytes; split into multiple packets above {MAX_DATA}")
        self.seq = self.seq % 15 + 1          # 1..15; 0 means "sequence unused"
        header = struct.pack("!BBBBIH", FLAG_V1_PUSH, self.seq, TYPE_RGB,
                             DEST_DEFAULT, 0, len(data))
        self.sock.sendto(header + data, self.addr)

    def close(self):
        self.sock.close()


class Streamer(threading.Thread):
    """Calls `source()` at `fps` and sends what it returns. Keeps WLED in
    realtime mode until stopped; WLED reverts ~2.5 s after the last packet."""

    def __init__(self, sender, source, fps=40):
        super().__init__(daemon=True)
        self.sender, self.source, self.period = sender, source, 1.0 / fps
        self._halt = threading.Event()
        self.error = None

    def run(self):
        nxt = time.monotonic()
        try:
            while not self._halt.is_set():
                frame = self.source()
                if frame is not None:             # None = send nothing (e.g. a WLED preset is running)
                    self.sender.send(frame)
                nxt += self.period
                delay = nxt - time.monotonic()
                if delay > 0:
                    self._halt.wait(delay)
                else:
                    nxt = time.monotonic()    # fell behind; don't try to catch up
        except Exception as e:                # surface to the main thread
            self.error = e

    def stop(self):
        self._halt.set()
        self.join(timeout=1)
