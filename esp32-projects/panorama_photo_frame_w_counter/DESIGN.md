# Panorama e-ink photo frame (EE03 + XIAO ESP32-S3 Sense)

Project directory: `esp32-projects/panorama_photo_frame_w_counter/`. This file is a
copy of the plan that was approved before building this project, kept here so the
design rationale lives alongside the code rather than only in a local Claude Code
plan file.

> **Update — SD-card storage + metadata (supersedes the LittleFS design below).**
> Once the SD-card mod was proven working (`../eink_sd_test`), image storage moved
> off LittleFS onto the SD card. What changed vs. the original plan:
> - Images + a per-photo `.xml` metadata sidecar are now read from the card's
>   `/pictures/` directory (mounted via `SPIClass(FSPI)` → SPI2_HOST, separate from the
>   panel's SPI3_HOST). No `LittleFS`, no `manifest.txt`, no `pio run -t uploadfs`;
>   photos cycle in `.bin` filename order. `tools/pack_images.py` and `data/images/`
>   are retired — the nibble-packing is folded into `prepare_image.py`, which now also
>   prompts for metadata and writes the `.xml` sidecar.
> - `/frame_config.xml` holds runtime settings read on each refresh: `<refresh_hours>`
>   (default 2 h, replacing the firmware `constexpr`) and `<counter>` — the counter now
>   lives on the SD card, not NVS. Its boot value comes from `<counter>`, and each GPIO
>   counter press rewrites that value in place (preserving the rest of the file).
> - The photo metadata field formerly prompted as "Short description" is now **Title**
>   (`<title>` in the per-photo sidecar; `prepare_image.py` prompts "Title").
> - Text overlays (all mid-grey `TFT_GRAY_8`, transparent so the image shows through):
>   header above the strip is font 2 with the counter left (a top-right battery
>   placeholder was tried, then removed pending real battery sensing). Caption below
>   is bottom-aligned with a font-2 left run
>   `Title · Location · Film` (hand-drawn centered-dot separators) and a font-4 right run
>   `Artist ‡ Date` (hand-drawn double dagger) — the built-in fonts are ASCII-32-127 only,
>   so those separators are drawn as primitives.
> - Every counter change appends a timestamped line to `/counter_track.txt` on the card.
>
> The photo geometry, deep-sleep/wake architecture, manual serial clock, and
> deferred-counter-redraw behavior are unchanged from the design below (though the
> counter moved out of the NVS schema into `frame_config.xml`). See `README.md` for the
> current workflow.

## Context

The user wants the first "real" (non-demo) e-ink project in `esp32-projects/`: a
battery-powered panorama photo frame on the existing Seeed XIAO ESP32-S3 Sense +
EE03 10.3" monochrome e-paper panel (1872x1404, 16 gray levels). It pairs with the
existing `python-projects/grayscale_image_conversion/prepare_image.py` tool. Photos
are fixed ~6:17 (h:w) panoramas, letterboxed onto the full panel canvas with white
space above/below. To start there are only two images
(`~/Pictures/test_1.png`/`test_2.png`), cycling on a timer (e.g. every 2 hours), with
one button forcing an immediate refresh/cycle and two other buttons
incrementing/decrementing a persistent counter (display-only, not tied to image
cycling). No WiFi, to save battery. An SD card for more image storage is planned for
later, so the storage design should make that swap easy without a rewrite. Lower-right
text overlay: last-refresh date/time, counter, refresh interval, and current filename.

Three sibling projects already exist under `esp32-projects/` that this design builds
directly on: `ee03-text-test/` (buttons + text/graphics basics, including a
`showFramePlaceholder()` page that's explicitly a placeholder for this exact use
case), `test_bw_image_eink/` (proves out `pushImage`/`initGrayMode(GRAY_LEVEL16)` +
image packing, and documents a hard flash-budget wall: two full-canvas 4bpp images
compiled into flash already reach 89.5% of the 3.34MB app partition), and
`wifi_counter_eink/` (proves out `Preferences`/NVS persistence and documents that
`updataPartial()` fast-refresh is incompatible with 4bpp gray mode — this project must
always use full `epaper.update()`).

Confirmed by direct inspection: `~/Pictures/test_1.png`/`test_2.png` are already
1872x1404, P-mode, 16-color — i.e. already run through `prepare_image.py` at its
defaults, not raw source panoramas. Content occupies rows ~384-1020, leaving a solid
white band from ~1020-1404 across the full width. **`prepare_image.py` needs zero code
changes** — its existing resize-to-width + vertical-letterbox behavior already produces
exactly the desired layout, and the bottom band is exactly where the text overlay goes.

Decisions already made with the user (see conversation for the tradeoffs discussed):
- **Time**: internal ESP32 RTC, set manually via a serial command (no external RTC
  chip, no WiFi/NTP). Confirmed the RTC domain survives deep sleep, only a genuine
  power loss resets it.
- **Image storage**: **LittleFS** (not compiled into flash), specifically so a later
  swap to a physical SD card is a small change (same file-read code path) and so
  images stop competing with firmware code for app-partition space.
- **Counter button redraw**: deferred — NVS persists immediately, but the on-screen
  counter only updates at the next scheduled/forced full refresh (no per-press
  full-screen flash).
- **Buttons**: reuse GPIO 2/3/5 (this repo's existing convention — confirmed no
  official Seeed "Key1/2/3" labeling exists anywhere to contradict it). GPIO2 = force
  refresh/next image, GPIO3 = counter +1, GPIO5 = counter -1.
- **Wake architecture**: deep sleep between cycles, `esp_sleep_enable_timer_wakeup()`
  for the periodic cycle + `esp_sleep_enable_ext1_wakeup()` (`ESP_EXT1_WAKEUP_ANY_LOW`)
  on GPIO 2/3/5 — confirmed via research these are valid RTC-capable pins on the S3 for
  ext1 wake. A counter-only wake must not reset the main refresh countdown.
- **Known open risk**: the Sense variant's camera/mic board has been reported (Seeed/
  Arduino forum threads) to draw much more current in deep sleep than the ~14µA base
  spec unless explicitly powered down. Not solved here — flagged as a hardware
  verification step; fallback is unplugging the stackable Sense expansion board.

