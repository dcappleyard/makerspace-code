# frame_tool

`bloomin8_tool.py` is a small local web page (or command line) for the Bloomin8 frames
listed in the server's `devices.yaml`. It can:

- **Probe** each frame: battery, play mode, whether pull is on and to where, the
  next wake, and its **clock skew** against this machine.
- **Pull now:** arm pull mode for this server with the first pull about 90 s
  ahead **by the frame's own clock**, so it works even when that clock has
  drifted. It also switches the frame to single-image mode, so its own
  slideshow can't overwrite pulled images. Use this to recover a frame that
  has dropped out of pull mode, or to set up a new one.

There's no API to *set* a Bloomin8's clock, so the tool only shows how far off
it is. The server doesn't need it set: it learns each Bloomin8's clock offset
from its pulls and sends wake times on the frame's own clock (the frame's
**Frame clock** card in the server UI). **Pull now** is how the server first
learns it, so use it after setting up or resetting a frame.

Run it on a machine that can reach the frames' network. On this setup that's
the Mac; the Pi can't reach the IoT VLAN.

## Setup (Mac)

The only dependency is PyYAML. The page is served by the standard library and
opens in your browser; it's not a Tk window, because the macOS system Tk draws
blank windows. Any Python 3.9+ works; this uses `/usr/bin/python3`:

```bash
cd python-projects/eink_photo_server/frame_tool && /usr/bin/python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Copy the server's `devices.yaml` from the Pi. In it, add a top-level
`server_url` (the server as the frames reach it) and a `frame_ip` for each
Bloomin8. The server ignores both keys, so the same file works on the Pi:

```yaml
server_url: http://192.168.30.10:8080
devices:
  - id: living_room_73
    protocol: bloomin8
    token: ...
    frame_ip: 192.168.20.219
```

Give each frame a fixed IP in UniFi so `frame_ip` stays right.

## Use

```bash
.venv/bin/python bloomin8_tool.py --devices ~/eink-data-copy/devices.yaml
```

This opens the page in your browser, served on `127.0.0.1` only (`--port` to
pick the port); Ctrl-C in the terminal stops it. The file is remembered after
the first run, in `~/.bloomin8_tool.json`; to switch files, edit the path at
the top of the page and click **Load**.

- **Selecting frames:** tick rows for **Probe** / **Pull now**. With nothing
  ticked, they act on every frame.
- **Sleeping frames:** wake a sleeping frame first (its button or the Bloomin8
  app). **Pull now** waits up to 60 s for it to answer.

The same actions work from the command line:

```bash
.venv/bin/python bloomin8_tool.py status            # all frames
.venv/bin/python bloomin8_tool.py status -v         # + the requests (as curl), raw replies, both clocks
.venv/bin/python bloomin8_tool.py pull living_room_73
.venv/bin/python bloomin8_tool.py off living_room_73      # pull mode off; keeps its image
.venv/bin/python bloomin8_tool.py reboot living_room_73   # restart, wait, re-probe the clock
```

Every **Probe** on the page also writes the requests it sent (as `curl`
commands), the frame's raw JSON replies, and the frame's clock next to this
machine's, to the log at the bottom. Tokens are shown as their last 4
characters only, so the output is safe to paste.

**Reboot** (`POST /reboot`) restarts the frame, waits up to 2 minutes for it
to answer again, and logs the clock skew before and after. A restart is the
frame's most likely moment to resync its clock, so it's the quickest way to
check whether it can reach an NTP server.

**Pull off** turns pull mode off on the frame, keeping its server URL and
token, so it stops calling the server and keeps showing its current image.
Use it to park a misbehaving frame, for example one whose clock is so far off
that every wake time the server gives it is already in its past, so it pulls
again every minute or two. **Pull now** turns pull mode back on.
