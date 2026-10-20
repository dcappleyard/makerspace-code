# xiao_s3_sense_webcam

A LAN web camera on the **Seeed XIAO ESP32-S3 Sense**: a browser page with a
live stream you can turn on and off, snapshots, a gallery, and camera
controls (auto exposure, or manual exposure and gain).
- **Hardware:** XIAO ESP32-S3 Sense: 8 MB flash, 8 MB PSRAM, and the camera + microSD expansion board. See `../hardware_info.md`.
- **Optional screen:** a 1.28" round touch display stacked on top gives a tap-to-wake live preview (see [Round display](#round-display)).
- **Storage:** snapshots go to the SD card as `/photos/YYYY-MM-DD_HH-MM-SS.jpg`. With no card they're kept in RAM for now, and moved onto a card when one turns up.

## Setup

1. **Fill in `include/secrets.h`.** Copy `include/secrets.h.example` to `include/secrets.h` (it's gitignored) and set `WIFI_SSID` / `WIFI_PASSWORD`.
2. **Optional: insert a FAT32 microSD card** into the Sense board. The firmware creates `/photos/` itself.
3. **Flash:**
   ```
   pio run -t upload
   ```
4. **Open the page.** Go to `http://xiao-cam.local/`, or the IP printed on the serial monitor. The serial log at boot shows:
   - the sensor model (OV2640 / OV3660)
   - SD card state
   - the URL

## Using it

| | |
|---|---|
| **Start / Stop live stream** | MJPEG from `http://<cam>:81/stream`. Stopping closes the connection, so the camera only streams while someone is watching. **One viewer at a time**: the stream occupies its server task, so a second viewer waits until the first stops. |
| **Take snapshot** | Captures a fresh frame at the current resolution and settings, whether or not the stream is on. With the stream off, the photo shows in the viewer. |
| **Gallery** | Newest first. Click a photo to view it full size, download it or delete it. Photos marked **temporary** are in RAM. |
| **Re-check SD card** | Remounts the card, e.g. after you insert one. Any RAM photos are written to it. The firmware doesn't poll for card insertion; if a write to the card fails (card pulled), it switches to RAM until you re-check. |
| **Camera settings** | Every change applies immediately, is saved in NVS, and survives a reboot. **Reset to defaults** clears the saved settings. |

### Snapshot names and storage

- **With a card:** `/photos/2026-10-19_14-03-22.jpg`. Two in the same second get `-2`, `-3`, … appended.
- **Before NTP has set the clock** (no WiFi/internet yet): `nodate_<uptime-ms>.jpg`. The page warns about this.
- **No card:** up to 20 photos or 4 MB in PSRAM, oldest dropped first, all **lost on reboot**. They're written to the card at the next successful mount. Limits are in `src/cam_config.h`.

### Exposure and image controls

| Group | Controls |
|---|---|
| Image | Resolution (up to the sensor's max, capped at QXGA), JPEG quality (lower = better/bigger) |
| Exposure | **Auto exposure** on: AE level −2…+2, night mode (DSP AEC). Off: manual **Exposure** 0–1200 |
| Gain | **Auto gain** on: gain ceiling 2×–128×. Off: manual **Gain** 0–30 |
| Colour | Auto white balance (+ AWB gain, WB mode), brightness, contrast, saturation |
| Orientation | Mirror, flip, lens correction |

Manual sliders are greyed out while their auto mode is on. If the sensor driver rejects a setting, the page shows the error.

Large resolutions lower the stream frame rate. Pick a smaller size for a smooth live view, and a larger one before taking a snapshot.

## Round display

The [1.28" Round Touch Display for XIAO](https://www.seeedstudio.com/1-28-Round-Touch-Display-for-Seeed-Studio-XIAO-ESP32.html) plugs onto the XIAO's headers, with the Sense camera/SD board still on the back. The firmware works with or without it attached.

| Screen state | What a tap does |
|---|---|
| **Off** (normal) | Wakes the screen into a **live camera preview** |
| **Preview** | Shows **"Turn screen off?"**, with **Yes** on the left half and **No** on the right |
| **Yes / No prompt** | Yes turns it off; No goes back to the preview. With no answer, it returns to the preview after 10 s |

- **Auto-off:** the screen also turns off after **2 minutes** with no touch.
- **Settings:** the timeouts are in `src/cam_config.h`.
- **Held finger:** counts as one tap.
- **Display only:** the screen just shows the camera. It doesn't take snapshots or change settings, which stay in the web page; mirror and flip set there apply to the preview too.

**Before you start:** set the display's **KE switch to ON**. Without it, GPIO43 can't switch the backlight (Seeed wiki).

**Expect a quick flash at boot.** The display library turns the backlight on during init, and the firmware turns it straight back off.

**If the preview looks wrong:**
- Blue and orange swapped: flip `PREVIEW_SWAP_BYTES` in `src/cam_config.h`.
- Rotated: change `DISPLAY_ROTATION` (0–3) in the same file. The touch halves follow the rotation.

**Frame rate:**
- Expect a few frames per second, depending on the resolution.
- Each preview frame is decoded at ½, ¼ or ⅛ scale, whichever still covers the 240 px circle, then centre-cropped.
- If the web stream is open at the same time, the two share the camera's frames, so both slow down.

**Shared SPI bus.** The display's LCD and the Sense SD slot use the same SCK/MISO/MOSI pins (GPIO 7/8/9).
- Seeed_GFX runs the LCD on its own SPI peripheral (HSPI), and two peripherals can't drive the same pins.
- So the SD card is mounted on the display's SPI instance (`screenSpi()` in `src/screen.h`), and `setupScreen()` must run before `mountSd()`.
- The SPI driver's transaction lock keeps the display (drawn from `loop()`) and the SD card (used by the web-server task) from overlapping.
- The display's own microSD slot (CS GPIO3) is held deselected and unused.

## API

The page uses these, and they're handy from `curl` too. State changes are POST-only.

| Method | Path | |
|---|---|---|
| GET | `/` | the page |
| GET | `/api/status` | sensor, settings, IP, clock, SD/RAM state, free PSRAM |
| POST | `/api/control?var=<name>&val=<int>` | set one control (names as in `/api/status` → `settings`) |
| POST | `/api/reset` | back to default settings |
| POST | `/api/snap` | take a snapshot → `{"name","size","sd","dated"}` |
| GET | `/api/photos` | `[{"name","size","sd"}]`, newest first |
| GET | `/photo?name=<name>` | the JPEG |
| POST | `/api/photos/delete?name=<name>` | delete one |
| POST | `/api/sd/mount` | re-check the card, move RAM photos → `{"sd","moved"}` |
| GET | `:81/stream` | MJPEG stream (`?t=<token>` when auth is on) |

```
curl -X POST http://xiao-cam.local/api/snap
```

## Authentication

Off by default. To turn on HTTP Basic Auth, uncomment `WEB_AUTH_USER`/`WEB_AUTH_PASS` in `secrets.h`. This is a bar against casual access, not real security: it travels in near-cleartext over plain HTTP.

The stream on port 81 can't use Basic Auth, because browsers won't prompt for credentials on a cross-port `<img>`. Instead it takes a random per-boot token, which the authenticated page reads from `/api/status`.

## Why esp_http_server (not WebServer.h like the siblings)

The other projects here use the synchronous `WebServer.h`, serviced from `loop()`. An MJPEG stream never finishes, so on that server it would lock out every other request.

This project uses ESP-IDF's `esp_http_server` instead. It runs two instances, each on its own task, the same pattern as the core's CameraWebServer example:
- port 80 for the page and API
- port 81 for the stream

Snapshots and setting changes therefore keep working while someone watches. Storage is only touched from the port-80 task, so it needs no locking (see `src/storage.h`).

## Source layout

```
src/cam_config.h     pins (camera, SD), storage limits, clock, network constants
src/camera.{h,cpp}   esp32-camera init, sensor detection, settings table + NVS persistence
src/storage.{h,cpp}  SD mount/remount (on the display's SPI bus), /photos, RAM fallback store, naming
src/screen.{h,cpp}   round display: touch, off / preview / Yes-No states, JPEG-decoded preview
src/web.{h,cpp}      the two HTTP servers, API handlers, MJPEG stream, auth
src/index_html.h     the single-page UI (embedded; no filesystem partition needed)
src/main.cpp         setup/loop, WiFi/mDNS/NTP, screen service
lib/driver/driver.h  Seeed_GFX screen selection (BOARD_SCREEN_COMBO 501 = round display)
```

## Verified vs. unverified

**Verified on hardware:** the camera, stream, snapshots and web page (before the round display was added).

**Verified:** with the round display support added, it builds clean at 35.6% flash (1,190,602 of 3,342,336 bytes) and 21.1% RAM, both with and without auth enabled.

**Round display, not yet run on hardware.** Check, in order:
- **Boot:** the screen flashes, then goes dark.
- **Shared bus:** the web page still works, and a snapshot still lands on the SD card. If SD broke, the shared bus is the suspect.
- **Wake:** a tap brings up the preview. Check its colours and orientation (see above).
- **Prompt:** a second tap shows Yes/No. No goes back to the preview; Yes turns it off. Left alone, it returns to the preview after 10 s.
- **Auto-off:** with no touch for 2 min, the screen turns off.
- **Everything at once:** the preview, the web stream and a snapshot all work together.

**Original checklist** (done for the camera and web page):
- **Boot log:** sensor detected, PSRAM found, SD state, IP.
- **Stream:** start and stop it; the serial log prints `Stream started` / `Stream stopped`.
- **Snapshot without a card:** shows as temporary. Then insert a card and click **Re-check SD card**: it moves to `/photos/` under its date-time name.
- **Exposure:** turn auto exposure off, drag Exposure, and see the image change. Reboot and confirm the settings came back.
- **Highest resolution:** a snapshot comes out whole, not truncated. The frame buffers are sized at init for QXGA; see `INIT_FRAMESIZE` in `camera.cpp`.
- **Heat:** the board runs hot when streaming continuously; see `../hardware_info.md`.
