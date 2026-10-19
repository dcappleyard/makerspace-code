# Design: EE03 frame as an eink_photo_server pull client

## Why

`../panorama_photo_frame_web` made the EE03 frame self-managing: photos were
prepared on a computer with `prepare_image.py` and uploaded to the device, and
the firmware cycled them and drew the captions. The eink_photo_server now does
all of that for every frame (Bloomin8s included): one library, per-frame
playlists and daily schedule blocks, per-photo `.xml` sidecars with tags, a wake
log. Feeding the EE03 from it means one place to manage photos instead of two.

## Decisions

**The server renders everything.** The `ee03_gray16` pipeline is a server-side
port of `prepare_image.py`:
- panorama strip on a white canvas
- 16-gray Floyd–Steinberg dither
- nibble-packing

It also draws the caption from the photo's sidecar, which `drawTextOverlay()` used to do on the device. Captions became a generic server step so any frame can have them. The firmware is left with "download bytes, push bytes". The counter header and the IP corner are gone with it.

**Kept from the web version:**
- the display path (`pushImage` + full gray `update()` + the 3 s settle gate)
- the SD wiring and its 20 MHz clock
- the single-task `loop()` and the `millis()`-only deadlines
- bounded WiFi connect with background reconnect, and NTP (now only for display)
- the opt-in auth seam

**Dropped**, as chosen when this was planned:
- the buttons, counter, `counter_track.txt` and its History pages
- the upload and photos pages, and `frame_config.xml`

The schedule now lives on the server, so `refresh_hours` went too.

**Downloads are all-or-nothing**, like uploads were. The image streams to a temp file and is only renamed into `/cache/` after the exact-length and SHA-256 checks pass. A truncated buffer would draw garbage, which is worse than keeping the old image.

**"keep" saves a refresh.** The frame reports the image it shows. When the server's choice is the same, it answers `keep`: no download, and no multi-second full-panel flash. At boot the frame deliberately doesn't report one, because a reflashed panel may show something stale.

**Offline mode instead of a blank frame.** A Pi reboot or a network outage shouldn't freeze the frame on one image indefinitely. After three failed pulls it cycles its cache every 2 hours, while still retrying the server every 5 minutes. The next successful pull ends offline mode.

**The status page is read-only plus "Pull now".** The single POST exists because the server can't push: without it, testing a change means waiting for the next scheduled check.

## Rejected or deferred

- **Server push / long-polling:** the pull model is shared with the battery frames, and a mains frame polling on the server's schedule costs nothing.
- **Verifying cache hits by SHA-256 before drawing:** files only enter the cache verified, and the name includes the server's content key.
- **OTA updates:** the partition table still reserves `app1`, as in the web version, but OTA isn't implemented.
