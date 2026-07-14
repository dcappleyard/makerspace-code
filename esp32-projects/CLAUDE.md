# esp32-projects

PlatformIO projects targeting ESP32 boards, using the Arduino framework. Contrast with `../arduino-projects/`, which uses the plain Arduino IDE — same C++/Arduino-framework family, different build system and layout.

## Layout

Each subdirectory is a **fully self-contained PlatformIO project** with its own `platformio.ini`, `src/`, `include/`, `lib/`, `test/`, and `.gitignore` (covering `.pio/` build output and editor/OS cruft). New boards or sketches should follow the same per-project structure — run `pio project init` inside a new subdirectory rather than hand-rolling the layout.

Current target hardware: Seeed XIAO ESP32-S3 (Sense variant), via the `platform-seeedboards` platform and `Seeed_GFX` library pulled in through `lib_deps` GitHub URLs (see `ee03-text-test/platformio.ini` for the pattern).

`hardware_info.md` is a running informal notes file about the physical hardware in use (displays, boards, part links). Keep it updated when you add a new board or peripheral — it's the only place hardware context is recorded outside code comments.

## Building

Standard PlatformIO CLI: `pio run` to build, `pio run -t upload` to flash, from inside the specific project subdirectory (each has its own `platformio.ini`, there's no repo-wide build).
