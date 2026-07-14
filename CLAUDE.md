# makerspace-code

A monorepo of personal maker/hobby projects spanning four independent segments, each with its own toolchain. There is no repo-wide build system, package manager, or CI — this is a low-ceremony personal repo. Match the existing minimal style: don't add test suites, linters, CI, or heavier dependency management than a segment already uses unless asked.

## Segments

| Segment | Stack | Docs |
|---|---|---|
| `arduino-projects/` | Arduino IDE (vscode-arduino extension) sketches, AVR boards | [arduino-projects/CLAUDE.md](arduino-projects/CLAUDE.md) |
| `esp32-projects/` | PlatformIO, Arduino framework, ESP32-S3 boards | [esp32-projects/CLAUDE.md](esp32-projects/CLAUDE.md) |
| `python-projects/` | Standalone Python 3 scripts (+ one bash utility) | [python-projects/CLAUDE.md](python-projects/CLAUDE.md) |
| `tidbyt-starlark/` | Tidbyt `pixlet` apps written in Starlark | [tidbyt-starlark/CLAUDE.md](tidbyt-starlark/CLAUDE.md) |

Each segment's CLAUDE.md is the authoritative source for that segment's conventions — read it before making changes there. `arduino-projects/` and `esp32-projects/` are both C++/Arduino-framework but use **different build systems** (Arduino IDE vs. PlatformIO); don't assume conventions carry over between them.

## Cross-cutting notes

- A single MIT `LICENSE` at the repo root covers everything in the monorepo — segments don't have their own.
- Root `.gitignore` covers OS cruft (`.DS_Store`), PlatformIO build output (`.pio/`), Python caches/venvs, and pixlet build artifacts (`*.zip`). Segment-specific `.gitignore` files (e.g. under `esp32-projects/`) can still exist for tool-specific patterns.
- `python-projects/usgs_monitoring/` and `tidbyt-starlark/`'s `usgs_tracker`, `yahara_candle`, and `yahara_plot` apps all pull from the same USGS water-monitoring sites on the Yahara river (Madison, WI). The Python scripts are ad hoc analysis/CLI tools; the Starlark apps are the Tidbyt display layer. A change to site IDs, parameter codes, or data-shape assumptions in one likely applies to the others.

## Commits

The user makes all commits themselves — don't `git commit` (or stage/push) unprompted. When asked for a commit message, generate one to hand back for the user to use themselves; don't run `git commit` with it unless explicitly told to.
