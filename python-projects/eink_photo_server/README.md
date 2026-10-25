# eink_photo_server

One server that feeds all the e-ink photo frames. Frames **pull** on their own timers (battery frames sleep, so pushing is unreliable). The server:
- stores photos: uploaded in the web UI, uploaded by a client such as the photobooth, or dropped into a folder
- prepares them for each frame type (crop, resize, tone tuning, encoding)
- keeps shared playlists, and a daily schedule per frame that picks from a source or a playlist

It runs in Docker on a Raspberry Pi.

v1 supports the **Bloomin8** "Schedule Pull" protocol (7.3" Spectra 6).

## Concepts

Each device in `devices.yaml` pairs two things:

- **Protocol adapter** (`server/protocols/`): how the frame asks for its next image, i.e. endpoints and response shape. `bloomin8` implements `/eink_pull`, `/eink_signal`, and `/image/<secret>/<name>`.
- **Pipeline** (`server/pipelines/`): how a source photo becomes the bytes that panel wants. `bloomin8_spectra6` does the following:
  - applies EXIF orientation and converts to sRGB
  - cover-crops to the panel aspect around a focal point, then Lanczos-resizes
  - applies saturation, contrast, brightness and gamma
  - rotates
  - encodes a baseline JPEG

  It does **not** dither, because the frame dithers itself. Its `preview()` gives a Spectra 6 dither simulation for the UI.

Sources, playlists, scheduling and photo storage are shared by every device.

### Adding a pipeline
1. Create `server/pipelines/<something>.py`.
2. Subclass `Pipeline` and decorate it with `@register`. Implement `prepare()`, and `preview()` if you want one.
3. Set its `name` as a device's `pipeline:` in `devices.yaml`.

Modules in that folder are auto-discovered. Bump `version` whenever the output changes, so cached images are regenerated.

### Adding a protocol
Add `server/protocols/<name>.py` with a FastAPI `router` and a `PROTOCOL` name, then list it in `server/protocols/__init__.py`. Use `schedule.choose()` / `schedule.next_wake()` and `prepare.get_prepared()` so the device shares the schedule logic. The planned ESP32 frame needs this: a "next image + sleep N s" endpoint and a pipeline that pre-dithers and packs 4 bpp.

## Web UI
The main nav is **Sources · Playlists · Frames**, each with sub-tabs. `/` redirects to `/sources/library`.

### Sources
Sub-tabs: **Library**, one tab per folder source from `devices.yaml` (e.g. **Photobooth**), and **Test cards**.
- **Library:** web upload, with an optional same-named `.xml` sidecar import (see below).
- **Each photo card has:**
  - click the photo to set the crop focal point
  - **Edit info** (sidecar fields and tags)
  - per-photo tuning
  - **Add to playlist ▾**
  - **Show next on ▾** a frame
  - **Sim**: opens the photo as the chosen frame would display it. It's per frame because size, strip, captions, rotation and tuning are all per frame.
  - **Delete**
- **Tag filter:** each source tab has one.

### Playlists
- **All playlists:** cards with thumbnails, photo count, and which frames use each one. **New / Rename / Duplicate / Delete**. Delete is refused, with a banner, while any frame's schedule block uses the playlist.
- **One sub-tab per playlist:** reorder (↑↓), remove, **Show next**, **Sim**.
- Photos are added from Sources with **Add to playlist**.
- Playlists aren't owned by frames. Several frames can share one.

### Frames
One sub-tab per frame (`/frame/<id>`): status, schedule with a next-24-hours timeline, wake timing, and the frame's log.

## Schedule (daily blocks)
Each frame has a daily timeline of blocks, edited on its tab. A block starts at a clock time and runs until the next block starts, wrapping past midnight. A block is **start time + source + selection + refresh**.

- **Source:** a raw source (`library`, a folder source id such as `photobooth`, or `testcards`) or a playlist (stored as `playlist:<id>`).
- **Selection:**
  - **Next:** in order, i.e. playlist order, or arrival order for a raw source. **Each frame keeps its own position per source** (the `source_cursors` table), so frames sharing a playlist don't disturb each other.
  - **Random:** never the photo currently shown.
  - **Most recent:** the newest added photo.
  - **Specific photo.**
- **Refresh:**
  - **Every N min** (N ≥ 5): ticks are counted from the block's start (07:00, 08:00, …).
  - **Blank:** hold one photo until the block ends. The frame doesn't wake until then.

Example: *Photobooth + Most recent every 10 min* is a live party feed.

**Old block kinds** map as: Sleep → hold (+ a specific photo or random), Load image → specific + hold, Random image → random every N, Play playlist → next every N.

**No blocks yet:** the frame follows the `interval_minutes`/`wake_hours` defaults from `devices.yaml`: Library, Next, every interval during `wake_hours`, and one random Library photo held outside them. **Make these editable** turns those defaults into blocks.

Precedence on each pull:
1. A queued **Show next** photo (one shot).
2. **Paused:** the last image is re-served.
3. **Retry guard:** a pull within 5 min of an unconfirmed one gets the same image.
4. The current block.

## Wake timing and the log
- **What the frame reports:** with every pull it reports `cron_time`, the wake time it was given. The log records that next to the actual pull time, so you can see the **drift**. Each pull also logs the battery, the block, the reason, and the next wake target and time sent.
- **Early wakes:** a scheduled pull that arrives up to 60 min *before* its target counts as that target. The frame gets that slot's photo, and the next wake is computed from the slot, so an early wake doesn't cause an extra refresh.
- **Wake offset:** the wake time sent is the target + the **wake offset**. The **Wake timing** card shows the median drift over the last 10 scheduled pulls, and **Apply measured** sets the offset to cancel it. If the frame wakes 3 min early, the offset becomes +3 min, so a 07:00 block's image appears at about 07:00.
- **Log tools:** the log keeps the newest 5000 events per frame. It can be cleared, or downloaded as CSV, from the frame's tab.

## Battery overlay
Set `battery_monitor` per device in `devices.yaml`:
- `none` (the default): no overlay. Use this for frames without a battery monitor.
- `always`: always overlay the battery %.
- `low`: overlay only when the battery is below 10%.

The overlay is a ~20 px "NN%" in a small white box in the upper-right corner, as the frame is mounted. Below 10% it's red on colour panels, otherwise black.

It shows the reading the frame sent with the same pull, or the last known reading if that pull didn't include one. The reading is part of the image's cache key, so a new value produces a new file and URL.

## Photo sidecars and tags
Each photo has a metadata sidecar, `originals/<sha>.xml`, in the flat `<meta>` format that `prepare_image.py` writes, plus a `tags` element:

```xml
<meta>
  <artist>…</artist>
  <date>YYYY-MM-DD</date>
  <location>…</location>
  <title>…</title>
  <film>…</film>
  <tags>beach, family</tags>
</meta>
```

**Getting a sidecar at upload:**
- Upload a same-named `.xml` alongside its image (`harbor.jpg` + `harbor.xml`) and its fields are imported.
- Without one, the sidecar is created from the photo's EXIF: the date taken (DateTimeOriginal) and the artist.
- Re-uploading the same image keeps its existing sidecar unless a new `.xml` comes with it.
- On startup the server creates any missing sidecars and rebuilds the tag index.

**Elements the server doesn't use** (e.g. `prepare_image.py`'s `text_color_*`) are kept as-is when the file is saved.

