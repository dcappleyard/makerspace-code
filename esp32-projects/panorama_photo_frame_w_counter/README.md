# panorama_photo_frame_w_counter

A battery-powered panorama photo frame on the XIAO ePaper DIY Kit EE03 (10.3" panel)
with a microSD card for image + metadata storage. Same board/display as
`../ee03-text-test`, `../test_bw_image_eink`, and `../wifi_counter_eink`; the SD-card
mod is the one proven out in `../eink_sd_test` — see `../hardware_info.md`. See
`DESIGN.md` for the original design rationale and the SD-migration notes on top of it.

Cycles between panorama photos on a timer (interval set by `frame_config.xml` on the
card, default every 2 hours), with one button forcing an immediate refresh/cycle and
two other buttons adjusting a persistent counter. Each photo has an `.xml` metadata
sidecar whose fields are drawn as a caption beneath the image. Deliberately has no
WiFi, to save battery — this device spends almost all its time in deep sleep.

## SD card layout

Format the card **FAT32** (see `../eink_sd_test/INSTALL.md`) and populate it like so:

```
/pictures/
    harbor.bin      # display-ready packed image (from prepare_image.py)
    harbor.xml      # its metadata sidecar (same base name)
    dawn.bin
    dawn.xml
    ...
/frame_config.xml   # <refresh_hours> (cycle interval) + <counter> (starting/live value)
/counter_track.txt  # created/appended by the frame itself (counter log)
```

Photos are cycled in **filename order** of the `.bin` files. Each `<name>.bin` needs a
matching `<name>.xml`; a missing sidecar just leaves the caption fields blank.
`frame_config.xml` is optional — without it (or with a bad value) the frame falls back
to a 2-hour interval and counter 0. A ready-to-copy starter lives in
`sd_card_template/frame_config.xml`. Note the frame **rewrites `<counter>` in this
file** on every counter-button press (see Buttons below).

## Workflow

1. Prepare each photo (crop/backfill to the 6:17 strip, dither, pack, and capture its
   metadata) with `python-projects/grayscale_image_conversion/prepare_image.py`:
   ```
   pip install -r requirements.txt   # first time only (Pillow, numpy)
   python3 prepare_image.py ~/Pictures/harbor.tif --output-dir ./sd_pictures
   ```
   It prompts for Artist / Date (YYYY-MM-DD) / Location / Title / Film and an output
   filename, then writes `<name>.bin` (exactly 1,314,144 bytes), `<name>.xml`, and a
   `<name>.png` preview into `--output-dir`. Any field can be left blank.
2. Copy the `.bin` + `.xml` pairs into the card's `/pictures/` directory, and put a
   `frame_config.xml` at the card root (see above). Re-copying is all it takes to
   change or add photos — no reflash needed.
3. Flash the firmware (only needed when the firmware itself changes):
   ```
   pio run -t upload
   ```
   There is no `uploadfs` step anymore — images live on the SD card, not in flash.
4. On first boot, open the serial monitor. The device asks for the current time: run
   `date +%s` on your computer, paste the number, and press Enter within the window
   (or just press Enter to skip). This is a **manual** clock — no WiFi/NTP and no
   external RTC, so it needs re-setting after any genuine power loss (battery pull,
   not deep sleep — deep sleep keeps the clock running). See `clock_set_instructions.md`.

## Clock & cold-boot behavior

The frame **does not depend on the clock being set** — it never hangs or misbehaves
without one. Photo cycling uses only *relative* intervals (each sleep is computed as
`nextRefEpoch - now`, both from the same clock, so an unset/arbitrary clock still yields
a correct interval), the caption shows no time, and a counter change with no clock is
logged as `TIME_NOT_SET` instead of a timestamp.

The one behavior to expect: on every **cold boot** (power loss / reset, not a
deep-sleep wake) the device holds in the serial time-set window for up to
`TIME_SET_WINDOW_MS` (**120 s**) *whether or not* you set the clock. So a battery-only
cold boot with nothing attached to serial waits ~2 minutes before the first image
appears. This is a deliberate delay, **not a hang** — press Enter (empty is fine) to
skip it immediately, or paste a timestamp to set the clock. Timer/button wakes skip the
window entirely.

## Buttons

Same GPIO pins as the other EE03 projects in this repo (2, 3, 5):

| Button | Action |
|---|---|
| GPIO2 | Force an immediate refresh — advances to the next image and redraws the whole panel (including the caption) |
| GPIO3 | Counter +1 |
| GPIO5 | Counter -1 |

On a counter press the frame reads `<counter>` from `/frame_config.xml`, adjusts it,
**writes the new value back into that file**, and appends a timestamped line to
`/counter_track.txt` (`YYYY-MM-DD HH:MM:SS <tab> +1/-1 <tab> newValue`; the timestamp is
`TIME_NOT_SET` if the clock has never been set). So the counter lives on the SD card, not
in flash — its boot value comes from `<counter>` and edits are persisted there. But **the
display is not redrawn** for a counter press — the on-screen value only updates at the
next scheduled or forced refresh. This avoids a multi-second full-panel flash on every
button press, since 4bpp gray-mode images can't use the panel's fast partial refresh
(see `../wifi_counter_eink/README.md`'s finding on that). If the SD card isn't present on
a counter press, the change is skipped (logged over serial).

## Text overlays

Small-font lines sit in the white margins bracketing the photo, with transparent
backgrounds so the image shows through. Each line is nudged toward its panel edge
(header up, caption down) by `EDGE_NUDGE` beyond the base `CAPTION_GAP`:

- **Header line, above the photo** (font 2): the **counter value**, left-aligned. (The
  top-right battery label is removed for now — `BATTERY_PLACEHOLDER` stays in
  `src/main.cpp` for when real battery sensing is wired up.)
- **Caption line, below the photo** (left and right runs bottom-aligned on a shared edge):
  - **Left-aligned (font 2):** `Title · Location · Film`, joined by a hand-drawn centered dot
  - **Right-aligned (font 4):** `Artist ‡ Date`, joined by a hand-drawn double dagger

Empty fields are omitted from each run with no dangling separators. The separators are
drawn by hand (`drawDotSep`/`drawDaggerSep`) because the built-in fonts only cover ASCII
32–127 — there's no centered-dot or double-dagger glyph to set as text.

**Per-corner text color (data-driven).** Instead of a fixed grey, each text block's color
comes from the sidecar. `prepare_image.py` samples a ~200×30 px patch in the matching
corner of the photo strip, takes the mean 4-bit gray level, and writes a contrasting
`TFT_GRAY_*` value: `text_color_top_left` (counter), `text_color_bottom_left`,
`text_color_bottom_right`, plus `text_color_top_right` (generated for future use). The
firmware parses these per photo (`parseGrayColor`) and falls back to `TFT_GRAY_8` if a
field is missing. The mapping (mean → color) lives in `gray_color_for_mean` in the Python
tool. Note the color is picked from the *image* corner while the text is drawn in the
adjacent white margin, so a very dark image corner yields light text that reads faintly
on the white margin — adjust the mapping (or move the text onto the image) if that
matters for your photos.

## Storage architecture

Images and their metadata live on the SD card, read at runtime over the card's own SPI
host (`SPIClass(FSPI)` → SPI2_HOST), which is physically separate from the EE03 panel's
bus (SPI3_HOST) so the two never contend — the arrangement proven in `../eink_sd_test`.
This replaces the project's original LittleFS image storage (`data/images/` +
`tools/pack_images.py` + `pio run -t uploadfs`), which capped total images at the
~6.9 MB filesystem partition and required a reflash to change photos. The nibble-packing
that `pack_images.py` used to do is now folded into `prepare_image.py`, so it emits the
display-ready `.bin` directly. The old `tools/` packer and `data/images/` payload are
retired.

## Swapping the SD card

Removing/inserting the card while the frame is powered (battery or USB-C) is generally
safe. The firmware only brings the SD bus up briefly at a wake event — `mountSd()` →
read (refresh) or append (counter press) → `unmountSd()` — and holds no card handle
across deep sleep, so for the vast majority of the time the card is fully unmounted and
idle. Pulling it then is fine, and the frame remounts a reinserted card fresh on the
next wake.

- **The only risk window** is the sub-second moment the card is actively mounted:
  during a refresh read, and especially during the `counter_track.txt` **write** after
  a counter press (yanking mid-write is the classic way to corrupt a FAT filesystem).
  So avoid pulling the card in the second or two right after a refresh fires or right
  after pressing a counter button; when in doubt, swap it while it's idle (nearly
  always).
