# wled_lighting_tools

Show runner and bench tools for the double-helix light sculpture (QuinLED Dig-Uno, stock WLED, 200 px over DDP). The full spec is in [PROJECT.md](PROJECT.md).

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml      # set wled.host to the Dig-Uno's IP (mDNS name works outside Docker)
```

`config.yaml` is git-ignored.

## Pixel map

```bash
python3 pixel_map.py --svg pixel_map_check.svg
```

Writes `pixels.csv` from the geometry constants at the top of `pixel_map.py`, plus an optional top/side-view check plot. Edit the constants and rerun; don't hand-edit the CSV.

## Shows

A show is a module in `shows/` with `render(t, xyz, meta)`, returning `(200, 3)` RGB as uint8 or floats in 0..1. `meta` is a `layout.Layout`:

- **Labels:** `strand_id`, `base_pair`, `part`, `slot`.
- **Masks:** `stem`, `ring`, `rod`.
- **Geometry:** `theta`, `r`, `h` (0 bottom to 1 top), `lollipop_theta`, `ring_pos`, `strand_pos`, `bp_frac`.

Helpers are in `shows/_util.py` (`hsv`, `rgb`, `color`, `pulse`, `wrap`, `hash01`, ...). Keep `render` a pure function of `t`: use `hash01` for randomness.

Some shows take options (`play.py --list` shows them and their defaults). Pass them with `-o key=value`, or in the rotation as `{show: dna_strand, options: {...}}`. Colors are names (`red`, `gold`, `warmwhite`, ... see `_util.NAMED_COLORS`), `#rrggbb`, or `[r, g, b]`. A show with a `seed` option picks new random colors each run unless you set the seed; the seed in use is printed (or logged by the runner), so a combination you like can be pinned. To add options to a show, define `OPTIONS = {...}` and `render(t, xyz, meta, opts)` (see `shows/__init__.py`).

```bash
python3 play.py --list
python3 play.py sequence --preview              # to the browser preview
python3 play.py sequence                        # to the sculpture (wled.host)
python3 play.py twinkle --also 127.0.0.1        # sculpture + preview together
python3 play.py dna_strand -o motion=up -o bpm=60 -o rod=white -o colors=red,blue,gold,green
python3 play.py dna_strand -o palette=classic -o sequence=GATTACA
```

To write a new show, start the preview, pick the show in the page's **Source** menu, and edit the file. The preview re-imports it on save. If the file has an error, the error shows in the page and the last good frame stays up.

## Browser preview

```bash
python3 preview/server.py                         # open http://localhost:8048
python3 testpattern.py --host 127.0.0.1 parts     # in another terminal
```

The preview stands in for the Dig-Uno. It listens for DDP on udp/4048 and draws the frames on a 3D model of the sculpture built from `pixels.csv`. Anything that speaks DDP can target it, including the Pi runner pointed at this machine's IP. It uses only the Python standard library, and the page draws on a plain canvas, so it works offline.

- Drag to rotate, scroll to zoom, double-click to reset. Front / 3/4 / Top views, plus auto-spin.
- Hover a bulb to see its index, output/light, strand, base pair, part, slot, and current RGB.
- The status chip shows live/idle, fps, the sender's address, and DDP sequence gaps. After 2.5 s without packets the frame dims: that's when the real sculpture would fall back to its WLED effect.
- **Source** menu: "DDP input" (default) or any show in `shows/`, rendered locally with live reload. `--show NAME` starts on one. Local shows run with default options; **Restart** re-rolls a random seed (new colors for `dna_strand`). For other options, use `play.py <show> --preview -o ...`.
- Options: `--ddp-port`, `--http-port`, `--bind 127.0.0.1` (local only; the default 0.0.0.0 accepts DDP from the LAN). Only one program can hold udp/4048 at a time.

## Runner (scheduled shows)

`runner.py` turns WLED on at each window's start (`{"on": true, "bri": N}`), plays the rotation, and turns it off at the window's end. The schedule, rotation, and brightness live in `config.yaml` (see `config.example.yaml`).

```bash
python3 runner.py --schedule               # next 7 days: sunrise/sunset and on-windows
python3 runner.py --preview --force-on     # rotation into the local preview now, no WLED API calls
python3 runner.py --force-on               # rotation on the sculpture now, ignoring the schedule
python3 runner.py                          # normal scheduled operation (what the Docker container runs)
```

- **Rotation entries:** a show name, `wled:<preset id>`, or `{show: name, minutes: N}`. For a preset, DDP stops and the runner sends `{"live": false, "ps": id}`, so WLED runs its own effect for that slot.
- **Failures:** if WLED is unreachable, API calls are retried every 30 s and streaming carries on. A show that errors keeps its last good frame. Invalid rotation entries are logged and skipped.
- **Stopping mid-window** (Ctrl-C, SIGTERM, crash) only stops streaming. WLED falls back to its own effect ~2.5 s later, which is the intended fallback.
- **YAML note:** PyYAML reads a bare `on:` key as boolean `true`. The schedule parser accepts that, so `on:` / `off:` work as written.

### Dashboard

The runner serves a web dashboard at `http://<pi>:8049/` (`--web-port`, 0 turns it off). It runs inside the runner process, so it shows and controls what is actually playing.

