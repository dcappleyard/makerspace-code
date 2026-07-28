# python-projects

Standalone `python3` scripts — no monorepo-wide package manager or virtualenv convention. Each subproject that imports third-party packages has its own lightweight, unpinned `requirements.txt` (just package names, no version pins) — follow that pattern for new subprojects rather than introducing poetry/uv/pipenv.

## Subprojects

- **`grayscale_image_conversion/`** — `prepare_image.py`, a CLI that fits a ~6:17 panorama photo onto the EE03 panel canvas (EXIF orientation, percentile contrast mapping, Floyd-Steinberg dithering to 4-bit grayscale), nibble-packs it to a display-ready `.bin`, and interactively prompts for metadata to write a matching `.xml` sidecar (+ a `.png` preview) for the `esp32-projects/panorama_photo_frame_w_counter/` SD-card frame. Deps: `Pillow`, `numpy`.
- **`usgs_monitoring/`** — `usgs_trend_summary.py` and `yahara_usgs_latest.py`, CLI tools that hit the USGS water-data API (`waterservices.usgs.gov`) for Yahara river monitoring sites near Madison, WI. Deps: `requests`. Overlaps with `../tidbyt-starlark/usgs_tracker`, `yahara_candle`, and `yahara_plot`, which target the same sites/parameters as the Tidbyt display layer — check both sides when changing site IDs or parameter codes.
- **`internet_connection_logging/`** — `check_netlog.sh`, a **bash/awk** script (not Python, despite the parent folder) that analyzes `network_health_log.csv`. The process that generates that CSV lives outside this repo (e.g. a cron/launchd job), so this directory only contains the analysis side.
