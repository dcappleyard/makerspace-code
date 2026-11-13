"""On/off windows from sun times and clock times.

Time expressions (config `on:` / `off:`):
    "23:00"              local clock time
    "sunset - 15m"       sun event +/- offset; events: sunrise, sunset, dawn, dusk, noon
    "sunrise + 1h30m"
    "dusk"

A window whose off time is at or before its on time ends the next day
(e.g. on: sunset, off: "01:00"). Windows can't be longer than 24 h.

Each window names the show it plays (`show:`); windows without one play the
default show. Intervals come back as Interval(start, end, show).
"""
import datetime as dt
import re
from dataclasses import dataclass
from typing import NamedTuple
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

SUN_EVENTS = ("sunrise", "sunset", "dawn", "dusk", "noon")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
_SUN = re.compile(r"^(sunrise|sunset|dawn|dusk|noon)\s*(?:([+-])\s*((?:\d+h)?\s*(?:\d+m)?))?$")


def parse_offset(s):
    """'1h30m' / '15m' / '2h' -> timedelta."""
    m = re.fullmatch(r"\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*", s or "")
    if not m or not (m.group(1) or m.group(2)):
        raise ValueError(f"bad offset {s!r} (use e.g. 15m, 1h, 1h30m)")
    return dt.timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0))


@dataclass(frozen=True)
class TimeExpr:
    text: str
    event: str = None          # sun event, or None for a clock time
    offset: dt.timedelta = dt.timedelta(0)
    clock: dt.time = None

    @classmethod
    def parse(cls, text):
        s = str(text).strip().lower()
        m = _CLOCK.match(s)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            return cls(text=str(text), clock=dt.time(h, mi))
        m = _SUN.match(s)
        if m:
            off = dt.timedelta(0)
            if m.group(2):
                off = parse_offset(m.group(3))
                if m.group(2) == "-":
                    off = -off
            return cls(text=str(text), event=m.group(1), offset=off)
        raise ValueError(f"bad time {text!r} (use \"HH:MM\" or e.g. \"sunset - 15m\")")


class Location:
    def __init__(self, latitude, longitude, timezone, name="site"):
        self.tz = ZoneInfo(timezone)
        self.info = LocationInfo(name, "", timezone, latitude, longitude)
        self._cache = {}

    def sun(self, date):
        if date not in self._cache:
            self._cache[date] = sun(self.info.observer, date=date, tzinfo=self.tz)
        return self._cache[date]

    def resolve(self, expr, date):
        """TimeExpr on a given local date -> aware datetime."""
        if expr.clock is not None:
            return dt.datetime.combine(date, expr.clock, tzinfo=self.tz)
        return self.sun(date)[expr.event] + expr.offset


class Interval(NamedTuple):
    start: dt.datetime
    end: dt.datetime
    show: str = None


@dataclass(frozen=True)
class Window:
    on: TimeExpr
    off: TimeExpr
    show: str = None

    def on_date(self, loc, date):
        """Interval for the window that starts on `date`."""
        start = loc.resolve(self.on, date)
        end = loc.resolve(self.off, date)
        if end <= start:
            end = loc.resolve(self.off, date + dt.timedelta(days=1))
        return Interval(start, end, self.show)


class Schedule:
    def __init__(self, loc, windows):
        self.loc, self.windows = loc, windows

    @classmethod
    def from_config(cls, cfg, default_show=None):
        """Windows from config; a window without show: plays `default_show`."""
        lc = cfg.get("location", {})
        loc = Location(lc.get("latitude", 43.07), lc.get("longitude", -89.40),
                       lc.get("timezone", "America/Chicago"), lc.get("name", "Madison"))
        sc = cfg.get("schedule", {})
        raw = sc.get("windows") or [sc]          # single on/off pair directly under schedule:
        wins = []
        for w in raw:
            # YAML 1.1 (PyYAML) reads bare `on:` / `off:` keys as booleans True / False
            on, off = w.get("on", w.get(True)), w.get("off", w.get(False))
            if on is None or off is None:
                raise ValueError(f"schedule window needs on: and off: ({w})")
            wins.append(Window(TimeExpr.parse(on), TimeExpr.parse(off), w.get("show") or default_show))
        return cls(loc, wins)

    def now(self):
        return dt.datetime.now(self.loc.tz)

    def intervals(self, date):
        """All windows starting on `date`, sorted."""
        return sorted((w.on_date(self.loc, date) for w in self.windows), key=lambda i: (i.start, i.end))

    def active(self, when=None):
        """Interval of the window containing `when`, else None."""
        when = when or self.now()
        d = when.astimezone(self.loc.tz).date()
        for day in (d - dt.timedelta(days=1), d):
            for iv in self.intervals(day):
                if iv.start <= when < iv.end:
                    return iv
        return None

    def next_start(self, when=None):
        when = when or self.now()
        d = when.astimezone(self.loc.tz).date()
        for i in range(0, 3):
            for iv in self.intervals(d + dt.timedelta(days=i)):
                if iv.start > when:
                    return iv
        return None
