# xiao_s3_ee03_pull_frame

The EE03 10.3" panorama frame as a **pull client of the eink_photo_server**
(`python-projects/eink_photo_server/`).
- **Hardware:** XIAO ESP32-S3 Plus, 1872×1404 16-gray panel, SD-card mod. This is the same unit `../panorama_photo_frame_web` runs on; see `../hardware_info.md`.
- **What the server does:** chooses what to show and when (playlists and schedule blocks), renders the caption, dithers, and packs the panel buffer.
- **What this firmware does:** asks for the next image, downloads it, and pushes it to the panel.

Why this exists, and what was dropped from the web version: see [DESIGN.md](DESIGN.md).

## Setup

1. **Add the frame on the server.** In its `data/devices.yaml`, add an entry with `protocol: esp32_pull` and `pipeline: ee03_gray16`; `devices.example.yaml` has an `office_panorama` example. Give it its own random `token` and `image_secret`, then click **Reload devices.yaml**. The frame gets its own tab for its playlist, schedule and log.
2. **Fill in `include/secrets.h`.** Copy `include/secrets.h.example` to `include/secrets.h` (it's gitignored). Set:
   - `WIFI_SSID` and `WIFI_PASSWORD`
   - `SERVER_URL`: the server as the frame reaches it. Use an IP, e.g. `http://192.168.30.10:8080`.
   - `DEVICE_TOKEN`: the same value as the server entry's `token`.
3. **Prepare an SD card.** Insert a FAT32-formatted card. The firmware creates `/cache/` itself; nothing needs to be on the card.
4. **Flash:**
   ```
   pio run -t upload
   ```
5. **Check it.** Watch the serial monitor, or open `http://ee03-frame.local/` (or the IP from the serial log). Within a few seconds of WiFi coming up, the frame pulls, downloads its first image and draws it. The server's frame tab logs the pull, the download and the confirmation.

## How it runs

| | |
|---|---|
| Next check | Whenever the server says (`next_check_s`, from the frame's schedule blocks + wake offset), measured with `millis()` |
| `show` | The image is streamed to `/cache/.download.tmp`, length (1,314,144 bytes) and SHA-256 checked, renamed into `/cache/`, drawn, then confirmed to the server |
| `keep` | The frame already shows the right image -- no download, no panel refresh |
| Cache hit | If the server picks an image already in `/cache/`, it's drawn straight from the card |
| Server unreachable | Retry every 5 min; after 3 failures in a row, **offline mode**: cycle the cached images every 2 h until the server answers again |
| Cache size | Newest 60 images kept (~80 MB), older ones pruned |

The frame always asks for a fresh decision at boot (e-paper keeps its image
with no power, so what's on the panel after a reflash may not be ours).

## Status page

`http://ee03-frame.local/` (read-only) shows:
- what's showing
- the last pull and its result
- the countdown to the next check
- offline mode, if it's on
- cache count and SD free space
- the clock, WiFi, uptime and heap

`/status.json` has the same data. **Pull now** (a POST) asks the server right away; it's handy after changing the playlist or using "Show next" on the server.

There's no authentication by default; the page only exposes status plus that
one button. To turn on HTTP Basic Auth, uncomment `WEB_AUTH_USER`/`WEB_AUTH_PASS` in
`secrets.h`.

## Source layout

```
src/frame_config.h   pins, geometry, timing constants (MUST be the first include -- FS.h order)
src/storage.{h,cpp}  SD mount, /cache listing/pruning, image loading
src/pull.{h,cpp}     the server protocol: pull, download+verify, signal, offline cycling
src/web.{h,cpp}      status page, status.json, POST /pull-now
src/main.cpp         setup/loop, WiFi/NTP, display state machine
```

## Verified vs. unverified

**Verified:** it builds clean at **29.1% flash (1,222,450 of 4,194,304
bytes) and 16.6% RAM**. The server side (the `esp32_pull` protocol, the
`ee03_gray16` pipeline, captions) was tested end to end with a simulated client.
The pipeline's output matches `prepare_image.py` to within 0.4/255 average tone.

**Not yet run on hardware.** Check, in order:
- **First boot:** pull → download → draw → the server log shows the signal.
- **Next scheduled check:** a different image, or `keep` with no refresh.
- **Pull now**, and **Show next** on the server followed by Pull now.
- **Server stopped:** 3 failures → offline mode → cached images cycle. Then start the server again: the frame recovers on the next retry.
- **Interrupted download:** pull the network mid-download. Nothing lands in `/cache/`, and the next pull retries.
- **Long soak:** ghosting over many refreshes, and min free heap. Same open questions as `../panorama_photo_frame_web`.
