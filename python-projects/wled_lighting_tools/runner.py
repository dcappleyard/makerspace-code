#!/usr/bin/env python3
"""Show runner: streams the rotation to WLED during the scheduled windows.

    python3 runner.py                     # run per config.yaml (what systemd starts)
    python3 runner.py --schedule          # print the next 7 days of windows and exit
    python3 runner.py --force-on          # ignore the schedule, run the rotation now
    python3 runner.py --preview --force-on   # DDP to the local preview, no WLED API calls

At window start: {"on": true, "bri": N}, then stream the rotation. Rotation
entries are shows (DDP) or "wled:<preset>" (DDP stops, WLED runs the preset).
At window end: stop streaming, {"on": false}. If the runner stops mid-window,
WLED falls back to its own effect after its realtime timeout (by design).
"""
import argparse
import datetime as dt
import logging
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import shows
from layout import Layout
from schedule import Schedule
from testpattern import load_config
from wled.api import WLED
from wled.ddp import DDPSender, Streamer

HERE = Path(__file__).resolve().parent
log = logging.getLogger("runner")

TICK = 0.25              # control loop period, s
RETRY = 30.0             # retry interval for failed WLED/network actions, s


@dataclass
class Entry:
    kind: str            # "show" or "preset"
    name: str            # show name, or preset id as str
    minutes: float

    def __str__(self):
        return self.name if self.kind == "show" else f"wled:{self.name}"


def parse_rotation(sc):
    default = float(sc.get("minutes_each", 10))
    known = set(shows.available())
    out = []
    for item in sc.get("rotation", []):
        minutes = default
        if isinstance(item, dict):
            minutes = float(item.get("minutes", default))
            item = f"wled:{item['wled']}" if "wled" in item else item.get("show")
        item = str(item).strip()
        if item.startswith("wled:"):
            pid = item[5:].strip()
            if not pid.isdigit():
                log.error("rotation: bad preset %r, skipped", item)
                continue
            out.append(Entry("preset", pid, minutes))
        elif item in known:
            out.append(Entry("show", item, minutes))
        else:
            log.error("rotation: no show %r in shows/, skipped (have: %s)", item, ", ".join(sorted(known)))
    return out


class Mixer:
    """Frame source for the Streamer: the current show, crossfading from the
    previous one. Returns None while a WLED preset runs (nothing is sent)."""

    def __init__(self, n):
        self.n = n
        self.lock = threading.Lock()
        self.cur = self.prev = None
        self.fade_start, self.fade_s = 0.0, 0.0
        self._logged_error = None

    def switch(self, player, fade_s=0.0):
        with self.lock:
            self.prev = self.cur if (player is not None and fade_s > 0) else None
            self.cur = player
            self.fade_start, self.fade_s = time.monotonic(), fade_s

    def __call__(self):
        with self.lock:
            cur, prev = self.cur, self.prev
            if cur is None:
                return None
            f = cur.frame()
            self._log_error(cur)
            if prev is not None:
                a = (time.monotonic() - self.fade_start) / self.fade_s
                if a >= 1:
                    self.prev = None
                else:
                    x = np.frombuffer(f, np.uint8).astype(np.float32)
                    y = np.frombuffer(prev.frame(), np.uint8).astype(np.float32)
                    f = (y + (x - y) * a + 0.5).astype(np.uint8).tobytes()
            return f

    def _log_error(self, player):
        if player.error != self._logged_error:
            self._logged_error = player.error
            if player.error:
                log.warning("show %s: %s", player.name, player.error)


class Fanout:
    """Send to several DDP targets; network errors are logged, not fatal."""

    def __init__(self, senders):
        self.senders = senders
        self._last_err = 0.0

    def send(self, data):
        for s in self.senders:
            try:
                s.send(data)
            except OSError as e:
                if time.monotonic() - self._last_err > RETRY:
                    self._last_err = time.monotonic()
                    log.warning("DDP send to %s failed: %s", s.addr[0], e)

    def close(self):
        for s in self.senders:
            s.close()