## Approach

### New project: `esp32-projects/panorama_photo_frame_w_counter/`

Fully self-contained PlatformIO project, same shape as the three siblings
(`platformio.ini`, `src/`, `lib/driver/driver.h` — byte-identical copy — `.gitignore`,
`README.md`), plus:
- `partitions.csv` (new, custom)
- `data/images/` — LittleFS source tree for `pio run -t uploadfs` (gitignored contents:
  generated `.bin` files + `manifest.txt`, same spirit as `test_bw_image_eink` ignoring
  its generated `image_data.h`)
- `tools/pack_images.py` + `tools/requirements.txt` (`Pillow` only)

### Partition table and `platformio.ini`

Custom `partitions.csv`, single non-OTA app partition (no OTA needed) + a generously
sized LittleFS data partition, summing to exactly the board's 8MB flash
(`seeed-xiao-esp32-s3-sense.json` confirms `maximum_size: 8388608`):

```
# Name,     Type, SubType,  Offset,   Size,      Flags
nvs,        data, nvs,      0x9000,   0x5000,
app0,       app,  factory,  0x10000,  0x140000,
spiffs,     data, spiffs,   0x150000, 0x6A0000,
coredump,   data, coredump, 0x7F0000, 0x10000,
```

`app0` = 1.25MB (comfortable headroom vs. `wifi_counter_eink`'s ~1.02MB/30.5% of a
3.34MB partition, and this project drops WiFi/WebServer entirely — verify with `pio
run` output, don't assume). `spiffs` (LittleFS — see note below on why it's still
named `spiffs`) = ~6.6MB: current 2 images (~1.31MB each) use ~2.5MB, leaving room for
~3x more before an SD card is actually needed.

Note: the LittleFS partition is named `spiffs`, not `littlefs` — Arduino-ESP32's
`LittleFS.h` defaults `partitionLabel` to `"spiffs"`, so `LittleFS.begin(false)` works
with no extra args as long as the partition table uses that label; `board_build.
filesystem = littlefs` is what actually makes `uploadfs` build a LittleFS (not SPIFFS)
image against it.

### `tools/pack_images.py`

