"""Protocol adapters: how a kind of frame asks for its next image.

Each module exposes a FastAPI `router` and a `PROTOCOL` name that devices.yaml
refers to. Add a module here and list it in ROUTERS.
"""
from . import bloomin8

ROUTERS = {bloomin8.PROTOCOL: bloomin8.router}
