# ESP32 hardware

Informal running notes on the physical boards/displays in use. Add a new section per device as hardware is added.

## XIAO ePaper DIY Kit EE03 — 10.3" monochrome ePaper display

- Board: Seeed XIAO ESP32-S3 **Plus** (confirmed via Seeed's EE03 getting-started page: "Built in XIAO ESP32-S3 Plus" — corrected from an earlier "Sense variant" note in this file, which was wrong for this board; no camera/mic expansion is present on this hardware)
- Display: 10.3" monochrome e-paper panel (EE03 kit)
- Product page: https://www.seeedstudio.com/XIAO-ePaper-DIY-Kit-EE03-for-10-3-Monochrome-ePaper-Display.html
- Used by: `ee03-text-test/` (buttons/text/graphics demo), `test_bw_image_eink/` (pushes a pre-converted grayscale photo to test the 16 gray levels), `wifi_counter_eink/` (browser-controlled counter over WiFi, partial e-paper refresh), `panorama_photo_frame_w_counter/` (battery-powered panorama photo frame — reads image + XML-metadata pairs off the SD-card mod below, deep sleep between refreshes, manually-set internal RTC, persistent counter logged to the card; see its `DESIGN.md` for the full design), `eink_sd_test/` (hardware bring-up diagnostic for the SD-card mod below), `panorama_photo_frame_web/` (the always-awake successor to the photo frame: same display path, but mains-powered with a LAN web interface for uploading photos, NTP clock, and counter control -- see its `DESIGN.md`), `xiao_s3_ee03_pull_frame/` (the same frame as a pull client of `python-projects/eink_photo_server/`: the server picks, captions, dithers and packs each image; the firmware downloads it to an SD cache and displays it, cycling the cache if the server is unreachable -- see its `DESIGN.md`)
- Notes: e-paper panels like this typically render more than 2 gray levels via dithering rather than pure black/white. `python-projects/grayscale_image_conversion/prepare_image.py` outputs 4-bit (16-level) dithered grayscale PNGs at 1872x1404 by default — that resolution lines up with this panel's native size, so it's likely the image-prep step feeding this display. Worth confirming and cross-referencing if either side changes.
- Battery/deep-sleep note: community reports (Seeed/Arduino forum threads) suggest the XIAO ESP32-S3 **Sense** variant's camera/mic expansion board can draw much more current in deep sleep than the base module's ~14µA spec unless it's explicitly powered down. This does **not** apply to this EE03 unit — it uses the Plus module with no camera attached — but is still relevant to any future project built on an actual Sense-variant board.

### Beta build: "beta-ee03-eink with SD card"

A specific modified unit — the stock EE03 board above with a microSD card added:

- SD card: Adafruit "Micro SD SPI or SDIO Card Breakout Board", product #4682 (https://www.adafruit.com/product/4682). Wired in **SPI mode** (not SDIO), 3.3V logic only (matches the ESP32-S3's own logic level, no level shifting needed).
- Shares the EE03 board's existing SPI1 bus, which also has a second CS pad reserved for a font-flash chip footprint — **confirmed unpopulated**, no chip present, nothing to conflict with.
- Pins: CLK=GPIO11, MOSI=GPIO13, MISO=GPIO12 (shared bus), SD card CS=GPIO39 (dedicated), font-flash CS pad=GPIO40 (unpopulated, unused).
- Status: working. The suspected CLK/3V3 solder short was ruled out (multimeter resistance/polarity-swap testing showed diode-signature behavior, not a real short). The actual root cause of the initial SD connect failures was the Adafruit breakout's DI/DO pads being wired instead of SI/SO (SPI mode) — fixed. `eink_sd_test/` runs as a continuous strain-relief monitor (15s periodic SD re-check + e-ink status refresh); `panorama_photo_frame_w_counter/` is the first project to actually *use* this SD card for storage (image + `.xml` pairs in `/pictures/`, `frame_config.xml`, `counter_track.txt`).
- SPI host note (verified during `eink_sd_test` bring-up): the SD card runs on `SPIClass(FSPI)` → **SPI2_HOST**, while the EE03 panel's Seeed_GFX/TFT_eSPI driver runs on **SPI3_HOST** — genuinely separate SPI peripherals, not just different CS lines on one bus, so the two never contend even when driven back-to-back.

## XIAO ESP32-S3 Sense — camera web cam

- Board: Seeed XIAO ESP32-S3 **Sense**, the first actual Sense-variant unit in this repo. The EE03 above is a Plus.
  - XIAO ESP32-S3 module: 8MB flash, 8MB OPI PSRAM
  - clip-on expansion board: camera connector, digital mic and microSD slot
- Product page: https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html
- PlatformIO board: `seeed-xiao-esp32-s3-sense`, from the same `platform-seeedboards` platform as the EE03 projects. Its board JSON already sets `qio_opi` memory, `BOARD_HAS_PSRAM` and `default_8MB.csv`.
- Camera: OV2640 on earlier kits; Seeed has since shipped OV3660 modules. The firmware reads the sensor PID at boot and reports the model, so either works.
  - The OV3660 needs vflip plus brightness/saturation tweaks to look right. These are borrowed from the core's CameraWebServer example; see `camera.cpp`.
  - DVP pin map: `CAMERA_MODEL_XIAO_ESP32S3` in the Arduino-ESP32 core's `libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h`. It's copied into `xiao_s3_sense_webcam/src/cam_config.h`.
  - The camera driver (`esp32-camera`) ships with the core, so no `lib_deps` are needed.
- microSD (on the expansion board): SPI on the XIAO's default SPI pins, SCK=GPIO7, MISO=GPIO8, MOSI=GPIO9, CS=GPIO21.
  - GPIO21 is also the user LED, so the LED flickers with card access.
  - These pins are entirely separate from the EE03 SD mod's (11/12/13/39).
- Heat: the ESP32-S3 + camera run noticeably warm when streaming continuously. That's a known trait of this board; a small heatsink or airflow helps for always-on use.
- Deep sleep: see the Sense deep-sleep current note under the EE03 section above. The webcam never sleeps, but any battery project on this board should power the camera down first.
- Used by: `xiao_s3_sense_webcam/` (LAN web camera; see its README):
  - live MJPEG stream you can toggle on and off
  - date-time-named snapshots, kept on SD, or in PSRAM when there's no card
  - auto and manual exposure/gain controls persisted in NVS
- Optional add-on: the 1.28" round touch display (next section), stacked on the same board.

## 1.28" Round Touch Display for XIAO

- Product page: https://www.seeedstudio.com/1-28-Round-Touch-Display-for-Seeed-Studio-XIAO-ESP32.html. Wiki: https://wiki.seeedstudio.com/get_start_round_display/ and https://wiki.seeedstudio.com/seeedstudio_round_display_usage/
- Panel: GC9A01, 240×240 round IPS, on SPI.
- Touch: CHSC6X at I2C 0x2E. A read is 5 bytes with no register address: byte 0 == 1 means pressed, x = byte 2, y = byte 4. INT goes LOW on touch.
- Also on the board:
  - a PCF8563 RTC on the same I2C bus (unused so far)
  - its own microSD slot
  - a battery connector with a power switch
- Pins (XIAO → ESP32-S3 GPIO):

  | XIAO pin | GPIO | Function |
  |---|---|---|
  | D1 | 2 | LCD CS |
  | D2 | 3 | Display's SD CS |
  | D3 | 4 | LCD DC |
  | D4 / D5 | 5 / 6 | I2C SDA / SCL (touch and RTC) |
  | D6 | 43 | Backlight, active HIGH |
  | D7 | 44 | Touch INT |
  | D8 / D9 / D10 | 7 / 8 / 9 | SCK / MISO / MOSI |
  | A0 | 1 | Battery voltage |

  - No LCD reset line.
  - D6/D7 are the UART0 TX/RX pins, which is fine because the XIAO's Serial is native USB.
- Switches:
  - **KE** must be ON for GPIO43 to control the backlight; ON also enables battery reading on A0.
  - The **power** switch cuts battery power. It's bypassed when the board is powered over USB.
- Library: `Seeed_GFX` with `BOARD_SCREEN_COMBO 501` in `lib/driver/driver.h`, which selects `User_Setups/Setup501_Seeed_XIAO_Round_Display.h`.
- **Shared SPI with the Sense SD slot:**
  - The LCD's SCK/MISO/MOSI are the same GPIO 7/8/9 the Sense expansion board's microSD uses (CS 21).
  - Setup501 sets `USE_HSPI_PORT` on the S3, so Seeed_GFX drives those pins from its own `SPIClass(HSPI)`.
  - An SD card on the global `SPI` (FSPI) would fight it for the pins.
  - The fix is to mount SD on the display's instance: `SD.begin(cs, TFT_eSPI::getSPIinstance(), …)`, after `tft.begin()`.
- Camera compatibility: no conflict with the Sense camera, whose pins (GPIO 10–18, 38–40, 47, 48) don't overlap. Its SCCB is on I2C port 1, while touch uses `Wire` (port 0).
- Used by: `xiao_s3_sense_webcam/`:
  - tap-to-wake live camera preview, cropped to the circle
  - a second tap for a Yes/No "turn screen off?" prompt
  - 2-minute auto-off
