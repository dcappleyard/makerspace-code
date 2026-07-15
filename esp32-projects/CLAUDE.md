# esp32-projects

PlatformIO projects targeting ESP32 boards, using the Arduino framework. Contrast with `../arduino-projects/`, which uses the plain Arduino IDE — same C++/Arduino-framework family, different build system and layout.

## Layout

Each subdirectory is a **fully self-contained PlatformIO project** with its own `platformio.ini`, `src/`, `include/`, `lib/`, `test/`, and `.gitignore` (covering `.pio/` build output and editor/OS cruft). New boards or sketches should follow the same per-project structure — run `pio project init` inside a new subdirectory rather than hand-rolling the layout.

Current target hardware: Seeed XIAO ESP32-S3 (Sense variant), via the `platform-seeedboards` platform and `Seeed_GFX` library pulled in through `lib_deps` GitHub URLs (see `ee03-text-test/platformio.ini` for the pattern).

`hardware_info.md` is a running informal notes file about the physical hardware in use (displays, boards, part links). Keep it updated when you add a new board or peripheral — it's the only place hardware context is recorded outside code comments.

## Building

Standard PlatformIO CLI: `pio run` to build, `pio run -t upload` to flash, from inside the specific project subdirectory (each has its own `platformio.ini`, there's no repo-wide build).

## Workflow

The user works in VS Code in parallel with Claude Code, using the PlatformIO extension there to build/upload/monitor the ESP32 boards directly. Expect the project to be open in VS Code at the same time — don't assume exclusive control over `.pio/` build state or the device's serial port, since the PlatformIO extension may be using either.

## Deep sleep + serial uploads

For any project that puts the board into deep sleep (see `panorama_photo_frame_w_counter/`): the XIAO ESP32-S3's native USB-Serial/JTAG interface only enumerates while the chip is awake, so `pio device list`/`upload`/`uploadfs` all lose the port entirely once it's asleep — it's not a fault, the device just isn't there yet. `pio`'s own startup overhead (dependency scanning, building any filesystem image) eats into the time between pressing reset and esptool actually opening the port, so a short "wake and wait for serial input" window on boot (e.g. before the first deep sleep) can expire before an upload command even gets that far, especially on the first `uploadfs` after a fresh build. Favor a generous window (60-120s) on any such boot-time serial prompt while actively iterating on uploads; it's cheap to shorten once the device is verified and no longer being reflashed frequently.
