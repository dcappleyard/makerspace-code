# Install / run instructions

Step-by-step setup for `eink_sd_test`, including every PlatformIO CLI command used and
how to prepare the microSD card. See `README.md` for what the test actually checks and
`DESIGN.md`-equivalent context in `../hardware_info.md`'s "beta-ee03-eink with SD card"
section for the physical build this targets.

## 1. Prerequisites

- **PlatformIO Core CLI** (`pio`) installed and on `PATH`. If `pio` isn't found in a
  fresh terminal, add it (PlatformIO Core installs into `~/.platformio/penv/bin` by
  default):
  ```
  echo 'export PATH="$PATH:$HOME/.platformio/penv/bin"' >> ~/.zshrc
  source ~/.zshrc
  pio --version   # sanity check
  ```
- A USB-C cable connected to the board's native USB port.
- The SD card wiring already soldered per `../hardware_info.md`'s beta build note, and
  — if there's any doubt about a solder short — **checked with a multimeter, power
  off, before proceeding** (see `README.md`'s "Before powering on" section; not
  repeated here).
- No `mklittlefs` install needed for this project specifically — unlike
  `../panorama_photo_frame_w_counter`, this firmware doesn't use LittleFS or a custom
  filesystem partition at all (see step 2 for why the SD card itself isn't LittleFS
  either).

## 2. Formatting the microSD card

**Use FAT32, not LittleFS.** This firmware mounts the card with Arduino-ESP32's `SD`
library (`SD.begin()`/`SD.open()` in `src/main.cpp`), which — like virtually all
embedded SD card libraries — expects a standard **FAT** filesystem, the same format
SD cards ship pre-formatted with and that any computer's card reader can read
natively. LittleFS is a different filesystem, designed for wear-leveling *raw* SPI
NOR/NAND flash chips with no built-in wear leveling of their own (that's what
`panorama_photo_frame_w_counter` uses for its onboard flash image storage) — it isn't
something the `SD` library (or SD cards generally, which already do their own
wear-leveling internally) supports or benefits from. Formatting the card as LittleFS
would simply make it unreadable by this firmware.

FAT32 also has a practical upside if this hardware is later used for photo storage
per `../panorama_photo_frame_w_counter/DESIGN.md`'s original SD-card plan: you'd be
able to drag `pack_images.py` output straight onto the card from a Mac card reader,
no `pio run -t uploadfs`-style flashing step required.

Recommended: a card **32GB or smaller**, formatted FAT32 (large-capacity exFAT cards
are not reliably supported by Arduino-ESP32's `SD` library).

**Option A — official SD Association formatter (recommended, handles FAT32 cluster
sizing correctly for embedded card libraries):**
Download "SD Memory Card Formatter" from https://www.sdcard.org/downloads/formatter/
(there's a Mac version), select the card, use the default "Quick Format," FAT32.

**Option B — command line (macOS `diskutil`):**
1. Insert the card in a reader, then identify its disk number — **read this
   carefully, erasing the wrong disk is unrecoverable**:
   ```
   diskutil list
   ```
   Look for a disk matching the card's actual size (e.g. `/dev/disk4`, not your main
   internal disk `/dev/disk0`/`/dev/disk1`).
2. Erase and format as FAT32 (substitute the correct `/dev/diskN` from step 1):
   ```
   diskutil eraseDisk FAT32 EINKSD MBRFormat /dev/diskN
   ```
   (`EINKSD` is just a volume label, change if you like.)
3. Confirm it mounted correctly:
   ```
   diskutil list /dev/diskN
   ```
   should show one `Windows_FAT_32` partition.

No pre-existing files or folder structure are required on the card — this firmware
writes its own test file (`/hwtest.txt`) at the root during the test.

Eject the card from your Mac, then insert it into the board's microSD slot.

## 3. Build and flash

From inside `esp32-projects/eink_sd_test/`:

```
pio run                 # compile only, no upload -- confirms the project builds
pio run -t upload       # compile (if needed) and flash over USB
```

If `pio run -t upload` can't auto-detect the port, find it explicitly and pass it:
```
pio device list                                  # find the board's port, e.g. /dev/cu.usbmodem101
pio run -t upload --upload-port /dev/cu.usbmodem101
```

Optional: `pio run -t clean` clears build artifacts if you want a from-scratch
rebuild (rarely necessary).

## 4. Watch the results

```
pio device monitor --port /dev/cu.usbmodem101   # substitute your actual port
```

Always pass `--port` explicitly — `pio device monitor` with no `--port` can default to
an unrelated virtual serial port (e.g. `/dev/cu.Bluetooth-Incoming-Port`) instead of
the board, a gotcha documented in `../CLAUDE.md` and
`../panorama_photo_frame_w_counter/clock_set_instructions.md`. Baud rate (115200) is
already set via `monitor_speed` in `platformio.ini`, so no `--baud` flag is needed.

You should see PASS/FAIL for both the SD card and e-ink tests within a couple seconds
of boot, plus the e-ink panel itself redrawing with a summary. To leave the monitor:
`Ctrl+C`.

To re-run the test, press the board's **reset** button — unlike
`panorama_photo_frame_w_counter`, this firmware never deep-sleeps, so the port stays
enumerated and visible in `pio device list` at all times; there's no timing race to
worry about here.
