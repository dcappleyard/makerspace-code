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
it is. A frame on a network without internet access may not be able to correct
its clock. The server's **Wake timing → Apply measured** compensates for steady
drift.

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
.venv/bin/python bloomin8_tool.py pull living_room_73
```
