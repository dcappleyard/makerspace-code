# xiao_s3_ee04_pullframe

A battery-powered **pull client of the eink_photo_server**
(`python-projects/eink_photo_server/`). It runs on the Seeed **XIAO ePaper Display Board EE04** (XIAO ESP32-S3 Plus) with the **4.26" 800×480 black/white** panel. For hardware details and the pin map, see `../hardware_info.md`.

- **What the server does:** picks the photo and when to check next, then fits, tunes, dithers to 1-bit and packs it (`ee04_bw1` pipeline).
- **What this firmware does:** wakes, asks the server, downloads and draws when the image is new, and goes back into deep sleep.

For why it works this way and what was left out compared with the EE03 frame, see [DESIGN.md](DESIGN.md).

**Two frames, one source tree.** There are two of these boards. `platformio.ini` has an environment per board, `frame1` and `frame2`, which differ only in `FRAME_SLOT` (which picks that frame's token in `secrets.h`) and the hostname. Always name the board you're flashing with `-e`. Label the boards physically; the serial log's first line shows the env's hostname and the board's MAC, and the server logs the MAC on the frame's tab.

## Hardware setup

1. Seat the panel's ribbon in the EE04's **24-pin** FPC connector, and set the FPC jumper to **24 Pin**.
2. Connect a LiPo to the JST 2.0 connector and turn the power switch on. USB-C charges it.

## Setup

1. **Add each frame on the server.** In `data/devices.yaml`, add one entry per frame with `protocol: esp32_pull`, `pipeline: ee04_bw1`, `width: 800` and `height: 480`. `devices.example.yaml` has a `desk_bw` example. Use `battery_monitor: low` or `none`, not `always` (the server README explains why). Give each its own random `token` and `image_secret` (`python3 -c "import secrets; print(secrets.token_urlsafe(24))"`), then click **Reload devices.yaml**.
2. **Fill in `include/secrets.h`.** It's gitignored, and a copy of `secrets.h.example` with placeholders is already in place. Set:
   - `WIFI_SSID` and `WIFI_PASSWORD`
   - `SERVER_URL`, e.g. `http://192.168.30.10:8080`
   - the `DEVICE_TOKEN` under `FRAME_SLOT == 1` and `== 2`: each frame's server `token`
3. **Flash and watch**, naming the board:
   ```
   pio run -e frame1 -t upload
   pio device monitor -e frame1
   ```
   and `-e frame2` for the other. A bare `pio run -t upload` flashes `frame1` (the default env).
   Within a few seconds the frame pulls, downloads and draws. The server's frame tab logs the pull, with the battery reading, and the confirmation.

## How it runs

| | |
|---|---|
| Each wake | Read the battery (before WiFi loads it), connect, pull, and on `show` download → verify → draw → signal. Then deep sleep |
| Next wake | After the server's `next_check_s` (minus the time spent awake), on the ESP32's RTC sleep timer |
| `keep` / `none` | No download, no panel refresh. The panel isn't even powered |
| Server or WiFi down | The panel keeps the last image. Retries come after 5, 15 and 30 min, then hourly |
| Battery below 3.30 V | No WiFi; sleep 12 h. Skipped while a USB host is attached |
| What survives sleep | The current image name, the server's `next_check_at`, the failure count, and the last AP's BSSID and channel (a fast reconnect with no scan). Kept in RTC memory |
| Cold boot (reset, power-on, reflash) | RTC memory is cleared, so the frame doesn't claim a current image. The server answers `show` and the frame redraws |

**Staying awake for development:** deep sleep drops the USB port. After a cold boot the frame stays awake for **2 minutes**, and for as long as a computer (a USB host) is attached. While awake it runs the same cycle on a `millis()` countdown. So to reflash: press **RESET**, then upload, or just upload while plugged into the computer. A plain USB charger doesn't keep it awake.

**Buttons:** KEY0–2 do nothing yet. RESET forces a fresh pull (a cold boot).

## Battery reading

The frame reads the voltage on A0 (GPIO1). GPIO6 switches the divider in, and is held LOW in sleep. It uses Seeed's scaling, `raw / 4096 × 7.16`, and converts to % with a resting-LiPo curve in `power.cpp`. Each pull sends `battery=<%>&battery_mv=<mV>`. To calibrate, compare `Battery … mV` in the serial log with a multimeter across the cell, and set `BATTERY_CAL` in `frame_config.h` to measured ÷ reported.

## Wake timing

The ESP32-S3's sleep timer runs off an internal RC oscillator, so wakes drift by roughly 1%: about a minute on a 2-hour interval. The server handles that with:
- **Early wakes:** a wake up to 60 min early counts as its slot.
- **Wake offset:** the frame tab's **Wake timing** card shows the median drift. **Apply measured** cancels it.

## Source layout

```
src/frame_config.h   geometry, battery, timing and wake constants
src/power.{h,cpp}    RTC-memory state, battery reading, stay-awake rule, deep sleep
src/pull.{h,cpp}     the esp32_pull exchange: pull, download+verify, draw, signal
src/main.cpp         wake cycle: battery → WiFi → pull → sleep (or stay awake)
```

## Status

**Verified on hardware (2026-11-25):**
- The connection test pattern from the first version drew correctly with the jumper on 24 Pin, which confirms the pin map and orientation.

**Pull client:** builds clean at 33.2% flash, 14.4% RAM. The server side (`ee04_bw1` and the battery parameters) was tested with a simulated client. **Not yet run on hardware.** Check, in order:
- First boot: pull → download → draw → the server log shows the signal and the battery reading.
- Is the image the right way round? It's copied straight into the same buffer the test pattern used, so it should be.
- Unplug USB: does the frame sleep and wake on schedule, getting `keep` with no refresh when nothing changed?
- Sleep current: measure it. Panel power (GPIO43) and the battery divider (GPIO6) are held LOW in sleep. Neither has been measured yet.
- Stop the server: the last image stays, and the retries back off.
- Check the battery reading against a multimeter.
