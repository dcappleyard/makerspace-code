# eink_sd_test

A hardware bring-up / strain-relief monitor for the **"beta-ee03-eink with SD card"**
build (see `../hardware_info.md`) — the EE03 kit with a microSD card (Adafruit 4682)
soldered onto its SPI1 bus. Not a permanent fixture: no deep sleep, stays powered over
USB, just re-run it via the reset button as needed. This is deliberately a separate
project from `../panorama_photo_frame_w_counter/` so testing never risks the
already-working panorama firmware.

The original CMD0/connect failures seen during bring-up were root-caused: the Adafruit
breakout's DI/DO pads were wired instead of SI/SO (SPI mode). With that fixed, this
firmware now runs as a **continuous connectivity monitor**: every 15 seconds it
re-mounts the SD card, does a write/read round-trip, and refreshes the e-ink panel with
a check counter and PASS/FAIL — useful for watching the connection live while doing
strain relief on the wires, without needing a laptop/serial monitor open.

## Pins (SPI1, shared bus)

| Signal | GPIO |
|---|---|
| CLK | 11 |
| MOSI | 13 |
| MISO | 12 |
| SD card CS | 39 |
| Font-flash chip CS pad | 40 — **unpopulated**, not used by this firmware |

## Running it

See `INSTALL.md` for the full step-by-step (every CLI command, plus how to format the
microSD card — FAT32, not LittleFS, with reasoning). Quick version:

```
pio run -t upload
pio device monitor --port <port>   # explicit --port, see ../CLAUDE.md
```

On boot it does one SD check and a full panel refresh, then every 15 seconds after
that it re-checks the SD card and does a fast partial refresh of just the status block
(check counter, PASS/FAIL, card size/error detail) — no need to reset between checks,
it runs continuously. Serial output mirrors the same info each cycle.

If a check fails, that's the actual diagnostic signal — the specific failure mode
(mount timeout vs. write/read mismatch) narrows down whether it's a wiring issue or
something else; there's no automatic fix here, just the report.

## Board note

Uses the same `board = seeed-xiao-esp32-s3-sense` PlatformIO board ID as the other
EE03 projects in this repo, even though the EE03 kit's actual module is the XIAO
ESP32-S3 **Plus** (confirmed via Seeed's EE03 docs — see `../hardware_info.md`), not
Sense. Not worth chasing a separate board ID for a throwaway test project when the
existing one already boots and drives the panel correctly on this hardware.
