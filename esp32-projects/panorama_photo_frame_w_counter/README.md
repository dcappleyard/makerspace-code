# panorama_photo_frame_w_counter

A battery-powered panorama photo frame on the XIAO ePaper DIY Kit EE03 (10.3" panel).
Same board/display as `../ee03-text-test`, `../test_bw_image_eink`, and
`../wifi_counter_eink` — see `../hardware_info.md`. See `DESIGN.md` for the full
design rationale and the decisions behind this project's architecture.

Cycles between panorama photos on a timer (default every 2 hours), with one button
forcing an immediate refresh/cycle and two other buttons adjusting a persistent
counter that's shown as a text overlay but never drives image cycling itself.
Deliberately has no WiFi, to save battery — this device spends almost all its time in
deep sleep.

## One-time setup: `mklittlefs`

This is the first project in `esp32-projects/` to use `board_build.filesystem`, and
the `Seeed-Studio/platform-seeedboards` fork doesn't pull in a `mklittlefs` binary the
way upstream `platform-espressif32` does — `pio run -t uploadfs`/`buildfs` will fail
with `mklittlefs: command not found` (or, on Apple Silicon without Rosetta installed,
`Bad CPU type in executable` if PlatformIO's own `tool-mklittlefs` package resolves to
an x86_64-only build). Fix: `brew install mklittlefs` (arm64-native on macOS) and make
sure `/opt/homebrew/bin` is on `PATH` before running `pio run -t uploadfs`.

## Workflow

1. Produce source images with
   `python-projects/grayscale_image_conversion/prepare_image.py` at its defaults
   (4-bit depth, 1872x1404 — matches this panel's native resolution and already
   produces the right panorama-on-white-canvas letterboxing with no extra flags).
2. Pack them into raw binaries for LittleFS (unlike `../test_bw_image_eink`, images
   here are **not** compiled into flash — see `DESIGN.md` for why):
   ```
   pip install -r tools/requirements.txt   # first time only
   python3 tools/pack_images.py ~/Pictures/test_1.png ~/Pictures/test_2.png
   ```
   This writes `data/images/img_00.bin`, `data/images/img_01.bin`, ... and
   `data/images/manifest.txt` (display order + original filenames). Pass images in
   the order you want them cycled.
3. Upload the filesystem image, then the firmware:
   ```
   pio run -t uploadfs
   pio run -t upload
   ```
   Re-run step 3's `uploadfs` any time you re-run `pack_images.py` with different or
   additional photos — the firmware itself doesn't need rebuilding for that.
4. On first boot, open the serial monitor. The device will ask for the current time:
   run `date +%s` on your computer, paste the number, and press Enter within 20
   seconds (or just press Enter to skip and set it later). This is a **manual** clock
   — there's no WiFi/NTP and no external RTC module, so it needs re-setting after any
   genuine power loss (battery pull, not deep sleep — deep sleep keeps the clock
   running).

## Buttons

Same GPIO pins as the other EE03 projects in this repo (2, 3, 5):

| Button | Action |
|---|---|
| GPIO2 | Force an immediate refresh — advances to the next image and redraws the whole panel (including the text overlay) |
| GPIO3 | Counter +1 |
| GPIO5 | Counter -1 |

Counter changes persist to NVS immediately, but **the display is not redrawn** for a
counter press — the on-screen counter value only updates at the next scheduled or
forced refresh. This avoids a multi-second full-panel flash on every button press,
since 4bpp gray-mode images can't use the panel's fast partial refresh (see
`../wifi_counter_eink/README.md`'s finding on that).

## Storage architecture

Images live in a LittleFS partition, not compiled into firmware — see `DESIGN.md` for
the full partition table and rationale. The short version: `../test_bw_image_eink`
found that two full-panel images compiled into flash already reach 89.5% of the app
partition, with no room left for a third image or for this project's extra logic
(deep sleep, NVS, RTC). LittleFS keeps images off the app partition entirely, and
reading them via `LittleFS.open()`/`File::read()` is the same code path a future SD
card would use — swapping in a physical SD card later should mean changing the mount
call, not rewriting the image-loading logic.

## Power / sleep behavior

The device does essentially all of its work once per boot, then calls
`esp_deep_sleep_start()` — `loop()` is never actually reached. It wakes via:
- **Timer**: the refresh interval (`REFRESH_INTERVAL_SEC` in `src/main.cpp`, default
  2 hours) — advances to the next image.
- **GPIO2 (ext1 wake)**: same as a timer wake, but immediate.
- **GPIO3/GPIO5 (ext1 wake)**: counter-only — adjusts and persists the counter, then
  goes back to sleep for whatever time remains until the *original* scheduled
  refresh (a counter press never resets or extends the refresh countdown).

## Verified vs. unverified

Nothing here has been run on physical hardware yet — this is a from-scratch build,
not an iteration on a working version. Specific things to check first (see
`DESIGN.md`'s Verification section for the full list):

- **Partition table**: sums to exactly 8MB on paper; needs `pio run` to confirm no
  overlap/build error, and to see actual app-partition fill % once compiled.
- **`epaper.sleep()`/`begin(wake)`**: no sibling project in this repo has ever called
  `sleep()` or a non-default `begin()` — every existing working example just calls
  plain `epaper.begin()`. This project calls `epaper.sleep()` before deep sleep and
  plain `epaper.begin()` (full init) on every wake; confirm this doesn't leave the
  panel in a bad state.
- **Sense-board deep-sleep current draw**: community reports (Seeed/Arduino forums)
  suggest the XIAO ESP32-S3 **Sense** variant's camera/mic expansion board can draw
  much more current in deep sleep than the base module's ~14µA spec, unless it's
  explicitly powered down. No code here does that. If real battery-life measurements
  come back high, the fallback is investigating a power-down sequence or physically
  unplugging the stackable Sense expansion board.
- **RTC across power loss**: expected to survive deep sleep but not a real power
  cycle — needs confirming on hardware, along with the serial time-set window only
  appearing on that cold-boot path (not on every timer/button wake).
- **Simultaneous button presses**: GPIO2 is coded to take priority if pressed
  alongside GPIO3/5, but this hasn't been exercised physically.