- **A missing card fails soft, never hangs**: a refresh with no card draws an "SD mount
  failed…" screen and sleeps; a counter press with no card still persists the count to
  NVS and just logs that it couldn't write the track file.
- **Electrically** the Adafruit #4682 breakout is 3.3 V with no level shifting, and
  SD-over-SPI is routinely hot-swapped — the practical hazard is filesystem corruption
  from mid-write removal, not hardware damage.

## Power / sleep behavior

The device does essentially all of its work once per boot, then calls
`esp_deep_sleep_start()` — `loop()` is never actually reached. It wakes via:
- **Timer**: the refresh interval (`<refresh_hours>` from `frame_config.xml`, default
  2 hours) — advances to the next image.
- **GPIO2 (ext1 wake)**: same as a timer wake, but immediate — advances to the next
  image **and restarts the full interval**: the next automatic advance is a fresh N
  hours from the moment you pressed the button, not from the previous schedule.
- **GPIO3/GPIO5 (ext1 wake)**: counter-only — adjusts the counter in
  `frame_config.xml`, logs it to the card, then goes back to sleep for whatever time
  remains until the *original* scheduled refresh (a counter press never resets or
  extends the countdown).

## Verified vs. unverified

The host-side image/metadata pipeline (`prepare_image.py`) is verified: correct 6:17
strip geometry, exact 1,314,144-byte `.bin`, well-formed `.xml`, and blank-field
handling. The firmware **compiles** but has not been run on physical hardware in this
configuration yet. Things to check first on-device:

- **SD read path**: card mounts, `/pictures` enumerates in filename order, each `.bin`
  reads back exactly 1,314,144 bytes and renders via `pushImage`/`update()`, and the
  matching `.xml` caption fields appear.
- **`frame_config.xml`**: present value drives the sleep timer; missing/garbled falls
  back to 2 h without crashing.
- **Counter round-trip**: a counter press rewrites `<counter>` in `frame_config.xml`
  (other config content preserved), appends a `+1`/`-1` line to `counter_track.txt`, and
  the new value shows at the next refresh — the panel is *not* touched on the press itself.
- **Caption overlay**: grey (`TFT_GRAY_8`) text; the hand-drawn centered dot and double
  dagger separators land correctly and the font-2/font-4 runs bottom-align; tune
  `DOT_SEP_W`/`DAGGER_SEP_W` and the dagger geometry on hardware if needed.
- **`epaper.sleep()`/`begin()` across wakes**: no sibling exercised `sleep()` before
  this project; confirm the panel redraws correctly after a sleep/wake cycle.
- **RTC across power loss**: expected to survive deep sleep but not a real power cycle;
  confirm the serial time-set window only appears on the cold-boot path.
- **Deep-sleep current draw**: measure before trusting any battery-life estimate.