- **Now:** the current show and its options, time left, what's next, the window, today's sunrise and sunset, and whether WLED is reachable.
- **Controls:**
  - skip to the next show
  - play a show (with options) or a WLED preset now, for N minutes, then return to the rotation
  - turn on now (for N minutes outside a window)
  - off until the next window
  - back to the schedule
  - a live brightness slider (applies `scale` immediately; **Save** writes it to the config)

  These overrides live in memory, so a restart drops them.
- **Live view:** the frames the runner is sending, on the same 3D model as the preview (`web/static/sculpture.js` is shared by both pages). It shows nothing while a `wled:<id>` preset runs, since WLED draws that itself.
- **Settings:** the `schedule:` section of the config:
  - on/off windows, with a 7-day preview
  - brightness, scale, minutes per show, crossfade, shuffle and re-assert
  - the rotation (order, minutes, per-show options)

  Changes are checked before saving: window expressions are parsed, and show options go through the show's own `prepare()`. They're then written back with ruamel.yaml, so comments and order survive, and applied without restarting the stream. The previous file is kept as `config.yaml.bak`. `wled:` and `location:` stay hand-edited and need a restart.
- **Log:** the runner's last ~150 log lines.
- **Password:** set `ADMIN_PASSWORD` in `docker-compose.yml` to require HTTP Basic auth (any user name). Empty means open to the LAN.

To try the dashboard without the sculpture, run `python3 runner.py --preview --force-on` and open `http://localhost:8049/`.

### Install on the Pi (Docker)

The runner and its dashboard run permanently in Docker (`docker-compose.yml`, `restart: unless-stopped`), so they come back after reboots and crashes. The dashboard is on port 8049. The preview isn't part of it; run that from a venv as above.

**One-time setup:**

- Install Docker. This also enables `docker.service` at boot. Log out and back in after adding yourself to the `docker` group.
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  ```
- Give the Dig-Uno a **DHCP reservation** on the router, and put that IP in `wled.host`. `.local` mDNS names don't resolve inside the container. The runner would just keep retrying, and the sculpture would stay on WLED's fallback effect.

**Deploy:**

```bash
cd ~/dev/makerspace-code/python-projects/wled_lighting_tools
mkdir -p data && cp config.example.yaml data/config.yaml && nano data/config.yaml
docker compose run --rm wled-show-runner python runner.py --schedule   # sanity-check location/timezone
docker compose up -d --build
docker compose logs -f
```

- **Config:** in Docker, the config is `data/config.yaml` (git-ignored), mounted at `/data`. The image sets `WLED_CONFIG=/data/config.yaml`, so every tool run inside the container uses it. The container runs as uid 1000 (the Pi's login user), so files the dashboard writes stay editable. If you deployed before the dashboard existed, move the old config once: `mkdir -p data && mv config.yaml data/`.
- **Updating:** `git pull && docker compose up -d --build`. The image is a snapshot, so edits in the checkout don't reach the running service until you rebuild. To apply a hand edit to `data/config.yaml`, run `docker compose restart`, or just use the dashboard.
- **Only one sender at a time.** Before you run `play.py`, `testpattern.py` or `runner.py --force-on` against the sculpture, run `docker compose stop`. Afterwards, run `docker compose start`. Two DDP streams at once make the sculpture flicker. To run a one-off inside the image, use `docker compose run --rm wled-show-runner python runner.py --force-on`.
- **Logs:** `docker compose logs`. They're capped at about 3 MB (json-file rotation) to spare the SD card.
- **Clock:** the Pi's clock must be right (NTP). If it's wrong at boot, the runner catches up once NTP syncs, because it reads the wall clock every tick.

## WLED settings checklist

- **Config → LED Preferences:** 2 outputs. GPIO16 start 0 length 100; GPIO3 start 100 length 100. Brightness limiter on, ~10 A.
- **Config → Sync Interfaces:** "Receive UDP realtime" on. Realtime timeout ~2.5 s.
- **Config → Time & Macros:** location Madison, WI (43.07, -89.40), timezone America/Chicago; sunset-on / late-off fallback timers.

## Bench check (`testpattern.py`)

Passed on the sculpture on 2026-11-11 (results in PROJECT.md). Rerun it after any wiring or WLED config change.

Every pattern streams until Ctrl-C, and WLED goes back to its own effect ~2.5 s later. `--scale` (default 0.5) scales all colors; `--host` overrides the config.

1. **Reachability:** `python3 testpattern.py info`. LED count should be 200.
2. **Color order:** `python3 testpattern.py rgb`. It prints RED / GREEN / BLUE / WHITE as it sends them. If the sculpture shows something else, fix Color Order in LED Preferences.
3. **Which strand is on which output:** `python3 testpattern.py outputs`. Output 1 is red, output 2 green. If the red strand isn't the 3'→5' side, set `OUTPUT1_STRAND = "5to3"` in `pixel_map.py` and rerun it.
4. **Pixel map:**
   - `python3 testpattern.py parts`: stems orange, rings blue, rods white.
   - `python3 testpattern.py basepairs`: red at the bottom to violet at the top.
   - `python3 testpattern.py step --output 1`: one pixel at a time, with its labels printed. Enter = next, `b` = back, a number jumps to that index, `q` quits.
   - `python3 testpattern.py chase --speed 4`: the same walk, automated.
5. **Brightness / power:** `python3 testpattern.py ramp --scale 1`. On this setup WLED's master brightness (`power on --bri N`) does **not** dim DDP; only `--scale` does. The runner's `schedule.scale` is the dimmer for shows.

Other commands: `solid R G B`, `blank`, `power on|off [--bri N]`.
