# eink_photo_server

One server that feeds all the e-ink photo frames. Frames **pull** on their own timers (battery frames sleep, so pushing is unreliable). The server:
- stores uploaded photos
- prepares them for each frame type (crop, resize, tone tuning, encoding)
- keeps a playlist per frame, with optional time-of-day windows

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

Playlists, scheduling and photo storage are shared by every device.

### Adding a pipeline
1. Create `server/pipelines/<something>.py`.
2. Subclass `Pipeline` and decorate it with `@register`. Implement `prepare()`, and `preview()` if you want one.
3. Set its `name` as a device's `pipeline:` in `devices.yaml`.

Modules in that folder are auto-discovered. Bump `version` whenever the output changes, so cached images are regenerated.

### Adding a protocol
Add `server/protocols/<name>.py` with a FastAPI `router` and a `PROTOCOL` name, then list it in `server/protocols/__init__.py`. Use `schedule.choose()` / `schedule.next_wake()` and `prepare.get_prepared()` so the device shares the playlist logic. The planned ESP32 frame needs this: a "next image + sleep N s" endpoint and a pipeline that pre-dithers and packs 4 bpp.

## Web UI
- **Library** (`/`): upload photos, set crop focal points and per-photo tuning, add photos to a frame's playlist, or "Show next" on a frame.
- **One tab per frame** (`/frame/<id>`): status, block schedule with a next-24-hours timeline, playlist, wake timing, and the frame's log.
- **Test card:** see below.

## Schedule (daily blocks)
Each frame has a daily timeline of blocks, edited on its tab. A block starts at a clock time and runs until the next block starts, wrapping past midnight.

| Block | On a pull the frame gets | Next wake |
|---|---|---|
| **Sleep** | a chosen photo, or a random playlist photo (picked once per night) | when the block ends |
| **Load image** | a chosen photo | when the block ends |
| **Random image** | a random playlist photo (never the one just shown) | every N min |
| **Play playlist** | the next playlist photo; the position carries over between blocks | every N min |

- **Interval alignment:** intervals are counted from the block's start (07:00, 08:00, …).
- **Playlist:** the frame's photo pool, which Random and Play playlist blocks draw from.
- **No blocks yet:** the frame follows the `interval_minutes`/`wake_hours` defaults from `devices.yaml`. **Make these editable** turns those defaults into blocks.

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

**In the Library:**
- Each photo shows `Title · Location · Film` and `Artist ‡ Date`, plus its tags.
- **Edit info** changes any field.
- **↓ xml** downloads the sidecar.
- The tag bar filters the Library by tag (`/?tag=…`).

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
These parameters are set per device in `devices.yaml` → `tuning` and can be overridden per photo. The pipeline applies them in this order:

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
Open the **Test card** tab. It renders one image at the frame's resolution, split into three columns (A/B/C), and each column is tuned with its own saturation, contrast, brightness and gamma.

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

Pure ink swatches barely respond to tuning, so judge the differences on the ramps, tints and pastels. Optionally pick a library photo for a "photo strip": the same crop of it appears in every column.

- **Save to library** stores the card as a normal photo. It gets neutral per-photo tuning, so the device's tuning isn't applied on top.
- **Save & show next** also queues the card for the frame's next pull. Any library photo has a **Show next** button too. It's one shot: after that pull the playlist resumes.
- To see it right away, wake the frame and resend its setup (`configure_frame --print-curl`).
- When you've picked a winner, copy that column's values into `devices.yaml` → `tuning`.

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
- `db.sqlite`: photos, playlists, device state, and pull history.
- `originals/` and `thumbs/`: uploads, stored by sha256.
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
