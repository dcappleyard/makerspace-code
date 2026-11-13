"""Audition: play an effect or a show in the browser only (nothing goes to the
sculpture). Renders with the same effects.Player + Mixer crossfade as the
runner, on its own thread with its own players, so the real stream is
unaffected. It runs only while a page is watching: it stops 10 s after the last
/api/audition/stream client leaves.
"""
import threading
import time

import effects
from runner import Mixer

FPS = 20
IDLE_STOP_S = 10


class Auditioner:
    def __init__(self, layout):
        self.layout = layout
        self.mixer = Mixer(layout.n)
        self.lock = threading.Lock()
        self.entries, self.idx = [], -1
        self.label = None
        self.scale, self.fade_s = 1.0, 2.0
        self.seconds_each = None
        self.entry_end = 0.0
        self.error = None
        self.clients = 0
        self.last_seen = 0.0
        self.thread = None
        self.running = False

    # ---------------------------------------------------------------- control
    def start(self, entries, label, scale=1.0, fade_s=2.0, seconds_each=None):
        """Play `entries` (shows.Entry list) in order, looping. seconds_each
        overrides each entry's own minutes (handy for skimming a show)."""
        if not entries:
            raise ValueError("nothing to play")
        for e in entries:                       # surface bad options now, not mid-play
            if e.kind == "effect":
                effects.Player(e.name, self.layout, options=e.options)
        with self.lock:
            self.entries, self.idx, self.label = list(entries), -1, label
            self.scale, self.fade_s = scale, fade_s
            self.seconds_each = seconds_each
            self.last_seen = time.monotonic()
            self._advance(first=True)
            if not self.running:
                self.running = True
                self.thread = threading.Thread(target=self._loop, name="audition", daemon=True)
                self.thread.start()

    def next(self):
        with self.lock:
            if self.entries:
                self._advance()

    def stop(self):
        with self.lock:
            self.running = False
            self.entries, self.idx, self.label = [], -1, None
            self.mixer.switch(None)

    def _advance(self, first=False):
        prev = self.entries[self.idx] if (0 <= self.idx < len(self.entries) and not first) else None
        self.idx = (self.idx + 1) % len(self.entries)
        e = self.entries[self.idx]
        secs = self.seconds_each if self.seconds_each else 60 * e.minutes
        self.entry_end = time.monotonic() + secs
        self.error = None
        if e.kind == "effect":
            try:
                p = effects.Player(e.name, self.layout, scale=self.scale, options=e.options)
            except Exception as ex:
                self.error = f"{e.name}: {ex}"
                self.mixer.switch(None)
                return
            fade = self.fade_s if (prev is not None and prev.kind == "effect" and not first) else 0.0
            self.mixer.switch(p, fade)
        else:
            self.mixer.switch(None)               # a WLED preset can't be shown here

    # ---------------------------------------------------------------- loop
    def _loop(self):
        while True:
            with self.lock:
                if not self.running:
                    return
                if self.clients == 0 and time.monotonic() - self.last_seen > IDLE_STOP_S:
                    self.running = False
                    self.entries, self.idx, self.label = [], -1, None
                    self.mixer.switch(None)
                    return
                if self.entries and time.monotonic() >= self.entry_end:
                    self._advance()
                if self.mixer.cur is not None:
                    self.mixer()                  # renders into mixer.last
            time.sleep(1 / FPS)

    # ---------------------------------------------------------------- status
    def watch(self, delta):
        with self.lock:
            self.clients += delta
            self.last_seen = time.monotonic()

    def status(self):
        with self.lock:
            e = self.entries[self.idx] if 0 <= self.idx < len(self.entries) else None
            return {
                "playing": bool(self.running and e),
                "label": self.label,
                "entry": str(e) if e else None,
                "kind": e.kind if e else None,
                "index": self.idx, "count": len(self.entries),
                "remaining_s": max(0, round(self.entry_end - time.monotonic())) if e else None,
                "error": self.error or (self.mixer.cur.error if self.mixer.cur else None),
                "frame": self.mixer.last if (self.running and self.mixer.cur is not None) else None,
            }