class Runner:
    def __init__(self, cfg, args):
        self.cfg, self.args = cfg, args
        wc = cfg.get("wled", {})
        sc = cfg.get("schedule", {})
        self.schedule = Schedule.from_config(cfg)
        self.rotation = parse_rotation(sc)
        if not self.rotation:
            sys.exit("rotation is empty (check schedule.rotation in config.yaml)")
        self.shuffle = bool(sc.get("shuffle", False))
        self.fade_s = float(sc.get("transition_seconds", 2))
        self.bri = sc.get("brightness")
        self.scale = max(0.0, min(1.0, float(sc.get("scale", 1.0))))
        self.reassert = bool(sc.get("reassert_on", False))
        self.fps = float(wc.get("fps", 40))
        self.port = int(wc.get("ddp_port", 4048))

        self.preview = args.preview
        host = "127.0.0.1" if args.preview else (args.host or wc.get("host"))
        if not host:
            sys.exit("No WLED host: set wled.host in config.yaml, or use --host / --preview")
        self.targets = [host] + list(args.also)
        api_port = int(wc.get("api_port", 80))
        self.api = None if args.preview else WLED(host if api_port == 80 else f"{host}:{api_port}")

        self.layout = Layout.load()
        self.mixer = Mixer(self.layout.n)
        self.streamer = None
        self.fanout = None
        self.window = None           # (start, end) while on
        self.order = []
        self.pos = -1
        self.entry = None
        self.entry_end = 0.0
        self.pending = {}            # action -> (retry time, desc, state)
        self.pending_start = 0.0     # retry time after a failed window start
        self.next_reassert = 0.0
        self.stopping = threading.Event()

    # ------------------------------------------------------------ WLED API
    def api_call(self, action, desc, **state):
        """POST state; on failure, remember it for retry. Returns success."""
        if self.api is None:
            log.info("[preview] would send %s %s", desc, state)
            self.pending.pop(action, None)
            return True
        try:
            self.api.set_state(**state)
            log.info("WLED %s %s", desc, state)
            self.pending.pop(action, None)
            return True
        except Exception as e:
            log.warning("WLED %s failed (%s); retrying in %ds", desc, e, RETRY)
            self.pending[action] = (time.monotonic() + RETRY, desc, state)
            return False

    def retry_pending(self):
        now = time.monotonic()
        for action, (when, desc, state) in list(self.pending.items()):
            if now >= when:
                self.api_call(action, desc, **state)

    def maybe_reassert(self):
        if not self.reassert or self.api is None or time.monotonic() < self.next_reassert:
            return
        self.next_reassert = time.monotonic() + 60
        try:
            if not self.api.state().get("on", True):
                log.info("WLED was off mid-window; turning it back on")
                self.api_call("on", "on", **self._on_state())
        except Exception as e:
            log.debug("reassert check failed: %s", e)

    def _on_state(self):
        return {"on": True, **({"bri": int(self.bri)} if self.bri is not None else {})}

    # ------------------------------------------------------------ windows
    def start_window(self, win):
        try:
            senders = [DDPSender(h, self.port) for h in self.targets]
        except OSError as e:          # mDNS/DNS not resolving yet
            log.warning("can't resolve %s (%s); retrying in %ds", self.targets, e, RETRY)
            self.pending_start = time.monotonic() + RETRY
            return
        self.window = win
        log.info("window on: %s -> %s", fmt(win[0]), fmt(win[1]))
        self.pending.pop("off", None)
        self.api_call("on", "on", **self._on_state())
        self.fanout = Fanout(senders)
        self.streamer = Streamer(self.fanout, self.mixer, self.fps)
        self.streamer.start()
        self.next_entry(first=True)

    def end_window(self):
        log.info("window off")
        self.mixer.switch(None)
        self.stop_streaming()
        self.window = None
        self.entry = None
        self.pending.pop("on", None)
        self.pending.pop("preset", None)
        self.api_call("off", "off", on=False)

    def stop_streaming(self):
        if self.streamer:
            self.streamer.stop()
            self.streamer = None
        if self.fanout:
            self.fanout.close()
            self.fanout = None

    # ------------------------------------------------------------ rotation
    def next_entry(self, first=False):
        prev = self.entry
        for _ in range(len(self.rotation)):
            self.pos += 1
            if self.pos >= len(self.order):
                self.order = list(self.rotation)
                if self.shuffle:
                    random.shuffle(self.order)
                    if prev and len(self.order) > 1 and self.order[0] == prev:
                        self.order.append(self.order.pop(0))   # don't repeat across cycles
                self.pos = 0
            e = self.order[self.pos]
            if e is prev and not first and len(self.rotation) > 1:
                continue
            if self.play(e, prev):
                self.entry = e
                self.entry_end = time.monotonic() + 60 * e.minutes
                return
        log.error("no rotation entry could start; blanking for a minute")
        self.mixer.switch(None)
        self.entry = None
        self.entry_end = time.monotonic() + 60

    def play(self, e, prev):
        if e is prev:          # single-entry rotation: just keep going
            return True
        if e.kind == "show":
            try:
                player = shows.Player(e.name, self.layout, scale=self.scale)
            except Exception as ex:
                log.error("show %s failed to load: %s", e.name, ex)
                return False
            fade = self.fade_s if (prev is not None and prev.kind == "show") else 0.0
            self.mixer.switch(player, fade)
            self.pending.pop("preset", None)
            log.info("playing %s for %g min%s", e, e.minutes, f" (crossfade {fade:g}s)" if fade else "")
            return True
        # WLED preset: stop sending DDP, then leave realtime mode and apply the preset
        self.mixer.switch(None)
        time.sleep(2 / self.fps)
        log.info("playing %s for %g min", e, e.minutes)
        self.api_call("preset", f"preset {e.name}", live=False, ps=int(e.name))
        return True

    # ------------------------------------------------------------ main loop
    def run(self):
        log.info("rotation: %s", ", ".join(map(str, self.rotation)))
        log.info("targets: %s%s", ", ".join(self.targets), " (preview: no WLED API)" if self.preview else "")
        if not self.args.force_on:
            nxt = self.schedule.active() or self.schedule.next_start()
            if nxt:
                log.info("current/next window: %s -> %s", fmt(nxt[0]), fmt(nxt[1]))
        while not self.stopping.is_set():
            if self.args.force_on:
                win = (self.schedule.now(), None)
            else:
                win = self.schedule.active()
            if win and self.window is None and time.monotonic() >= self.pending_start:
                self.start_window(win)
            elif not win and self.window is not None:
                self.end_window()
            if self.window is not None:
                if self.streamer and self.streamer.error:
                    log.error("streamer died: %s; restarting it", self.streamer.error)
                    self.streamer = Streamer(self.fanout, self.mixer, self.fps)
                    self.streamer.start()
                if time.monotonic() >= self.entry_end:
                    self.next_entry()
                self.maybe_reassert()
            self.retry_pending()
            self.stopping.wait(TICK)
        # Shutdown mid-window: just stop streaming; WLED falls back to its own effect.
        self.mixer.switch(None)
        self.stop_streaming()
        log.info("stopped")


