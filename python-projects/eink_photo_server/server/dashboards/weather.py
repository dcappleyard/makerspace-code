"""Weather dashboard (weather.gov), in the spirit of TRMNL's weather-at-a-glance.

Two styles:
  bars  (default) TRMNL-like range bars. Each day is a rounded pill spanning its
        low..high on a scale shared by the section (condition icon, high at the
        top, low at the bottom, shaded for the condition); each hour is a pill
        floating at its temperature. On landscape panels the current temperature
        is a left column with a pointer onto the first section's scale; on
        portrait panels it is a band across the top.
  tiles the period grid: label, temps and an inset condition tile per period.

Both: [current] [section A] [section B] [title bar], each section daily (N days)
or hourly (N hours), stacked or side by side.
"""
from __future__ import annotations

import math
from datetime import datetime

from . import DashboardType, Field, nws, register
from .draw import Surface, chip, fit_font, font, hline, icon_font, pill, small_icon, text, text_w, vline

# NWS icon code -> Weather Icons glyph (day, night).
_G = chr
GLYPHS = {
    "skc": (_G(0xF00D), _G(0xF02E)), "few": (_G(0xF00C), _G(0xF083)),
    "sct": (_G(0xF002), _G(0xF086)), "bkn": (_G(0xF013), _G(0xF086)), "ovc": (_G(0xF013), _G(0xF013)),
    "wind_skc": (_G(0xF021), _G(0xF021)), "wind_few": (_G(0xF021), _G(0xF021)),
    "wind_sct": (_G(0xF000), _G(0xF022)), "wind_bkn": (_G(0xF000), _G(0xF022)), "wind_ovc": (_G(0xF021), _G(0xF021)),
    "rain": (_G(0xF019), _G(0xF019)), "rain_showers": (_G(0xF009), _G(0xF029)),
    "rain_showers_hi": (_G(0xF009), _G(0xF029)),
    "snow": (_G(0xF01B), _G(0xF01B)), "blizzard": (_G(0xF01B), _G(0xF01B)),
    "rain_snow": (_G(0xF017), _G(0xF017)), "rain_sleet": (_G(0xF0B5), _G(0xF0B5)),
    "snow_sleet": (_G(0xF0B5), _G(0xF0B5)), "fzra": (_G(0xF0B5), _G(0xF0B5)),
    "rain_fzra": (_G(0xF0B5), _G(0xF0B5)), "snow_fzra": (_G(0xF0B5), _G(0xF0B5)), "sleet": (_G(0xF0B5), _G(0xF0B5)),
    "tsra": (_G(0xF01E), _G(0xF01E)), "tsra_sct": (_G(0xF010), _G(0xF02D)), "tsra_hi": (_G(0xF010), _G(0xF02D)),
    "tornado": (_G(0xF056), _G(0xF056)), "hurricane": (_G(0xF073), _G(0xF073)),
    "tropical_storm": (_G(0xF073), _G(0xF073)),
    "fog": (_G(0xF003), _G(0xF04A)), "haze": (_G(0xF0B6), _G(0xF014)),
    "smoke": (_G(0xF062), _G(0xF062)), "dust": (_G(0xF063), _G(0xF063)),
    "hot": (_G(0xF072), _G(0xF072)), "cold": (_G(0xF076), _G(0xF076)),
}
RAINDROP = _G(0xF078)
POP_MIN = 20     # don't show precip chances below this


def glyph(code: str, is_day: bool | None) -> str:
    day, night = GLYPHS.get(code, GLYPHS["bkn"])
    return night if is_day is False else day


SECTIONS = (("daily", "Daily"), ("hourly", "Hourly"), ("none", "None"))


