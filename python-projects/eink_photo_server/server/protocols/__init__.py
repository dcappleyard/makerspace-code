"""Protocol adapters: how a kind of frame asks for its next image.

Each module exposes a FastAPI `router` and a `PROTOCOL` name that devices.yaml
refers to. Add a module here and list it in ROUTERS. Shared pull logic and the
/image route live in common.py.
"""
from . import bloomin8, common, esp32_pull

ROUTERS = {bloomin8.PROTOCOL: bloomin8.router, esp32_pull.PROTOCOL: esp32_pull.router}
SHARED_ROUTER = common.router
