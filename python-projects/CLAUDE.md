# python-projects

Standalone `python3` scripts — no monorepo-wide package manager or virtualenv convention. Each subproject that imports third-party packages has its own lightweight, unpinned `requirements.txt` (just package names, no version pins) — follow that pattern for new subprojects rather than introducing poetry/uv/pipenv.

## Subprojects

- **`grayscale_image_conversion/`** — `prepare_image.py`, a CLI that resizes/dithers an image into fixed-size 4-bit grayscale PNG for an e-paper-style display (EXIF orientation, percentile contrast mapping, Floyd-Steinberg dithering). Deps: `Pillow`, `numpy`.
- **`usgs_monitoring/`** — `usgs_trend_summary.py` and `yahara_usgs_latest.py`, CLI tools that hit the USGS water-data API (`waterservices.usgs.gov`) for Yahara river monitoring sites near Madison, WI. Deps: `requests`. Overlaps with `../tidbyt-starlark/usgs_tracker`, `yahara_candle`, and `yahara_plot`, which target the same sites/parameters as the Tidbyt display layer — check both sides when changing site IDs or parameter codes.
- **`internet_connection_logging/`** — `check_netlog.sh`, a **bash/awk** script (not Python, despite the parent folder) that analyzes `network_health_log.csv`. The process that generates that CSV lives outside this repo (e.g. a cron/launchd job), so this directory only contains the analysis side.