@register
class Weather(DashboardType):
    name = "weather"
    label = "Weather (weather.gov)"
    version = "2"
    default_settings = {
        "lat": 43.0731, "lon": -89.4012, "location_label": "", "units": "us",
        "current": True, "style": "bars", "section_a": "daily", "section_b": "hourly",
        "split": "auto", "ratio": 0.55, "days": 7, "hours": 7, "step": 1, "show_pop": True,
        "title_bar": True, "show_battery": True,
    }
    form = (
        Field("lat", "Latitude", "number", step=0.0001, min=-90, max=90, group="Location"),
        Field("lon", "Longitude", "number", step=0.0001, min=-180, max=180, group="Location"),
        Field("location_label", "Label", help="blank = the nearest town weather.gov reports", group="Location"),
        Field("units", "Units", "select", (("us", "°F"), ("si", "°C")), group="Location"),
        Field("style", "Style", "select", (("bars", "Range bars"), ("tiles", "Tiles")), group="Layout",
              help="bars: each day a pill from low to high"),
        Field("current", "Current conditions", "bool", group="Layout"),
        Field("section_a", "First section", "select", SECTIONS, group="Layout",
              help="top, or left when side by side"),
        Field("section_b", "Second section", "select", SECTIONS, group="Layout"),
        Field("split", "Sections", "select",
              (("auto", "Auto"), ("stacked", "Stacked (top/bottom)"), ("side_by_side", "Side by side")),
              group="Layout"),
        Field("ratio", "First section share", "number", min=0.3, max=0.7, step=0.05, group="Layout"),
        Field("days", "Days", "number", min=3, max=7, step=1, group="Periods"),
        Field("hours", "Hours", "number", min=4, max=12, step=1, group="Periods"),
        Field("step", "Hour step", "select", (("1", "every hour"), ("2", "every 2 h"), ("3", "every 3 h")),
              group="Periods"),
        Field("show_pop", "Precip chance", "bool", help=f"shown at {POP_MIN}% and up", group="Periods"),
        Field("title_bar", "Title bar", "bool", group="Extras"),
        Field("show_battery", "Battery in title bar", "bool",
              help="when the frame's battery_monitor would show it", group="Extras"),
    )

    # -- data ---------------------------------------------------------------------
    def refresh_due(self, all_settings):
        locs = []
        for s in all_settings:
            loc = (float(s["lat"]), float(s["lon"]))
            if loc not in locs:
                locs.append(loc)
        nws.refresh_due(locs)

    def refresh(self, s):
        return nws.refresh(float(s["lat"]), float(s["lon"]))

    def status(self, s):
        e = nws.load(float(s["lat"]), float(s["lon"]))
        p = e.get("point") or {}
        return {"fetched_at": e.get("fetched_at"), "error": e.get("error"), "error_at": e.get("error_at"),
                "place": ", ".join(x for x in (p.get("city"), p.get("state")) if x),
                "grid": p.get("grid"), "station": ((e.get("data") or {}).get("current") or {}).get("station")}

    # -- model: exactly what's drawn (part of the cache key) ---------------------
    def model(self, s, ctx):
        now: datetime = ctx["now"]
        tz = ctx["tz"]
        si = s.get("units") == "si"

        def T(f):
            if f is None:
                return None
            return int(round((f - 32) * 5 / 9 if si else f))

        def pop(p):
            if not s.get("show_pop") or p is None or p < POP_MIN:
                return None
            return int(round(p / 10) * 10)

        e = nws.load(float(s["lat"]), float(s["lon"]))
        point = e.get("point") or {}
        m = {"location": s.get("location_label") or point.get("city") or "Weather",
             "battery": ctx.get("battery") if s.get("show_battery") else None}
        data = e.get("data")
        if not data:
            m["empty"] = "Waiting for weather.gov" + (f" ({e['error'][:60]})" if e.get("error") else "")
            return m
        fetched = datetime.fromisoformat(e["fetched_at"])
        # Dated (a frame that ran out of battery shows how old it is), hour
        # resolution (fewer redraws).
        m["updated"] = fetched.astimezone(tz).strftime("%a %b %-d, %-I %p")
        m["stale"] = (now - fetched).total_seconds() > nws.STALE_S
        today = now.astimezone(tz).date().isoformat()

        daily = [d for d in data["daily"] if d["date"] >= today]
        hour0 = now.replace(minute=0, second=0, microsecond=0)
        hourly = [h for h in data["hourly"] if datetime.fromisoformat(h["start"]) >= hour0]

        wanted = {s.get("section_a"), s.get("section_b")}
        if "daily" in wanted:
            m["daily"] = [{
                "label": ("Today" if d["high"] is not None else "Tonight") if d["date"] == today
                else datetime.fromisoformat(d["date"]).strftime("%a %-d"),
                "high": T(d["high"]), "low": T(d["low"]), "pop": pop(d["pop"]),
                "cond": nws.CODE_COND.get(d["code"], "cloudy"), "glyph": glyph(d["code"], d["is_day"]),
            } for d in daily[: int(s["days"])]]
        if "hourly" in wanted:
            step = max(1, int(s["step"]))
            picked = hourly[::step][: int(s["hours"])]
            m["hourly"] = [{
                "label": "Now" if i == 0 and datetime.fromisoformat(h["start"]) <= now
                else datetime.fromisoformat(h["start"]).astimezone(tz).strftime("%-I %p"),
                "temp": T(h["temp"]), "pop": pop(h["pop"]),
                "cond": nws.CODE_COND.get(h["code"], "cloudy"), "glyph": glyph(h["code"], h["is_day"]),
            } for i, h in enumerate(picked)]
        if s.get("current"):
            cur = data.get("current")
            first = hourly[0] if hourly else None
            src = cur or (first and {"temp": first["temp"], "feels": first["temp"], "code": first["code"],
                                     "is_day": first["is_day"], "short": first["short"]})
            if src:
                t0 = daily[0] if daily and daily[0]["date"] == today else None
                at = cur.get("at") if cur else None
                m["current"] = {
                    "at": datetime.fromisoformat(at).astimezone(tz).strftime("%-I:%M %p") if at else None,
                    "temp": T(src["temp"]), "feels": T(src["feels"]),
                    "short": src.get("short") or "", "cond": nws.CODE_COND.get(src["code"], "cloudy"),
                    "glyph": glyph(src["code"], src.get("is_day")),
                    "high": T(t0["high"]) if t0 else None, "low": T(t0["low"]) if t0 else None,
                }
        return m

    # -- drawing ------------------------------------------------------------------
    def render(self, m, surface: Surface, s):
        th = surface.theme
        W, H = surface.width, surface.height
        img, d = surface.canvas()
        pad = max(4, round(min(W, H) * 0.02))
        bottom = H
        if s.get("title_bar"):
            bar_h = max(th.min_font + 8, min(56, round(H * 0.075)))
            _title_bar(d, m, (0, H - bar_h, W, H), th)
            bottom = H - bar_h
        if m.get("empty"):
            f = fit_font(d, m["empty"], W * 0.9, bottom * 0.08)
            text(d, (W / 2, bottom / 2), m["empty"], f, th.fg)
            return img

        x0, y0, x1, y1 = pad, pad, W - pad, bottom - pad
        if s.get("style", "bars") == "bars":
            _render_bars(img, d, m, s, th, (x0, y0, x1, y1), pad)
            return img
        if m.get("current"):
            if (x1 - x0) / max(1, y1 - y0) > 2.6:        # very wide: current is a left column
                cw = round(min((x1 - x0) * 0.26, (y1 - y0) * 1.3))
                _current_column(img, d, m["current"], (x0, y0, x0 + cw, y1), th)
                vline(d, x0 + cw + pad, y0, y1, th.rule, max(1, pad // 4))
                x0 += cw + 2 * pad
            else:
                ch = round((y1 - y0) * 0.27)
                _current_band(img, d, m["current"], (x0, y0, x1, y0 + ch), th)
                hline(d, x0, x1, y0 + ch + pad // 2, th.rule, max(1, pad // 4))
                y0 += ch + pad

        secs = [k for k in (s.get("section_a"), s.get("section_b")) if k in ("daily", "hourly") and m.get(k)]
        if not secs:
            return img
        boxes = _split(d, len(secs), (x0, y0, x1, y1), s, th, pad)
        for kind, box in zip(secs, boxes):
            _section(img, d, kind, m[kind], box, th)
        return img


# --- layout helpers ----------------------------------------------------------------

def _split(d, n, box, s, th, pad, rule=True):
    """Boxes for n (1 or 2) sections: stacked, or side by side on very wide areas."""
    x0, y0, x1, y1 = box
    if n < 2:
        return [box]
    split = s.get("split", "auto")
    if split == "auto":
        split = "side_by_side" if (x1 - x0) / max(1, y1 - y0) > 3.0 else "stacked"
    r = float(s.get("ratio", 0.5))
    if split == "side_by_side":
        xm = round(x0 + (x1 - x0) * r)
        if rule:
            vline(d, xm, y0, y1, th.rule, max(1, pad // 4))
        return [(x0, y0, xm - pad, y1), (xm + pad, y0, x1, y1)]
    ym = round(y0 + (y1 - y0) * r)
    if rule:
        hline(d, x0, x1, ym, th.rule, max(1, pad // 4))
    return [(x0, y0, x1, ym - pad // 2), (x0, ym + pad // 2, x1, y1)]

def _uniform(d, texts, max_w, max_h, bold=False, min_size=6):
    """One font size that fits every text (so a row of columns matches)."""
    size = max(min_size, int(max_h))
    while size > min_size and any(text_w(d, t, font(size, bold)) > max_w for t in texts if t):
        size -= 1
    return font(size, bold)


def _deg(t) -> str:
    return "—" if t is None else f"{t}°"


def _pop_text(d, cx, cy, p, f, ink):
    """Raindrop icon + 'NN%' centred on (cx, cy)."""
    if p is None:
        return
    s = f"{p}%"
    size = f.size
    iw = text_w(d, RAINDROP, _icon(size))
    tw = text_w(d, s, f)
    gap = max(1, size // 6)
    left = cx - (iw + gap + tw) / 2
    small_icon(d, (left, cy), RAINDROP, size, ink, anchor="lm")
    text(d, (left + iw + gap, cy), s, f, ink, anchor="lm")


def _icon(size):
    from .draw import icon_font
    return icon_font(size)


def _section(img, d, kind, items, box, th):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    n = len(items)
    if n == 0 or w < 20 or h < 20:
        return
    # Columns suit wide sections, rows tall ones: pick the shape whose cells
    # are closest to the ideal proportions.
    col_err = abs(math.log(((w / n) / h) / 0.55))
    row_err = abs(math.log((w / (h / n)) / 6.0))
    if col_err <= row_err:
        _columns(img, d, kind, items, box, th)
    else:
        _rows(img, d, kind, items, box, th)


def _columns(img, d, kind, items, box, th):
    x0, y0, x1, y1 = box
    n = len(items)
    cw, h = (x1 - x0) / n, y1 - y0
    daily = kind == "daily"
    has_pop = any(i["pop"] is not None for i in items)
    # Row shares of the column height (the pop row's share goes to the others
    # when nothing has a precip chance to show).
    rows = ([("label", .16), ("hi", .2), ("chip", .34), ("lo", .17), ("pop", .13)] if daily else
            [("label", .18), ("chip", .38), ("hi", .26), ("pop", .18)])
    if not has_pop:
        rows = [(k, v) for k, v in rows if k != "pop"]
    total = sum(v for _, v in rows)
    ys, y = {}, y0
    for key, share in rows:
        ys[key] = (y, y + h * share / total)
        y += h * share / total
    rh = {k: b - a for k, (a, b) in ys.items()}

    f_label = _uniform(d, [i["label"] for i in items], cw * 0.9, rh["label"] * 0.7, True, th.min_font)
    temps_hi = [_deg(i["high"] if daily else i["temp"]) for i in items]
    f_hi = _uniform(d, temps_hi, cw * 0.8, rh["hi"] * (0.78 if daily else 0.6), True, th.min_font)
    if daily:
        f_lo = _uniform(d, [_deg(i["low"]) for i in items], cw * 0.8, rh["lo"] * 0.7, False, th.min_font)
    f_pop = _uniform(d, ["100%"], cw * 0.62, rh["pop"] * 0.7, False, th.min_font) if has_pop else None
    side = min(cw * 0.82, rh["chip"] * 0.94)

    for i, it in enumerate(items):
        cx = x0 + cw * (i + 0.5)
        text(d, (cx, sum(ys["label"]) / 2), it["label"], f_label, th.fg)
        text(d, (cx, sum(ys["hi"]) / 2), temps_hi[i], f_hi, th.hi if daily else th.fg)
        cy = sum(ys["chip"]) / 2
        chip(img, d, (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2), th.fill(it["cond"]),
             it["glyph"], th)
        if daily:
            text(d, (cx, sum(ys["lo"]) / 2), _deg(it["low"]), f_lo, th.lo)
        if has_pop:
            _pop_text(d, cx, sum(ys["pop"]) / 2, it["pop"], f_pop, th.muted)


def _rows(img, d, kind, items, box, th):
    x0, y0, x1, y1 = box
    n = len(items)
    w, rh = x1 - x0, (y1 - y0) / n
    daily = kind == "daily"
    # Column shares of the row width.
    cols = ([("label", .26), ("chip", .16), ("hi", .2), ("lo", .18), ("pop", .2)] if daily else
            [("label", .3), ("chip", .18), ("hi", .26), ("pop", .26)])
    xs, x = {}, x0
    for key, share in cols:
        xs[key] = (x, x + w * share)
        x += w * share
    cwid = {k: b - a for k, (a, b) in xs.items()}
    f_label = _uniform(d, [i["label"] for i in items], cwid["label"] * 0.92, rh * 0.5, True, th.min_font)
    temps_hi = [_deg(i["high"] if daily else i["temp"]) for i in items]
    f_hi = _uniform(d, temps_hi, cwid["hi"] * 0.9, rh * 0.58, True, th.min_font)
    f_lo = _uniform(d, [_deg(i["low"]) for i in items] if daily else ["0"], cwid["lo"] * 0.9 if daily else 99,
                    rh * 0.5, False, th.min_font)
    f_pop = _uniform(d, ["100%"], cwid["pop"] * 0.6, rh * 0.42, False, th.min_font)
    side = min(rh * 0.86, cwid["chip"] * 0.9)
    for i, it in enumerate(items):
        cy = y0 + rh * (i + 0.5)
        if i:
            hline(d, x0, x1, round(y0 + rh * i), th.muted, 1)
        text(d, (xs["label"][0], cy), it["label"], f_label, th.fg, anchor="lm")
        cx = sum(xs["chip"]) / 2
        chip(img, d, (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2), th.fill(it["cond"]),
             it["glyph"], th)
        text(d, (sum(xs["hi"]) / 2, cy), temps_hi[i], f_hi, th.hi if daily else th.fg)
        if daily:
            text(d, (sum(xs["lo"]) / 2, cy), _deg(it["low"]), f_lo, th.lo)
        _pop_text(d, sum(xs["pop"]) / 2, cy, it["pop"], f_pop, th.muted)


def _current_band(img, d, c, box, th):
    """Horizontal: [tile] [big temp] [conditions / feels like / hi-lo]."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    side = h * 0.92
    chip(img, d, (x0, y0 + (h - side) / 2, x0 + side, y0 + (h + side) / 2), th.fill(c["cond"]), c["glyph"], th)
    x = x0 + side + h * 0.18
    t = _deg(c["temp"])
    # Big, but leave the text lines at least ~40% of the band on narrow panels.
    big = fit_font(d, t, max((x1 - x0) * 0.3, (x1 - x) - (x1 - x0) * 0.4), h * 0.78, True, th.min_font)
    text(d, (x, y0 + h / 2), t, big, th.fg, anchor="lm")
    x += text_w(d, t, big) + h * 0.25
    lines = [c["short"], f"Feels like {_deg(c['feels'])}"]
    if c.get("high") is not None or c.get("low") is not None:
        lines.append(f"High {_deg(c['high'])}   Low {_deg(c['low'])}")
    avail = x1 - x
    lh = h / 3
    f_main = fit_font(d, lines[0], avail, lh * 0.7, True, th.min_font)
    f_sub = _uniform(d, lines[1:], avail, lh * 0.6, False, th.min_font)
    for i, line in enumerate(lines):
        text(d, (x, y0 + lh * (i + 0.5)), line, f_main if i == 0 else f_sub, th.fg if i == 0 else th.muted,
             anchor="lm")


def _current_column(img, d, c, box, th):
    """Vertical (wide panels): tile, big temp, then the text lines."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    cx = (x0 + x1) / 2
    side = min(w * 0.6, h * 0.42)
    chip(img, d, (cx - side / 2, y0, cx + side / 2, y0 + side), th.fill(c["cond"]), c["glyph"], th)
    y = y0 + side + h * 0.04
    t = _deg(c["temp"])
    big = fit_font(d, t, w * 0.9, h * 0.22, True, th.min_font)
    text(d, (cx, y), t, big, th.fg, anchor="mt")
    y += big.size * 1.1
    lines = [c["short"], f"Feels like {_deg(c['feels'])}"]
    if c.get("high") is not None or c.get("low") is not None:
        lines.append(f"High {_deg(c['high'])}  Low {_deg(c['low'])}")
    lh = (y1 - y) / max(3, len(lines))
    f_main = fit_font(d, lines[0], w * 0.95, lh * 0.6, True, th.min_font)
    f_sub = _uniform(d, lines[1:], w * 0.95, lh * 0.5, False, th.min_font)
    for i, line in enumerate(lines):
        text(d, (cx, y + lh * (i + 0.5)), line, f_main if i == 0 else f_sub, th.fg if i == 0 else th.muted)


def _title_bar(d, m, box, th):
    x0, y0, x1, y1 = box
    h = y1 - y0
    d.rectangle([x0, y0, x1, y1], fill=th.bar_bg)
    pad = h * 0.4
    f = font(max(th.min_font, round(h * 0.5)), True)
    fr = font(max(th.min_font, round(h * 0.45)))
    right = []
    if m.get("stale"):
        right.append("STALE")
    if m.get("updated"):
        right.append(f"Updated {m['updated']}")
    if m.get("battery") is not None:
        right.append(f"Battery {m['battery']}%")
    right = "   ·   ".join(right)
    # Shrink both sides together if they'd collide (narrow portrait panels).
    while f.size > th.min_font and text_w(d, m.get("location", ""), f) + text_w(d, right, fr) > (x1 - x0) - 3 * pad:
        f, fr = font(f.size - 1, True), font(max(th.min_font, fr.size - 1))
    text(d, (x0 + pad, y0 + h / 2), m.get("location", ""), f, th.bar_fg, anchor="lm")
    text(d, (x1 - pad, y0 + h / 2), right, fr, th.bar_fg, anchor="rm")



# --- range-bar style ----------------------------------------------------------------

def _render_bars(img, d, m, s, th, box, pad):
    x0, y0, x1, y1 = box
    secs = [k for k in (s.get("section_a"), s.get("section_b")) if k in ("daily", "hourly") and m.get(k)]
    cur = m.get("current")
    column = None
    if cur:
        if (x1 - x0) / max(1, y1 - y0) > 1.15:      # landscape: current is a left column
            cw = round(min((x1 - x0) * 0.28, (y1 - y0) * 0.8))
            column = (x0, y0, x0 + cw, y1)
            x0 += cw + pad
        else:                                         # portrait: a band across the top
            ch = round((y1 - y0) * 0.2)
            _bars_current_band(d, cur, (x0, y0, x1, y0 + ch), th)
            hline(d, x0, x1, y0 + ch + pad // 2, th.rule, max(1, pad // 4))
            y0 += ch + pad
    minspan = 6 if s.get("units") == "si" else 10
    scales = [_bars(img, d, kind, m[kind], b, th, minspan, pad)
              for kind, b in zip(secs, _split(d, len(secs), (x0, y0, x1, y1), s, th, pad, rule=False))]
    if column:
        first = scales[0] if scales else None
        ptr = first["y"](cur["temp"]) if first and cur.get("temp") is not None else None
        _bars_current_column(d, cur, column, th, ptr, first["left"] if first else x0)


def _bars(img, d, kind, items, box, th, minspan, pad):
    """One section of range bars. Returns its temperature scale (for the current
    temperature's pointer): {"y": temp -> y, "left": x of the first bar}."""
    x0, y0, x1, y1 = box
    n = len(items)
    w, h = x1 - x0, y1 - y0
    if not n or w < 20 or h < 40:
        return None
    daily = kind == "daily"
    cw = w / n
    f_lab = _uniform(d, [i["label"] for i in items], cw * 0.94, min(h * 0.08, cw * 0.26), True, th.min_font)
    lab_h = f_lab.size * 1.5
    has_pop = any(i["pop"] is not None for i in items)
    f_pop = font(max(th.min_font, round(f_lab.size * 0.9)))
    pop_h = f_pop.size * 1.5 if has_pop else 0
    ya, yb = y0 + lab_h, y1 - pop_h - (0 if has_pop else pad / 2)
    pw = min(cw * 0.74, (yb - ya) * 0.34)             # bar width: slim on wide, short panels

    nums = [_num(t) for i in items for t in ((i["high"], i["low"]) if daily else (i["temp"],))]
    f_num = _uniform(d, nums, pw * 0.86, pw * 0.36, True, th.min_font)
    ic, pp = pw * 0.55, pw * 0.16                     # icon size, inner padding

    def h_min(ic, pp, nf):
        # Content of the shortest bar: icon + number (+ a second number for daily).
        return 2 * pp + ic + nf * (2.2 if daily else 1.1)

    H = h_min(ic, pp, f_num.size)
    if H > (yb - ya) * 0.72:                          # short section: shrink the contents
        k = (yb - ya) * 0.72 / H
        ic, pp = ic * k, pp * k
        f_num = font(max(th.min_font, int(f_num.size * k)), True)
        H = h_min(ic, pp, f_num.size)

    temps = [t for i in items for t in ((i["high"], i["low"]) if daily else (i["temp"],)) if t is not None]
    if not temps:
        return None
    tmin, tmax = min(temps), max(temps)
    if tmax - tmin < minspan:                         # don't blow a 2° wobble up to full height
        mid = (tmin + tmax) / 2
        tmin, tmax = mid - minspan / 2, mid + minspan / 2
    top_c, bot_c = ya + H / 2, yb - H / 2

    def y_of(t):
        t = min(tmax, max(tmin, t))
        return bot_c - (t - tmin) / (tmax - tmin) * (bot_c - top_c)

    for i, it in enumerate(items):
        cx = x0 + cw * (i + 0.5)
        text(d, (cx, y0 + lab_h * 0.45), it["label"], f_lab, th.fg)
        if daily:
            hi = it["high"] if it["high"] is not None else it["low"]
            lo = it["low"] if it["low"] is not None else it["high"]
            if hi is None:
                continue
            top, bot = y_of(hi) - H / 2, y_of(lo) + H / 2
        else:
            if it["temp"] is None:
                continue
            top = y_of(it["temp"]) - H / 2
            bot = top + H
        fill = th.fill(it["cond"])
        pill(img, d, (cx - pw / 2, top, cx + pw / 2, bot), fill, th)
        halo = (fill.halo or fill.bg) if fill.pattern else None
        sw = max(1, f_num.size // 8) if halo else 0
        kw = dict(anchor="mm", stroke_width=sw, stroke_fill=halo)
        _glyph_in(d, it["glyph"], (cx, top + pp + ic / 2), pw * 0.84, ic, fill.icon, sw, halo)
        num_y = top + pp + ic + f_num.size * 0.55
        if daily:
            if it["high"] is not None:
                d.text((cx, num_y), _num(it["high"]), font=f_num, fill=fill.icon, **kw)
            if it["low"] is not None:
                d.text((cx, bot - pp - f_num.size * 0.5), _num(it["low"]), font=f_num, fill=fill.icon, **kw)
        else:
            d.text((cx, num_y), _num(it["temp"]), font=f_num, fill=fill.icon, **kw)
        if has_pop:
            _pop_text(d, cx, y1 - pop_h / 2, it["pop"], f_pop, th.muted)
    return {"y": y_of, "left": x0 + (cw - pw) / 2}


def _glyph_in(d, g, centre, max_w, max_h, ink, stroke=0, halo=None):
    """Draw an icon glyph as large as fits max_w x max_h, centred on its actual
    ink (Weather Icons glyphs differ a lot in extent: sun rays, rain streaks)."""
    size = int(max_h * 1.4)
    while size > 6:
        l, t, r, b = d.textbbox((0, 0), g, font=icon_font(size), anchor="mm")
        if r - l <= max_w and b - t <= max_h:
            break
        size -= 1
    f = icon_font(size)
    l, t, r, b = d.textbbox((0, 0), g, font=f, anchor="mm")
    d.text((centre[0] - (l + r) / 2, centre[1] - (t + b) / 2), g, font=f, fill=ink, anchor="mm",
           stroke_width=stroke, stroke_fill=halo)


def _num(t) -> str:
    """A temperature inside a bar: no degree sign (TRMNL-style, room for bigger digits)."""
    return "—" if t is None else str(t)


def _cur_lines(c):
    lines = [c.get("short") or ""]
    if c.get("feels") is not None and c.get("temp") is not None and abs(c["feels"] - c["temp"]) >= 2:
        lines.append(f"Feels like {_deg(c['feels'])}")
    if c.get("high") is not None or c.get("low") is not None:
        lines.append(f"H {_deg(c['high'])}  ·  L {_deg(c['low'])}")
    return [x for x in lines if x]


def _big_temp(d, t, max_w, max_h, th):
    return fit_font(d, t, max_w, max_h, False, th.min_font)


def _visual_mid(d, t, f):
    """Offset from an 'lm'-anchored y to the glyphs' visual middle."""
    _, top, _, bot = d.textbbox((0, 0), t, font=f, anchor="lm")
    return (top + bot) / 2, top, bot


def _bars_current_column(d, c, box, th, ptr_y, tip_x):
    """Landscape: time, a big temperature level with its place on the first
    section's scale and a pointer onto it; conditions in the space left."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    t = _deg(c["temp"])
    big = _big_temp(d, t, w * 0.68, min(h * 0.3, w * 0.45), th)
    mid, top, bot = _visual_mid(d, t, big)
    f_at = font(max(th.min_font, round(big.size * 0.19)), True)
    at_h = f_at.size * 1.6
    if ptr_y is None:
        ptr_y = y0 + h * 0.35
    # Temperature centred on the pointer, kept inside the column.
    cy = min(max(ptr_y, y0 + at_h + (mid - top)), y1 - (bot - mid))
    by = cy - mid                                     # 'lm' anchor y
    text(d, (x0, by + top - at_h / 2), c.get("at") or "Now", f_at, th.fg, anchor="lm")
    text(d, (x0, by), t, big, th.fg, anchor="lm")
    # Pointer: a rule from the number to a triangle at the first bar.
    lw = max(2, big.size // 30)
    lx = x0 + text_w(d, t, big) + big.size * 0.12
    tr = lw * 3
    if tip_x - tr * 2 > lx + tr:
        d.line([(lx, ptr_y), (tip_x - tr * 1.5, ptr_y)], fill=th.fg, width=lw)
        d.polygon([(tip_x - 1, ptr_y), (tip_x - tr * 1.8, ptr_y - tr), (tip_x - tr * 1.8, ptr_y + tr)], fill=th.fg)
    # Conditions in the larger space above or below the temperature.
    block_top, block_bot = by + top - at_h, by + bot
    gap = h * 0.04
    above, below = (y0, block_top - gap), (block_bot + gap, y1)
    ry0, ry1 = max((above, below), key=lambda r: r[1] - r[0])
    _cond_block(d, c, (x0, ry0, x1, ry1), th, big.size)


def _cond_block(d, c, box, th, big_size, align="center"):
    """Condition icon + text lines, left-aligned, centred vertically in box."""
    x0, y0, x1, y1 = box
    w, rh = x1 - x0, y1 - y0
    lines = _cur_lines(c)
    size = max(th.min_font, round(big_size * 0.2))
    f_main = fit_font(d, lines[0], w * 0.98, size, True, th.min_font) if lines else None
    f_sub = _uniform(d, lines[1:] or ["x"], w * 0.98, size * 0.9, False, th.min_font)
    lh = size * 1.45
    gs = min(w * 0.32, size * 3)
    while lines and (gs + len(lines) * lh > rh):
        if gs:
            gs = 0
        else:
            lines.pop()
    if not lines and not gs:
        return
    total = gs + len(lines) * lh
    y = y0 + (rh - total) / 2
    if gs:
        d.text((x0, y + gs / 2), c["glyph"], font=icon_font(int(gs)), fill=th.fg, anchor="lm")
        y += gs
    for i, line in enumerate(lines):
        text(d, (x0, y + lh / 2), line, f_main if i == 0 else f_sub, th.fg if i == 0 else th.muted, anchor="lm")
        y += lh


def _bars_current_band(d, c, box, th):
    """Portrait: [time / big temperature] [icon + conditions]."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    t = _deg(c["temp"])
    f_at = font(max(th.min_font, round(h * 0.13)), True)
    at_h = f_at.size * 1.5
    big = _big_temp(d, t, w * 0.45, (h - at_h) * 0.95, th)
    mid, top, bot = _visual_mid(d, t, big)
    by = y0 + at_h + (h - at_h) / 2 - mid
    text(d, (x0, y0 + at_h / 2), c.get("at") or "Now", f_at, th.fg, anchor="lm")
    text(d, (x0, by), t, big, th.fg, anchor="lm")
    xr = x0 + text_w(d, t, big) + w * 0.06
    gs = min(h * 0.6, (x1 - xr) * 0.3)
    d.text((xr + gs / 2, y0 + h / 2), c["glyph"], font=icon_font(int(gs)), fill=th.fg, anchor="mm")
    xr += gs + w * 0.04
    lines = _cur_lines(c)
    if not lines:
        return
    lh = h / max(3, len(lines))
    f_main = fit_font(d, lines[0], x1 - xr, lh * 0.5, True, th.min_font)
    f_sub = _uniform(d, lines[1:] or ["x"], x1 - xr, lh * 0.45, False, th.min_font)
    y = y0 + (h - lh * len(lines)) / 2
    for i, line in enumerate(lines):
        text(d, (xr, y + lh / 2), line, f_main if i == 0 else f_sub, th.fg if i == 0 else th.muted, anchor="lm")
        y += lh
