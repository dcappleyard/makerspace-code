#!/usr/bin/env python3
"""Show runner: streams the rotation to WLED during the scheduled windows.

    python3 runner.py                     # run per config.yaml (what the Docker container runs)
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
import os
import queue
import random
import signal
import sys
import threading
import time
from collections import deque
from concurrent.futures import Future
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
    options: dict = None  # show options (rotation entry's options:)

    def __str__(self):
        return self.name if self.kind == "show" else f"wled:{self.name}"


def parse_rotation(sc):
    default = float(sc.get("minutes_each", 10))
    known = set(shows.available())
    out = []
    for item in sc.get("rotation", []):
        minutes, options = default, None
        if isinstance(item, dict):
            minutes = float(item.get("minutes", default))
            options = item.get("options")
            item = f"wled:{item['wled']}" if "wled" in item else item.get("show")
        item = str(item).strip()
        if item.startswith("wled:"):
            pid = item[5:].strip()
            if not pid.isdigit():
                log.error("rotation: bad preset %r, skipped", item)
                continue
            out.append(Entry("preset", pid, minutes))
        elif item in known:
            out.append(Entry("show", item, minutes, options))
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
        self.last = None             # last frame sent (bytes), for the dashboard's live view

    def switch(self, player, fade_s=0.0):
        with self.lock:
            self.prev = self.cur if (player is not None and fade_s > 0) else None
            self.cur = player
            self.fade_start, self.fade_s = time.monotonic(), fade_s
            if player is None:
                self.last = None

    def set_scale(self, scale):
        with self.lock:
            for p in (self.cur, self.prev):
                if p is not None:
                    p.scale = scale

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
            self.last = f
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


class LogBuffer(logging.Handler):
    """Keeps the last N formatted log lines for the dashboard."""

    def __init__(self, n=200):
        super().__init__()
        self.lines = deque(maxlen=n)

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
        except Exception:
            pass


def _iso(t):
    return t.isoformat() if t else None


class Runner:
    def __init__(self, cfg, args, cfg_path=None):
        self.args = args
        self.cfg_path = cfg_path
        wc = cfg.get("wled", {})
        self._load_schedule(cfg)
        if not self.rotation:
            sys.exit("rotation is empty (check schedule.rotation in config.yaml)")
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

        # Dashboard (web/app.py) plumbing. The web side only submits commands
        # and reads the status snapshot; runner state stays on the loop thread.
        self.cmds = queue.Queue()
        self._done = []              # (future, result, exception) to resolve after this tick
        self.manual = None           # (start, end): "on now" outside the schedule
        self.suppress_until = None   # "off until next window": skip windows ending by then
        self._status = {}
        self._status_lock = threading.Lock()
        self.wled_health = {"reachable": None, "error": None, "checked": None, "info": None}
        self.logbuf = None

    def _load_schedule(self, cfg):
        """Everything that comes from the schedule: section (and location:)."""
        sc = cfg.get("schedule", {})
        self.cfg = cfg
        self.schedule = Schedule.from_config(cfg)
        self.rotation = parse_rotation(sc)
        self.shuffle = bool(sc.get("shuffle", False))
        self.fade_s = float(sc.get("transition_seconds", 2))
        self.bri = sc.get("brightness")
        self.scale = max(0.0, min(1.0, float(sc.get("scale", 1.0))))
        self.reassert = bool(sc.get("reassert_on", False))

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
                player = shows.Player(e.name, self.layout, scale=self.scale, options=e.options)
            except Exception as ex:
                log.error("show %s failed to load: %s", e.name, ex)
                return False
            fade = self.fade_s if (prev is not None and prev.kind == "show") else 0.0
            self.mixer.switch(player, fade)
            self.pending.pop("preset", None)
            log.info("playing %s for %g min%s", e, e.minutes, f" (crossfade {fade:g}s)" if fade else "")
            if player.raw_opts:
                log.info("  options: %s", ", ".join(f"{k}={v}" for k, v in player.raw_opts.items()))
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
        if self.api is not None:
            threading.Thread(target=self._health_loop, name="wled-health", daemon=True).start()
        while not self.stopping.is_set():
            self.drain_commands()
            win = self.effective_window()
            if win and self.window is None and time.monotonic() >= self.pending_start:
                self.start_window(win)
            elif not win and self.window is not None:
                self.end_window()
            elif win and win[1] != self.window[1]:
                self.window = win            # e.g. a manual "on" running into a scheduled window
            if self.window is not None:
                if self.streamer and self.streamer.error:
                    log.error("streamer died: %s; restarting it", self.streamer.error)
                    self.streamer = Streamer(self.fanout, self.mixer, self.fps)
                    self.streamer.start()
                if time.monotonic() >= self.entry_end:
                    self.next_entry()
                self.maybe_reassert()
            self.retry_pending()
            self.update_status()
            self.resolve_commands()
            self.stopping.wait(TICK)
        # Shutdown mid-window: just stop streaming; WLED falls back to its own effect.
        self.mixer.switch(None)
        self.stop_streaming()
        log.info("stopped")

    def effective_window(self):
        """The window that should be on now: the schedule, adjusted by the
        dashboard's manual on/off overrides (which live in memory only)."""
        now = self.schedule.now()
        if self.args.force_on:
            return (now, None)
        win = self.schedule.active(now)
        if self.suppress_until is not None:
            if now >= self.suppress_until:
                self.suppress_until = None
            elif win and win[1] <= self.suppress_until:
                win = None
        if self.manual is not None:
            if now >= self.manual[1]:
                self.manual = None
            elif not win:
                win = self.manual
        return win

    # ------------------------------------------------------------ dashboard
    def submit(self, name, **kw):
        """Queue a command for the loop thread (called from the web thread).
        Returns a Future that resolves to a result dict or raises ValueError."""
        fut = Future()
        self.cmds.put((name, kw, fut))
        return fut

    def drain_commands(self):
        """Run queued commands. Their futures resolve at the end of the tick
        (resolve_commands), so a reply's status already reflects the command."""
        while True:
            try:
                name, kw, fut = self.cmds.get_nowait()
            except queue.Empty:
                return
            try:
                self._done.append((fut, getattr(self, f"cmd_{name}")(**kw) or {}, None))
            except Exception as e:
                if not isinstance(e, ValueError):
                    log.exception("dashboard command %s failed", name)
                self._done.append((fut, None, e))

    def resolve_commands(self):
        done, self._done = self._done, []
        for fut, res, exc in done:
            fut.set_exception(exc) if exc else fut.set_result(res)

    def cmd_skip(self):
        if self.window is None:
            raise ValueError("the sculpture is off")
        log.info("dashboard: skip")
        self.next_entry()

    def cmd_play(self, item, minutes=None, options=None):
        """Play one show (or wled:<id>) now for `minutes`, then resume the rotation."""
        minutes = float(minutes or self.cfg.get("schedule", {}).get("minutes_each", 10))
        spec = {"show": item, "minutes": minutes, **({"options": options} if options else {})}
        if str(item).startswith("wled:"):
            spec = {"wled": str(item)[5:], "minutes": minutes}
        entries = parse_rotation({"rotation": [spec]})
        if not entries:
            raise ValueError(f"unknown show or bad preset: {item}")
        e = entries[0]
        if e.kind == "show":       # surface bad options as an error, not a log line
            shows.Player(e.name, self.layout, options=e.options)
        log.info("dashboard: play %s for %g min", e, minutes)
        if self.window is None:
            self.suppress_until = None
            now = self.schedule.now()
            self.manual = (now, now + dt.timedelta(minutes=minutes))
            self.start_window(self.manual)
            if self.window is None:
                raise ValueError("couldn't start streaming (see log)")
        if not self.play(e, self.entry):
            raise ValueError(f"{e} failed to start (see log)")
        self.entry = e
        self.entry_end = time.monotonic() + 60 * minutes

    def cmd_on(self, minutes=None):
        self.suppress_until = None
        if self.args.force_on or self.schedule.active():
            log.info("dashboard: on (schedule window)")
            return {"note": "on for the scheduled window"}
        minutes = float(minutes or 60)
        now = self.schedule.now()
        self.manual = (now, now + dt.timedelta(minutes=minutes))
        log.info("dashboard: on for %g min", minutes)

    def cmd_off(self):
        if self.args.force_on:
            raise ValueError("runner was started with --force-on; stop it instead")
        self.manual = None
        win = self.schedule.active()
        if win:
            self.suppress_until = win[1]
        log.info("dashboard: off until the next window")

    def cmd_resume(self):
        """Drop manual on/off overrides and follow the schedule again."""
        self.manual = self.suppress_until = None
        log.info("dashboard: back to the schedule")

    def cmd_scale(self, value):
        v = float(value)
        if not 0.0 <= v <= 1.0:
            raise ValueError("scale must be 0..1")
        self.scale = v
        self.mixer.set_scale(v)

    def cmd_apply_config(self, cfg):
        """Adopt a new schedule: section without stopping the stream."""
        old_bri, cur = self.bri, self.entry
        self._load_schedule(cfg)
        if not self.rotation:
            raise ValueError("rotation is empty")
        self.mixer.set_scale(self.scale)
        log.info("config reloaded; rotation: %s", ", ".join(map(str, self.rotation)))
        self.order = list(self.rotation)
        if self.shuffle:
            random.shuffle(self.order)
        self.pos = -1
        if cur is not None:
            same = [i for i, e in enumerate(self.order)
                    if (e.kind, e.name, e.options) == (cur.kind, cur.name, cur.options)]
            if same:
                self.pos = same[0]       # keep playing it; the rotation continues after it
            elif self.window is not None:
                self.next_entry()
        if self.window is not None and self.bri != old_bri and self.bri is not None:
            self.api_call("on", "on", **self._on_state())

    def _health_loop(self):
        while not self.stopping.is_set():
            h = {"checked": _iso(self.schedule.now())}
            try:
                i = self.api.info()
                h.update(reachable=True, error=None,
                         info={k: i.get(k) for k in ("name", "ver", "ip")} | {"leds": i.get("leds", {}).get("count")})
            except Exception as e:
                h.update(reachable=False, error=str(e), info=self.wled_health.get("info"))
            self.wled_health = h
            self.stopping.wait(60)

    def peek_next(self):
        if not self.rotation:
            return None
        if self.pos + 1 < len(self.order):
            return str(self.order[self.pos + 1])
        return "(shuffled)" if self.shuffle else str(self.rotation[0])

    def update_status(self):
        now = self.schedule.now()
        sun = self.schedule.loc.sun(now.date())
        nxt = self.schedule.next_start(now)
        e, p = self.entry, self.mixer.cur
        entry = None
        if self.window is not None and e is not None:
            entry = {"label": str(e), "kind": e.kind, "name": e.name, "minutes": e.minutes,
                     "remaining_s": max(0, round(self.entry_end - time.monotonic())),
                     "options": dict(p.raw_opts) if (e.kind == "show" and p and p.name == e.name) else None,
                     "error": p.error if (e.kind == "show" and p) else None}
        st = {
            "now": _iso(now),
            "tz": self.schedule.loc.tz.key,
            "on": self.window is not None,
            "forced": bool(self.args.force_on),
            "preview": self.preview,
            "window": ({"start": _iso(self.window[0]), "end": _iso(self.window[1]),
                        "manual": self.manual is not None and self.window == self.manual}
                       if self.window else None),
            "manual": ({"start": _iso(self.manual[0]), "end": _iso(self.manual[1])} if self.manual else None),
            "suppressed_until": _iso(self.suppress_until),
            "next_window": {"start": _iso(nxt[0]), "end": _iso(nxt[1])} if nxt else None,
            "sun": {k: _iso(sun[k]) for k in ("dawn", "sunrise", "sunset", "dusk")},
            "entry": entry,
            "next": self.peek_next() if self.window is not None else None,
            "rotation": [str(x) for x in self.rotation],
            "scale": self.scale,
            "brightness": self.bri,
            "targets": self.targets,
            "wled": self.wled_health,
            "pending": [d for _, d, _ in self.pending.values()],
            "streaming": self.streamer is not None and self.mixer.cur is not None,
        }
        with self._status_lock:
            self._status = st

    def status(self):
        with self._status_lock:
            return dict(self._status)


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
    ap.add_argument("--config", default=os.environ.get("WLED_CONFIG", str(HERE / "config.yaml")),
                    help="config file (default: $WLED_CONFIG, else config.yaml here)")
    ap.add_argument("--host", help="WLED host (overrides config)")
    ap.add_argument("--preview", action="store_true", help="DDP to 127.0.0.1 and skip WLED API calls")
    ap.add_argument("--also", action="append", default=[], help="additional DDP target (repeatable)")
    ap.add_argument("--force-on", action="store_true", help="ignore the schedule; run the rotation now")
    ap.add_argument("--schedule", action="store_true", help="print upcoming windows and exit")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--web-port", type=int, default=8049, help="dashboard port (0 = no dashboard)")
    ap.add_argument("--web-bind", default="0.0.0.0", help="dashboard bind address")
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

    r = Runner(cfg, a, cfg_path)
    r.logbuf = LogBuffer()
    r.logbuf.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(r.logbuf)
    if a.web_port:
        from web.app import start_web     # imported here so the CLI works without fastapi
        start_web(r, a.web_bind, a.web_port)
    signal.signal(signal.SIGTERM, lambda *_: r.stopping.set())
    try:
        r.run()
    except KeyboardInterrupt:
        r.stopping.set()
        r.mixer.switch(None)
        r.stop_streaming()


if __name__ == "__main__":
    main()
