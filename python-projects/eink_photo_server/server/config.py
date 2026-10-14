"""Static configuration: environment settings + the device registry (devices.yaml).

Runtime state (battery, playlist cursor, last image, ...) lives in SQLite, not here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DEVICES_FILE = Path(os.environ.get("DEVICES_FILE", DATA_DIR / "devices.yaml"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# Base URL the frames use to reach us, e.g. http://192.168.20.5:8080. If unset,
# image URLs are built from the incoming request's Host header.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def parse_hhmm(s: str) -> time:
    h, m = str(s).split(":")
    return time(int(h), int(m))


@dataclass
class Device:
    id: str
    protocol: str
    pipeline: str
    width: int
    height: int
    token: str
    image_secret: str
    output_rotation: int = 0
    interval_minutes: int = 120
    wake_start: time | None = None
    wake_end: time | None = None
    tuning: dict = field(default_factory=dict)
    name: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Device:
        wake = d.get("wake_hours") or [None, None]
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            protocol=d["protocol"],
            pipeline=d["pipeline"],
            width=int(d["width"]),
            height=int(d["height"]),
            token=str(d["token"]),
            image_secret=str(d["image_secret"]),
            output_rotation=int(d.get("output_rotation", 0)) % 360,
            interval_minutes=int(d.get("interval_minutes", 120)),
            wake_start=parse_hhmm(wake[0]) if wake[0] else None,
            wake_end=parse_hhmm(wake[1]) if wake[1] else None,
            tuning=dict(d.get("tuning") or {}),
        )


@dataclass
class Config:
    tz: ZoneInfo
    devices: dict[str, Device]

    def by_secret(self, secret: str) -> Device | None:
        return next((d for d in self.devices.values() if d.image_secret == secret), None)


def load() -> Config:
    raw = yaml.safe_load(DEVICES_FILE.read_text()) if DEVICES_FILE.exists() else {}
    raw = raw or {}
    tz = ZoneInfo(raw.get("timezone") or os.environ.get("TZ") or "UTC")
    devices = {}
    for d in raw.get("devices") or []:
        dev = Device.from_dict(d)
        devices[dev.id] = dev
    return Config(tz=tz, devices=devices)


config = load()


def reload() -> Config:
    global config
    new = load()
    config.tz, config.devices = new.tz, new.devices
    return config
