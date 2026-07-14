# arduino-projects

Arduino IDE sketches, built and uploaded via the **vscode-arduino extension** — not PlatformIO (contrast with `../esp32-projects/`, which is PlatformIO). Default board target is `arduino:avr:uno` (see `.vscode/arduino.json`); check that file before assuming a different board.

## Conventions

- Arduino IDE requires a sketch's containing folder name to match its `.ino` filename (e.g. `triplet_volt_clock/triplet_volt_clock.ino`). Keep this invariant when adding or renaming sketches.
- `.vscode/c_cpp_properties.json` is IDE-generated and may contain machine-specific absolute paths from whatever machine last opened the project in VS Code. Don't hand-edit it — let the extension regenerate it.

## Vendored vs. personal code

- `libraries/` contains **vendored third-party Arduino libraries** (Adafruit_BusIO, Adafruit_LiquidCrystal, Adafruit_MCP23017_Arduino_Library, Adafruit_RGB_LCD_Shield_Library, LiquidCrystal). Treat as read-only — don't edit vendor source to fix a sketch-level bug; work around it in the sketch instead.
- `Personal Libraries/Sensirion/` is actual personal library code (distinct from the vendored `libraries/` above) and is fair game to edit.

## Loosely-organized areas — ask before restructuring

Some folders are informal experiment logs rather than curated, single-purpose projects. Don't consolidate, delete, or "clean up" older versions without asking, since it's not always clear which are superseded vs. intentionally kept for reference:

- `Sensirion/` — roughly a dozen loose experiment/test sketches (handshake tests, calibration, i2c scanner, etc.), separate from the curated `Personal Libraries/Sensirion/` library.
- `Mini Gauge/` — three versions side by side (`MiniGauge`, `MiniGaugeV1`, `MiniGaugeV2`) with no changelog explaining the differences.
- `Test Sketches/` — scratch sketches (`I2c_Scanner`, `Sensirion Library Test`); some have PlatformIO-style `include/`/`lib/`/`test/` stub folders even though this segment otherwise uses the Arduino IDE.