Adapted from `esp32-projects/test_bw_image_eink/tools/convert_image.py` — reuse its
`pack_image()` nibble-packing function as-is (byte = 2 pixels, high nibble = even
pixel, low nibble = odd pixel, 0=black..15=white; already confirmed against vendored
`Seeed_GFX` source). Differences:
- Validate each input against the fixed 1872x1404 panel resolution.
- Emit one raw `.bin` file per image into `data/images/` (`img_00.bin`, `img_01.bin`,
  ...) instead of a C header — no framing needed, width/height are fixed compile-time
  constants in firmware.
- Emit `data/images/manifest.txt`: one tab-separated line per image, `<bin
  filename>\t<original source filename>`, in display order — firmware reads this for
  image count, which file to open per index, and the filename to show in the overlay.

Workflow: `prepare_image.py` (unchanged) → `tools/pack_images.py ~/Pictures/test_1.png
~/Pictures/test_2.png` → `pio run -t uploadfs` → `pio run -t upload`.

### Firmware (`src/main.cpp`)

Unlike the siblings' `loop()`-polling shape, this device does its work once per boot
and ends `setup()` with `esp_deep_sleep_start()` — a deep-sleep wake is a full
reset/reboot, so `loop()` is effectively unused.

**NVS schema** (`Preferences`, namespace `"frame"`, opened/closed per write exactly
like `wifi_counter_eink`'s `loadCounter()`/`persistCounter()` so every change survives
power loss):
- `imgIndex` (uint8) — index into `manifest.txt` order
- `counter` (int32) — user counter, display-only
- `nextRefEpoch` (int64) — absolute epoch seconds for the next scheduled full refresh
- `rtcValid` (bool) — whether the RTC has been set this power session

Refresh interval stays a firmware `constexpr` (not NVS-backed) — matches this repo's
low-ceremony style; easy to promote later if it needs to be runtime-tunable.

**Boot/wake dispatch**:
1. `Serial.begin(115200)`.
2. `esp_sleep_get_wakeup_cause()` — if this is a true cold boot/reset (not a
   timer/ext1 wake), open a bounded serial time-set window (user pastes a Unix epoch
   int from `date +%s`, `settimeofday()`, mark `rtcValid`). Skip this on every
   timer/button wake — deep sleep keeps the RTC domain powered, so it's unnecessary
   and would cost latency/battery every cycle.
3. Load NVS values; `LittleFS.begin(false)` (no auto-format — the filesystem is only
   ever populated via `uploadfs`; a mount failure should draw a static error to the
   panel, never silently reformat and wipe images).
4. Read `manifest.txt` for image count + filenames.
5. Dispatch:
   - **Cold boot / `ESP_SLEEP_WAKEUP_TIMER` / ext1 wake including GPIO2** → full
     refresh: advance `imgIndex`, read the packed `.bin` from LittleFS into a PSRAM
     buffer (`ps_malloc(1314144)`), `epaper.begin()` → `initGrayMode(GRAY_LEVEL16)` →
     `pushImage(0,0,1872,1404,(uint16_t*)buffer)`, draw the text overlay, `epaper.
     update()` (always full — `updataPartial()` is confirmed incompatible with 4bpp
     gray mode), persist `imgIndex` + new `nextRefEpoch`.
   - **ext1 wake with only GPIO3/GPIO5** → counter-only: `counter +=/-= 1`, persist
     immediately, **no display touch at all** (no `epaper.begin()`/`update()`), recompute
     remaining sleep from the *unchanged* `nextRefEpoch`.
   - Both bits set simultaneously → GPIO2 (refresh) takes priority; exercise on
     hardware.
6. Busy-wait for button release (`while (digitalRead(pin) == LOW) delay(10);`, same
   convention as `ee03-text-test`) before re-sleeping, so a still-held button doesn't
   immediately re-trigger `ESP_EXT1_WAKEUP_ANY_LOW`.
7. Re-arm: re-set `pinMode(2/3/5, INPUT_PULLUP)` (GPIO config doesn't survive deep
   sleep), `sleepSec = max(nextRefEpoch - now(), MIN_SLEEP_SEC)`,
   `esp_sleep_enable_timer_wakeup(sleepSec * 1'000'000ULL)`,
   `esp_sleep_enable_ext1_wakeup((1ULL<<2)|(1ULL<<3)|(1ULL<<5),
   ESP_EXT1_WAKEUP_ANY_LOW)`, `epaper.sleep()`, `esp_deep_sleep_start()`.