def fmt(t):
    return t.strftime("%a %m-%d %H:%M %Z") if t else "(forced on)"


def print_schedule(cfg, days):
    s = Schedule.from_config(cfg)
    today = s.now().date()
    print(f"{s.loc.info.name} ({s.loc.info.latitude}, {s.loc.info.longitude}) {s.loc.tz.key}")
    for i in range(days):
        d = today + dt.timedelta(days=i)
        sn = s.loc.sun(d)
        wins = "  ".join(f"{a.strftime('%H:%M')}-{b.strftime('%H:%M')}" for a, b in s.intervals(d))
        print(f"  {d.strftime('%a %m-%d')}  sunrise {sn['sunrise'].strftime('%H:%M')}  "
              f"sunset {sn['sunset'].strftime('%H:%M')}   on: {wins}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--host", help="WLED host (overrides config)")
    ap.add_argument("--preview", action="store_true", help="DDP to 127.0.0.1 and skip WLED API calls")
    ap.add_argument("--also", action="append", default=[], help="additional DDP target (repeatable)")
    ap.add_argument("--force-on", action="store_true", help="ignore the schedule; run the rotation now")
    ap.add_argument("--schedule", action="store_true", help="print upcoming windows and exit")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    cfg_path = Path(a.config)
    if not cfg_path.exists():
        sys.exit(f"{cfg_path} not found (copy config.example.yaml)")
    cfg = load_config(cfg_path)
    if a.schedule:
        return print_schedule(cfg, a.days)

    r = Runner(cfg, a)
    signal.signal(signal.SIGTERM, lambda *_: r.stopping.set())
    try:
        r.run()
    except KeyboardInterrupt:
        r.stopping.set()
        r.mixer.switch(None)
        r.stop_streaming()


if __name__ == "__main__":
    main()
