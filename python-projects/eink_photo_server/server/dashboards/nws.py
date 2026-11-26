"""National Weather Service (api.weather.gov) client, normalizer and cache.

Pulls never wait on NWS. A background refresher fetches each location in use
every REFRESH_S and writes DATA_DIR/dashboards/wx-<lat>,<lon>.json. Rendering
reads the last good copy and flags it stale after STALE_S. Dashboards at the
same location share a single fetch.

Everything is stored in US units (°F, mph) as NWS sends them. Dashboards
convert at render time.

API notes (checked against Madison, WI, 2026-11):
- /points/{lat},{lon} -> grid + forecast URLs, timezone, nearby city, stations.
  It's stable, so it's resolved once per cache file.
- /forecast: 14 twelve-hour periods (day ~6am-6pm, night ~6pm-6am). The first
  may be partial ("This Afternoon", "Tonight"). Names vary ("Thanksgiving Day"),
  so days are paired by startTime date, never by name.
- /forecast/hourly: ~156 one-hour periods.
- Icon URLs: .../icons/land/{day|night}/{code}[,{pop}][/{code2}...]. The first
  code is the dominant one. shortForecast is the fallback when icon is missing.
- 500/503s and stale grids happen, so retry with backoff and keep the last good data.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config as cfg

log = logging.getLogger(__name__)

API = "https://api.weather.gov"
# NWS asks for an identifying User-Agent. A generic app name, no personal details.
USER_AGENT = "eink-frame-server/1.0 (weather dashboard)"
TIMEOUT_S = 15
REFRESH_S = 20 * 60
STALE_S = 3 * 3600
HOURLY_KEEP = 48

_ICON = re.compile(r"/icons/land/(day|night)/([a-z_]+)")

# NWS icon code -> our condition (the chip's shade). The glyph is chosen per code
# in weather.py.
CONDITIONS = ("clear", "partly", "cloudy", "wind", "rain", "mix", "snow", "storm", "fog", "hot", "cold")
CODE_COND = {
    "skc": "clear", "few": "clear", "sct": "partly", "bkn": "cloudy", "ovc": "cloudy",
    "wind_skc": "wind", "wind_few": "wind", "wind_sct": "wind", "wind_bkn": "wind", "wind_ovc": "wind",
    "rain": "rain", "rain_showers": "rain", "rain_showers_hi": "rain",
    "snow": "snow", "blizzard": "snow",
    "rain_snow": "mix", "rain_sleet": "mix", "snow_sleet": "mix", "fzra": "mix", "rain_fzra": "mix",
    "snow_fzra": "mix", "sleet": "mix",
    "tsra": "storm", "tsra_sct": "storm", "tsra_hi": "storm", "tornado": "storm", "hurricane": "storm",
    "tropical_storm": "storm",
    "fog": "fog", "haze": "fog", "smoke": "fog", "dust": "fog",
    "hot": "hot", "cold": "cold",
}
# shortForecast keywords -> code, first match wins (used when there's no icon).
_TEXT_CODES = [
    (r"thunder|t-storm", "tsra"), (r"blizzard", "blizzard"), (r"freezing|sleet|wintry", "rain_snow"),
    (r"snow|flurr", "snow"), (r"shower", "rain_showers"), (r"rain|drizzle", "rain"),
    (r"fog|haze|smoke|dust", "fog"), (r"wind|breezy|blustery", "wind_sct"), (r"overcast", "ovc"),
    (r"mostly cloudy|considerable cloud", "bkn"), (r"partly|mostly sunny|mostly clear", "sct"),
    (r"cloudy", "ovc"), (r"sunny|clear|fair", "skc"),
]


def icon_code(icon_url: str | None, text: str | None) -> tuple[str, bool | None]:
    """(NWS code, is_day or None) from an icon URL, else from the forecast text."""
    m = _ICON.search(icon_url or "")
    if m and m[2] in CODE_COND:
        return m[2], m[1] == "day"
    t = (text or "").lower()
    for pat, code in _TEXT_CODES:
        if re.search(pat, t):
            return code, (m[1] == "day") if m else None
    return "bkn", (m[1] == "day") if m else None


# --- HTTP ----------------------------------------------------------------------

def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 and e.code != 429:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise last


def _val(q) -> float | None:
    """NWS quantitative value {"value": x, "unitCode": ...} -> x."""
    return q.get("value") if isinstance(q, dict) else q


def _c_to_f(c):
    return None if c is None else c * 9 / 5 + 32


def resolve_point(lat: float, lon: float) -> dict:
    p = _get(f"{API}/points/{lat:.4f},{lon:.4f}")["properties"]
    rel = (p.get("relativeLocation") or {}).get("properties") or {}
    stations = []
    try:
        st = _get(p["observationStations"])
        stations = [f["properties"]["stationIdentifier"] for f in st.get("features", [])[:3]]
    except Exception as e:
        log.warning("NWS stations for %s,%s: %s", lat, lon, e)
    return {"grid": f"{p.get('gridId')}/{p.get('gridX')},{p.get('gridY')}",
            "forecast": p["forecast"], "forecast_hourly": p["forecastHourly"],
            "stations": stations, "tz": p.get("timeZone"),
            "city": rel.get("city", ""), "state": rel.get("state", "")}


# --- normalizing -----------------------------------------------------------------

def _period(p: dict) -> dict:
    code, is_day = icon_code(p.get("icon"), p.get("shortForecast"))
    return {"start": p["startTime"], "temp": p.get("temperature"),
            "pop": _val(p.get("probabilityOfPrecipitation")) or 0,
            "code": code, "is_day": bool(p.get("isDaytime")) if is_day is None else is_day,
            "short": p.get("shortForecast", ""), "name": p.get("name", ""),
            "wind": " ".join(x for x in (p.get("windDirection"), p.get("windSpeed")) if x)}


def normalize_daily(periods: list[dict]) -> list[dict]:
    """Pair day/night periods by local date: high = the day period, low = the
    night that follows it. A leading night-only date ("Tonight") has no high."""
    days: dict[str, dict] = {}
    order = []
    for p in map(_period, periods):
        date = p["start"][:10]           # local date: startTime carries the local offset
        if date not in days:
            days[date] = {"date": date, "day": None, "night": None}
            order.append(date)
        days[date]["day" if p["is_day"] else "night"] = p
    out = []
    for date in order:
        d, n = days[date]["day"], days[date]["night"]
        main = d or n
        out.append({"date": date, "name": main["name"],
                    "high": d["temp"] if d else None, "low": n["temp"] if n else None,
                    "pop": max((x["pop"] for x in (d, n) if x), default=0),
                    "code": main["code"], "is_day": bool(d), "short": main["short"]})
    return out


def normalize_hourly(periods: list[dict]) -> list[dict]:
    return [{k: v for k, v in _period(p).items() if k != "name"} for p in periods[:HOURLY_KEEP]]


def normalize_current(obs: dict | None) -> dict | None:
    if not obs:
        return None
    p = obs.get("properties") or {}
    t = _c_to_f(_val(p.get("temperature")))
    if t is None:
        return None
    feels = _c_to_f(_val(p.get("windChill")))
    if feels is None:
        feels = _c_to_f(_val(p.get("heatIndex")))
    code, is_day = icon_code(p.get("icon"), p.get("textDescription"))
    wind = _val(p.get("windSpeed"))
    return {"at": p.get("timestamp"), "temp": t, "feels": feels if feels is not None else t,
            "code": code, "is_day": is_day, "short": p.get("textDescription") or "",
            "humidity": _val(p.get("relativeHumidity")),
            "wind_mph": None if wind is None else wind / 1.609}


def _latest_obs(stations: list[str]) -> dict | None:
    for sid in stations:
        try:
            obs = _get(f"{API}/stations/{sid}/observations/latest")
        except Exception as e:
            log.info("NWS observation %s: %s", sid, e)
            continue
        cur = normalize_current(obs)
        if not cur:
            continue
        at = datetime.fromisoformat(cur["at"]) if cur.get("at") else None
        if at and datetime.now(timezone.utc) - at > timedelta(hours=2):
            continue
        cur["station"] = sid
        return cur
    return None


# --- cache ---------------------------------------------------------------------

def loc_key(lat: float, lon: float) -> str:
    return f"{float(lat):.4f},{float(lon):.4f}"


def _path(key: str) -> Path:
    d = cfg.DATA_DIR / "dashboards"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"wx-{key}.json"


_lock = threading.Lock()
_mem: dict[str, tuple[float, dict]] = {}   # key -> (mtime, entry)


def load(lat: float, lon: float) -> dict:
    """The cached entry: {"point", "data", "fetched_at", "error", "error_at"}
    (any may be missing). Never touches the network."""
    key = loc_key(lat, lon)
    path = _path(key)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return {}
    with _lock:
        hit = _mem.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        entry = json.loads(path.read_text())
        _mem[key] = (mtime, entry)
        return entry


def _save(key: str, entry: dict) -> None:
    path = _path(key)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(entry))
    tmp.replace(path)


def refresh(lat: float, lon: float) -> dict:
    """Fetch now and update the cache. On failure the last good data is kept,
    with the error recorded alongside it. Returns the entry."""
    key = loc_key(lat, lon)
    entry = dict(load(lat, lon))
    now = datetime.now(timezone.utc).isoformat()
    try:
        point = entry.get("point")
        if not point:
            point = resolve_point(float(lat), float(lon))
        try:
            daily = _get(point["forecast"])["properties"]["periods"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            point = resolve_point(float(lat), float(lon))   # grid moved: re-resolve
            daily = _get(point["forecast"])["properties"]["periods"]
        hourly = _get(point["forecast_hourly"])["properties"]["periods"]
        entry.update({"point": point, "fetched_at": now, "error": None, "error_at": None,
                      "data": {"daily": normalize_daily(daily), "hourly": normalize_hourly(hourly),
                               "current": _latest_obs(point.get("stations") or [])}})
        log.info("NWS %s (%s): %d daily, %d hourly", key, point.get("city"), len(daily), len(hourly))
    except Exception as e:
        log.warning("NWS refresh %s failed: %s", key, e)
        entry.update({"error": f"{type(e).__name__}: {e}", "error_at": now})
    _save(key, entry)
    return entry


# --- background refresher ------------------------------------------------------

_failures: dict[str, int] = {}
_next_try: dict[str, float] = {}


def refresh_due(locations: list[tuple[float, float]]) -> None:
    """Refresh each location whose data is older than REFRESH_S, backing off
    (1, 2, 4... up to REFRESH_S minutes) after failures."""
    for lat, lon in locations:
        key = loc_key(lat, lon)
        if time.time() < _next_try.get(key, 0):
            continue
        entry = load(lat, lon)
        fetched = entry.get("fetched_at")
        if fetched and (datetime.now(timezone.utc) - datetime.fromisoformat(fetched)).total_seconds() < REFRESH_S:
            continue
        entry = refresh(lat, lon)
        if entry.get("error"):
            n = _failures[key] = _failures.get(key, 0) + 1
            _next_try[key] = time.time() + min(REFRESH_S, 60 * 2 ** (n - 1))
        else:
            _failures.pop(key, None)
            _next_try.pop(key, None)


def refresh_async(lat: float, lon: float) -> None:
    threading.Thread(target=refresh, args=(lat, lon), name="nws-refresh", daemon=True).start()