**On a source tab:**
- Each photo shows `Title · Location · Film` and `Artist ‡ Date`, plus its tags.
- **Edit info** changes any field.
- **↓ xml** downloads the sidecar.
- The tag bar filters the source's photos by tag.

## Captions
A frame can have a photo's caption rendered into the image on the server. It uses the same layout as the original EE03 firmware: a left run `Title · Location · Film` and a larger right run `Artist ‡ Date`.

Set it per device in `devices.yaml`:
- **`captions: below_strip`:** in the white band under a panorama strip. Black text.
- **`captions: overlay_bottom`:** over the bottom of the photo, inside the strip on strip frames. Each half gets its own color for contrast with what's under it:
  - **Gray panels:** `prepare_image.py`'s gray levels, no outline. This is how the old EE03 firmware's captions looked on a 778 strip.
  - **Color panels:** black or white, with an outline.
- **`captions: none`:** the default.
- **`caption_size`:** sets the smaller text's px. The default scales with the panel.

**Font:** the Docker image installs DejaVu Sans for wide character coverage. Outside Docker the server uses a system font if it finds one, else Pillow's built-in font, which only covers basic Latin. The `·` and `‡` separators are drawn as shapes, so they don't depend on the font.

**Caching:** caption text is part of the image's cache key, so editing a title gives the frame a fresh image on its next pull.

