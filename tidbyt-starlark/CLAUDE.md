# tidbyt-starlark

Tidbyt apps written in Starlark and built/pushed with `pixlet`. No pixlet version is pinned anywhere in the repo — there's no `.pixlet` config or lockfile, so builds depend on whatever `pixlet` is installed locally.

## Convention: one app per subdirectory

Each app is a subdirectory containing `<app>.star` + `manifest.yaml`. `manifest.yaml` fields in use: `id`, `name`, `summary`, `desc`, `author`, `entry`.

**`entry` must exactly match the actual `.star` filename in that directory.** This was previously broken in `yahara_plot/manifest.yaml` (`entry: image_render.star` pointed at a file that didn't exist — the real file was `yahara_plot.star`), which would break `pixlet push`/build. Double-check this whenever you add or rename a `.star` file.

Apps: `morning_info_text/`, `morning_setup/`, `test_tidbyt/`, `usgs_tracker/`, `yahara_candle/`, `yahara_plot/`.

## Config pattern (currently inconsistent)

- `morning_info_text.star` uses `schema.star` (`get_schema()`) for user-configurable options — the app can be configured per-install through the Tidbyt app UI.
- The rest (`morning_setup`, `usgs_tracker`, `yahara_candle`, `yahara_plot`) hardcode config as module-level constants (`LAT`, `LON`, `SITE`, etc.) edited directly in the `.star` file.

Both patterns are acceptable for now, but prefer `schema.star`-based config for anything meant to be installable/configurable outside your own setup — hardcoded constants are fine for single-purpose personal displays.

## Known naming overlap

`yahara_candle`, `yahara_plot`, and `usgs_tracker` all currently have `name: River Info` in their manifests (likely copy-paste drift from a shared template) — worth renaming to something distinguishable if you ever need to tell them apart in the Tidbyt app list, but left as-is since these are user-facing names on the physical device and shouldn't be changed without deciding on new names first.

## Build artifacts

`*.zip` is gitignored at the repo root going forward. `morning_info_text/morning_info_text.zip` and `test_tidbyt/test_tidbyt.zip` are pre-existing tracked build artifacts — leave them tracked unless asked to clean them up, but don't add new `.zip` files to git.
