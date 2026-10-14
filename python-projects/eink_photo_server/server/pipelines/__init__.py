"""Pipeline registry.

Every module in this package is imported at startup; modules register their
pipeline with @register. To add one: drop a new module here, decorate the class,
and reference its `name` from devices.yaml.
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import Pipeline

_registry: dict[str, Pipeline] = {}


def register(cls):
    _registry[cls.name] = cls()
    return cls


def get(name: str) -> Pipeline:
    if name not in _registry:
        raise KeyError(f"unknown pipeline {name!r} (have: {', '.join(sorted(_registry))})")
    return _registry[name]


def names() -> list[str]:
    return sorted(_registry)


for _m in pkgutil.iter_modules(__path__):
    if _m.name != "base":
        importlib.import_module(f"{__name__}.{_m.name}")