**Text overlay**: bottom-right white margin (rows ~1020-1404), using the same
`Seeed_GFX`/`TFT_eSPI` text APIs `ee03-text-test` already uses (`setTextSize`,
`setTextColor`, `drawString`), with `setTextDatum(TR_DATUM)` for right-alignment. Four
lines: last-refresh datetime (`gettimeofday()`/`strftime`), counter, refresh interval
(e.g. `"Every 2h"`), current filename (from the manifest). Exact pixel placement needs
on-hardware visual tuning, not a finalized layout.

**Include-order gotcha to carry over**: `wifi_counter_eink/src/main.cpp` documents that
`Seeed_GFX`'s ESP32-S3 processor header does `#define FS_NO_GLOBALS` before including
`FS.h`, which breaks unqualified `FS`/`File` use elsewhere unless `<FS.h>` is included
first. `LittleFS.open()` returns `fs::File`, so this project needs the identical
`#include <FS.h>` before `#include <TFT_eSPI.h>` fix.

**Explicitly not solved here** (verification items, not assumptions):
- `epaper.sleep()`/`begin(wake=1)`/`initFromSleep()` has no precedent in this repo —
  every sibling only ever calls plain `epaper.begin()` (full init). Use `epaper.
  begin(0)` (full init) on every wake for parity with proven-working code; still call
  `epaper.sleep()` before `esp_deep_sleep_start()` to cut the panel's own idle draw,
  but confirm on hardware this doesn't leave the panel in a bad state.
- Sense-board camera/mic deep-sleep current draw (see Context) — no power-down code
  is added; measure on real hardware before trusting any battery-life estimate.

### Docs

- New `panorama_photo_frame_w_counter/README.md`: description + cross-references to
  the three siblings for the patterns reused; full workflow commands; partition
  rationale (linking back to `test_bw_image_eink/README.md`'s 89.5%-full finding as
  *why* images moved to LittleFS); button mapping and the deferred-counter-redraw
  behavior; the serial time-set procedure and its power-loss-vs-deep-sleep behavior;
  a "Verified vs. unverified" section listing the two open risks above.
- `esp32-projects/hardware_info.md`: extend the existing "XIAO ePaper DIY Kit EE03"
  section's "Used by" line to add this project (same board/display, not a new
  device).

## Verification

1. **Partition sizing**: `pio run`, check `app0` fill % against the new 1.25MB
   partition (compare to `wifi_counter_eink`'s known 30.5%/3.34MB baseline); confirm
   the table sums to exactly 8MB with no overlap.
2. **LittleFS**: `pio run -t uploadfs`, confirm `LittleFS.begin(false)` succeeds,
   `manifest.txt` parses, both `.bin` files read back exactly 1,314,144 bytes and
   render correctly via `pushImage`/`update()`.
3. **Deep sleep + timer wake**: test with a short interval (e.g. 60s, not 2h) first;
   confirm actual sleep (measurable current drop) and correct
   `esp_sleep_get_wakeup_cause()` identification on wake.
4. **Button wake**: press GPIO2/3/5 individually while asleep; confirm
   `esp_sleep_get_ext1_wakeup_status()` correctly identifies each, GPIO2 triggers a
   full refresh, GPIO3/5 never touch the display; test simultaneous presses and the
   release-wait logic (no immediate re-wake loop).
5. **Counter persistence**: increment/decrement, then a real power cycle (pull power,
   not just deep sleep) — confirm the value survives and displays correctly at the
   next refresh.
6. **RTC behavior**: confirm time survives a deep-sleep/timer cycle but requires
   re-setting after genuine power loss, and that the serial time-set window only
   appears on that cold-boot path.
7. **Deep-sleep current draw** (Sense variant risk): measure with a multimeter/USB
   power meter before trusting any battery-life number; if anomalously high, look at
   a camera power-down sequence or physically unplugging the Sense expansion board.
8. **`epaper.sleep()`/wake correctness**: confirm the panel redraws correctly after a
   `sleep()`/wake cycle, since no sibling project has exercised this path before.