## EE03 panorama frame (`esp32_pull` + `ee03_gray16`)
This serves the DIY 10.3" EE03 frame; its firmware is in `esp32-projects/xiao_s3_ee03_pull_frame/`.

**The `ee03_gray16` pipeline** does what `python-projects/grayscale_image_conversion/prepare_image.py` does:
1. Places the photo in a panorama strip on a white 1872×1404 canvas. `options.strip_height` (661 or 778) and `options.fit` (`letterbox` or `cover`) control the strip.
2. Tunes it in gray and draws the caption.
3. Dithers to 16 grays (Floyd–Steinberg).
4. Nibble-packs it into the exact 1,314,144-byte `.bin` the panel takes.

The UI previews decode the `.bin` back to a PNG.

**The `esp32_pull` protocol:**
- **`GET /esp32/v1/pull`** (`X-Access-Token` header): returns JSON with a status of `show`, `keep`, `none` or `error`. A `show` includes `image_url`, `image_bytes`, `sha256` and `name`. Every response includes `next_check_s` and `next_check_at`.
- **`keep`:** the frame already shows the right image (it reports `current=<name>`), so it skips both the download and the panel refresh.
- **`GET /esp32/v1/signal`:** confirms the display after the panel refresh.

The schedule blocks, wake offset and log are the same as for the Bloomin8.

## Tuning
These parameters are set per device in `devices.yaml` → `tuning` and can be overridden per photo. Per-photo tuning is global to the photo; there's no per-frame or per-playlist photo tuning. The pipeline applies them in this order:

1. **`lift` / `lift_threshold`** (defaults 0 / 90): soft shadow lift. Pixels darker than the threshold (luma 0–255) are raised by up to `lift`, most strongly at black. Spectra 6 tends to crush deep shadows.
2. **`gamma`:** applied to luma only, so hue and saturation are kept. >1 lightens midtones, <1 darkens.
3. **`brightness`, `contrast`, `saturation`:** 1.0 = unchanged.

