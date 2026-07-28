# ESP32 hardware

Informal running notes on the physical boards/displays in use. Add a new section per device as hardware is added.

## XIAO ePaper DIY Kit EE03 — 10.3" monochrome ePaper display

- Board: Seeed XIAO ESP32-S3 **Plus** (confirmed via Seeed's EE03 getting-started page: "Built in XIAO ESP32-S3 Plus" — corrected from an earlier "Sense variant" note in this file, which was wrong for this board; no camera/mic expansion is present on this hardware)
- Display: 10.3" monochrome e-paper panel (EE03 kit)
- Product page: https://www.seeedstudio.com/XIAO-ePaper-DIY-Kit-EE03-for-10-3-Monochrome-ePaper-Display.html
- Used by: `ee03-text-test/` (buttons/text/graphics demo), `test_bw_image_eink/` (pushes a pre-converted grayscale photo to test the 16 gray levels), `wifi_counter_eink/` (browser-controlled counter over WiFi, partial e-paper refresh), `panorama_photo_frame_w_counter/` (battery-powered panorama photo frame — reads image + XML-metadata pairs off the SD-card mod below, deep sleep between refreshes, manually-set internal RTC, persistent counter logged to the card; see its `DESIGN.md` for the full design), `eink_sd_test/` (hardware bring-up diagnostic for the SD-card mod below)
- Notes: e-paper panels like this typically render more than 2 gray levels via dithering rather than pure black/white. `python-projects/grayscale_image_conversion/prepare_image.py` outputs 4-bit (16-level) dithered grayscale PNGs at 1872x1404 by default — that resolution lines up with this panel's native size, so it's likely the image-prep step feeding this display. Worth confirming and cross-referencing if either side changes.
- Battery/deep-sleep note: community reports (Seeed/Arduino forum threads) suggest the XIAO ESP32-S3 **Sense** variant's camera/mic expansion board can draw much more current in deep sleep than the base module's ~14µA spec unless it's explicitly powered down. This does **not** apply to this EE03 unit — it uses the Plus module with no camera attached — but is still relevant to any future project built on an actual Sense-variant board.

### Beta build: "beta-ee03-eink with SD card"

A specific modified unit — the stock EE03 board above with a microSD card added:

- SD card: Adafruit "Micro SD SPI or SDIO Card Breakout Board", product #4682 (https://www.adafruit.com/product/4682). Wired in **SPI mode** (not SDIO), 3.3V logic only (matches the ESP32-S3's own logic level, no level shifting needed).
- Shares the EE03 board's existing SPI1 bus, which also has a second CS pad reserved for a font-flash chip footprint — **confirmed unpopulated**, no chip present, nothing to conflict with.
- Pins: CLK=GPIO11, MOSI=GPIO13, MISO=GPIO12 (shared bus), SD card CS=GPIO39 (dedicated), font-flash CS pad=GPIO40 (unpopulated, unused).
- Status: working. The suspected CLK/3V3 solder short was ruled out (multimeter resistance/polarity-swap testing showed diode-signature behavior, not a real short). The actual root cause of the initial SD connect failures was the Adafruit breakout's DI/DO pads being wired instead of SI/SO (SPI mode) — fixed. `eink_sd_test/` runs as a continuous strain-relief monitor (15s periodic SD re-check + e-ink status refresh); `panorama_photo_frame_w_counter/` is the first project to actually *use* this SD card for storage (image + `.xml` pairs in `/pictures/`, `frame_config.xml`, `counter_track.txt`).
- SPI host note (verified during `eink_sd_test` bring-up): the SD card runs on `SPIClass(FSPI)` → **SPI2_HOST**, while the EE03 panel's Seeed_GFX/TFT_eSPI driver runs on **SPI3_HOST** — genuinely separate SPI peripherals, not just different CS lines on one bus, so the two never contend even when driven back-to-back.
