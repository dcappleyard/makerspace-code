"""Minimal WLED JSON API client (stdlib only)."""
import json
import urllib.request


class WLED:
    def __init__(self, host, timeout=3.0):
        self.base = f"http://{host}"
        self.timeout = timeout

    def _req(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")

    def info(self):
        return self._req("/json/info")

    def state(self):
        return self._req("/json/state")

    def set_state(self, **fields):
        """POST /json/state, e.g. set_state(on=True, bri=128) or set_state(ps=3)."""
        return self._req("/json/state", fields)

    def on(self, bri=None):
        return self.set_state(on=True, **({} if bri is None else {"bri": bri}))

    def off(self):
        return self.set_state(on=False)

    def preset(self, preset_id):
        return self.set_state(ps=preset_id)