The lift formula and luma-gamma approach come from [fwmone/eink-optimize](https://github.com/fwmone/eink-optimize) (MIT). Its author's Bloomin8 settings are:
- saturation 1.15
- gamma 0.85 in its convention, which is about **1.18** here
- lift 13 / threshold 90
- no contrast boost

A good first test card is A = your current settings, B = that recipe, C = halfway between.

## Test cards (tuning A/B/C on the real panel)
Open **Sources → Test cards**. It renders one image at the frame's resolution, split into three columns (A/B/C), and each column is tuned with its own saturation, contrast, brightness and gamma.

- **Color card:**
  - Spectra 6 ink swatches
  - hue sweeps at full and half saturation
  - gray ramp and an 11-step wedge
  - skin and pastel patches
  - ink tint ramps
- **Black & white card:**
  - 16-step wedge and a smooth ramp
  - 1-px lines and checkerboards
  - text sizes
  - shadow and highlight steps

Pure ink swatches barely respond to tuning, so judge the differences on the ramps, tints and pastels. Optionally pick a photo for a "photo strip": the same crop of it appears in every column.

- **Save** stores the card in the **Test cards** source (its own `testcards` source, not the Library). It gets neutral per-photo tuning, so the device's tuning isn't applied on top.
- **Save & show next** also queues the card for the frame's next pull. Any photo has a **Show next on ▾** menu too. It's one shot: after that pull the schedule resumes.
- To see it right away, wake the frame and resend its setup (`configure_frame --print-curl`).
- When you've picked a winner, copy that column's values into `devices.yaml` → `tuning`.

## Sources and the photobooth
A **source** is a pool of photos. There are three kinds: the Library, Test cards, and folder sources you define in `devices.yaml`. A folder source feeds in photos from outside, e.g. the `esp32-projects/xiao_s3_sense_photobooth` firmware, which uploads to it.

Add a `sources:` list next to `devices:`:
```yaml
sources:
  - id: photobooth            # lowercase letters/digits/_; not library/testcards/playlist
    name: Photobooth
    folder: sources/photobooth  # relative to DATA_DIR (/data in Docker); bind-mount elsewhere if wanted
    upload_token: "<random>"    # enables uploads; generate like other tokens
    tags: [photobooth]          # added to every new photo's sidecar
```

**Folder behaviour:**
- Files are kept human-readable in the folder (e.g. `2026-10-24_19-02-11_A.jpg`), with the `.xml` sidecar beside each as `<name>.xml` (the `prepare_image.py` convention). Library photos stay content-addressed in `originals/`.
- **Photos arrive two ways:** HTTP upload, or dropping files into the folder (scp, SMB, etc).
- **Sidecar for a new folder photo:** the EXIF date and artist, plus the source's `tags`. A name like `YYYY-MM-DD_HH-MM-SS_A.jpg` also gives the date and a `shot-a` style tag. A same-named `.xml` already in the folder is used as-is.
- **Deleting:** a file deleted from the folder is removed from the server (and from playlists) on the next scan. Deleting a folder-source photo in the UI deletes its file too.

**Scanning:** the server scans folder sources at startup, every 60 s, and when you press **Rescan folder** on the source's tab. Set the interval with the `SCAN_INTERVAL` env var in seconds; `0` disables the periodic scan.

**Upload endpoint:** `POST /sources/<id>/upload`, token-authenticated, so it isn't behind the admin password.
- **Headers:** `X-Access-Token: <upload_token>`, `X-Filename: <name>.jpg`, `Content-Type: image/jpeg`. The body is the raw JPEG, at most 25 MB.
- **Responses:**
  - `200 {"status":"stored"|"duplicate","id":N,"name":"stored filename"}`. `duplicate` means the same content is already on the server. A name collision with different content is stored as `name-2.jpg`.
  - `401` bad token
  - `400` bad filename or empty body
  - `413` too large
  - `422` not an image

```bash
curl -X POST -H 'X-Access-Token: <token>' -H 'X-Filename: test.jpg' -H 'Content-Type: image/jpeg' --data-binary @test.jpg http://<pi>:8080/sources/photobooth/upload
```

## Upgrading
The first start on the new version migrates the database automatically, once (schema version 2, recorded in a `meta` table):
- each frame's old playlist becomes a playlist named after the frame
- old blocks are converted to source/selection/hold. Behaviour was checked to be identical, i.e. the same 24 h plan.
- a frame's old playlist position becomes its cursor
- frames that were on the `devices.yaml` fallback get explicit blocks on their old playlist

Back up the database first:
```bash
cp data/db.sqlite data/db.sqlite.bak
```

## Running

### Docker (Pi)
```bash
mkdir -p data && cp devices.example.yaml data/devices.yaml   # then edit tokens/secrets
docker compose up -d --build
```
- Set `PUBLIC_BASE_URL` in `docker-compose.yml` to the URL the frames use to reach the Pi.
- Set `ADMIN_PASSWORD` to password-protect the web UI. The frame endpoints are always open (they use the token and path secret).
- The UI is at `http://<pi>:8080/`.

### Dev on the Pi (live reload)
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```
`server/` is mounted into the container, and uvicorn restarts whenever a file is saved. Only rebuild (`--build`) when `requirements.txt` changes.

### Local dev
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p data && cp devices.example.yaml data/devices.yaml
DATA_DIR=./data .venv/bin/uvicorn server.app:app --reload --port 8080
```

Simulate a frame:
```bash
curl -H 'X-Access-Token: CHANGE_ME_TOKEN' 'http://localhost:8080/eink_pull?device_id=test&pull_id=1&battery=80'
```

### Pointing a Bloomin8 at the server
Wake the frame so it's reachable, then:
```bash
python -m server.tools.configure_frame living_room_73 <frame-ip> --server http://<pi-ip>:8080
```
The tool does two things:
1. PUTs `/upstream/pull_settings` with the device token and a first wake 2 minutes out.
2. Switches the frame to **single-image mode** (`POST /show {"play_type":0}`), keeping whatever it currently shows. See "Local playback overrides pulls" below for why. Skip this with `--keep-local-playback`.

Use `--dry-run` to only print the PUT.

- **On the Pi:** run it inside the container with `docker compose exec eink-photo-server python -m server.tools.configure_frame …`. That container already has `/data`.
- **Locally:** prefix the command with `DATA_DIR=./data`.
- **If the server can't reach the frames' VLAN:** this happens when the firewall only allows IoT → server. Add `--print-curl` and run the two printed commands from a machine that can reach the frame, e.g. the one running the Bloomin8 app. The second one needs `python3`.

## Data (`DATA_DIR`, `/data` in Docker; git-ignored)
- `devices.yaml`: device registry. It holds the tokens, so it stays out of git.
- `db.sqlite`: photos, playlists, per-frame source positions, device state, and pull history.
- `originals/` and `thumbs/`: Library uploads, stored by sha256.
- Folder sources' files (e.g. `sources/photobooth/`), under `DATA_DIR` unless configured otherwise. See below.
- `cache/<device>/`: prepared images. Each is keyed by source, pipeline + version, geometry, tuning, and focal point.

## Bloomin8 notes / to verify on hardware
- **Protocol:** the response shape follows Lukafin/bloomin8-pull-server and fwmone/bloomin8_pull. HTTP is always 200, and the real `status` (200 SHOW / 204 / 4xx ERROR) is in the JSON body. Times are ISO-8601 UTC with a `Z` suffix.
- **Device lookup:** devices are identified by **token**. The frame's own `device_id` is recorded and shown in the UI, but it doesn't have to be configured.
- **`output_rotation`:** defaults to 90 in the example. Lukafin stores landscape images rotated 90° CW, so the file is portrait-shaped but still named `_L.jpg`. Check with a photo that has an obvious "up". If it's wrong, change the value and reload; the new cache key means the next pull serves a fresh image.
- **Local playback overrides pulls.** Pull mode doesn't stop the frame's own slideshow.
  - **Symptom:** old photos from the frame's own gallery replace server images every few minutes, and the battery drains faster.
  - **Cause:** the frame is still in gallery (`play_type` 1) or playlist (`play_type` 2) mode, and its own timer (`play_duration`, e.g. 300 s) keeps advancing the local slideshow.
  - **Check:** `curl http://<frame>/deviceInfo` and look at `play_type`, `playlist`, `gallery` and `next_time`.
  - **Fix:** `configure_frame` does this, or by hand: `POST /show {"play_type":0,"image":"<deviceInfo image>"}`. Afterwards `next_time` falls back to `sleep_duration`, which is about 3 days.
  - **Where pulled images go:** the frame stores them in a local `upstream` gallery; leave that gallery alone.
  - **`pre_image`** in `/upstream/pull_settings` is read-only (the last displayed image) and can't be cleared.
  - **API references:** [Schedule Pull API](https://github.com/ARPOBOT-BLOOMIN8/eink_canvas_home_assistant_component/blob/main/docs/Schedule_Pull_API.md) and [local API (OpenAPI)](https://github.com/ARPOBOT-BLOOMIN8/eink_canvas_home_assistant_component/blob/main/openapi.yaml).
- **Native panel orientation:** the 7.3" reports `width: 480, height: 800` in `/deviceInfo`, i.e. it's natively portrait. That's why a landscape-mounted frame needs `output_rotation: 90`.
- **File size:** the frame's maximum file size and support for progressive JPEGs are unknown. We send baseline JPEGs at q92, and the log records each image's byte size.
