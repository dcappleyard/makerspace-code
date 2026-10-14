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

## Playlist behavior
On each pull, the server answers based on the time *now*, never at an exact time:
1. **Paused:** re-serve the last image, or 204 if there is none. Use this for vacation or to freeze a picture.
2. **A time window is active** (e.g. 08:00–10:00): show that item. If several windows are active, rotate among them. A window counts as active from 30 min before its start, because frames wake early.
3. **Otherwise:** show the next un-windowed item in playlist order, wrapping around.
4. **Retry guard:** a pull within 5 min of an unconfirmed one gets the same image again.

`next_cron_time` is set to now + `interval_minutes`. If that falls outside `wake_hours`, it moves to the next wake start. If a window opens before then, it moves to that window's start.

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
This PUTs `/upstream/pull_settings` with the device token and a first wake 2 minutes out. Use `--dry-run` to only print the request.

- **On the Pi:** run it inside the container with `docker compose exec eink-photo-server python -m server.tools.configure_frame …`. That container already has `/data`.
- **Locally:** prefix the command with `DATA_DIR=./data`.

## Data (`DATA_DIR`, `/data` in Docker; git-ignored)
- `devices.yaml`: device registry. It holds the tokens, so it stays out of git.
- `db.sqlite`: photos, playlists, device state, and pull history.
- `originals/` and `thumbs/`: uploads, stored by sha256.
- `cache/<device>/`: prepared images. Each is keyed by source, pipeline + version, geometry, tuning, and focal point.

## Bloomin8 notes / to verify on hardware
- **Protocol:** the response shape follows Lukafin/bloomin8-pull-server and fwmone/bloomin8_pull. HTTP is always 200, and the real `status` (200 SHOW / 204 / 4xx ERROR) is in the JSON body. Times are ISO-8601 UTC with a `Z` suffix.
- **Device lookup:** devices are identified by **token**. The frame's own `device_id` is recorded and shown in the UI, but it doesn't have to be configured.
- **`output_rotation`:** defaults to 90 in the example. Lukafin stores landscape images rotated 90° CW, so the file is portrait-shaped but still named `_L.jpg`. Check with a photo that has an obvious "up". If it's wrong, change the value and reload; the new cache key means the next pull serves a fresh image.
- **File size:** the frame's maximum file size and support for progressive JPEGs are unknown. We send baseline JPEGs at q92, and the log records each image's byte size.
