# Lighted Sculpture: show runner — project overview & goals

Working spec for `wled_lighting_tools/`. This is the document to revise before and during the build; `CLAUDE.md` in this folder is a short summary that points here.

Status: milestones 1–6 built (6 not yet run on the sculpture). **Bench check on the sculpture passed (2026-11-11)** — see "Hardware bench results". **Deployed on the Pi 5 in Docker (2026-11-13)**; first scheduled evening on the sculpture still to check.

## Goal

A Python service on a Raspberry Pi (4 or 5) that streams animations to a QuinLED Dig-Uno running **stock WLED** over DDP, on a sunset-based schedule. Plus a simulator so shows can be written and tested without the hardware.

The Dig-Uno firmware is not modified. All control goes through WLED's network interfaces (DDP over UDP, JSON API over HTTP).

## Hardware (installed and working)

- **Pixels:** 4 × Light-o-rama 12V WS2811 bullet strings in use, 50 px each, 4" spacing, xConnect. **200 px total.** A 5th identical string is a spare and is not installed.
- **Power:** Mean Well LRS-150-12 (12V, 12.5A). Full-white load is about 60W / 5A.
- **Controller:** QuinLED Dig-Uno v3 (ESP32, WLED), 2 outputs:
  - Output 1: GPIO16, start 0, length 100 (strings 1–2)
  - Output 2: GPIO3, start 100, length 100 (strings 3–4)
- **Network:** controller is reachable on the LAN by mDNS name or IP; the Pi deployment uses its IP (DHCP reservation), since `.local` doesn't resolve inside Docker. The real host goes in config; nothing is hardcoded.
- **Location:** Madison, WI (about 43.07 N, -89.40 W), timezone America/Chicago.

## Sculpture geometry

A DNA-like double helix built around a **central vertical rod** (no backbone "handrails").

- **10 base pairs**, 4.5" rise between them (9 × 4.5" = 40.5" from top to bottom base pair).
- Each base pair = **two "lollipops"** on opposite sides of the rod.
- **Lollipop:** a 7" stem out from the rod + a 7" diameter ring, ring lying flat (parallel to the ground).
- **Twist:** right-handed, about **40°** per base pair (9 steps × 40° = 360°, so the top base pair lines up with the bottom one).
- Bottom base pair is about 14" off the ground. No designated front yet.

### Wiring (per strand)

Two strands of 100 px, one per Dig-Uno output: one on the 3'→5' side, one on the 5'→3' side. Numbering below is the string's own light number (1 = nearest the plug).

Per lollipop, 10 lights, listed top-down (light numbers decreasing), travelling clockwise around the ring viewed from above:

| Order | Where | Top lollipop |
|---|---|---|
| 1 | stem, nearest the rod | 100 |
| 2 | stem, nearer the ring | 99 |
| 3–7 | ring, 5 lights evenly spaced, clockwise from above | 98–94 |
| 8–9 | stem, returning to the rod | 93–92 |
| 10 | rod, on the way down to the next base pair | 91 |

Repeats down the strand; the bottom lollipop is 10…2 and **light 1 is on the rod below the bottom lollipop**, nearest the plug.

Both strands follow the same pattern (clockwise from above, not mirrored). Each 100 px strand is two 50 px strings joined between the 5th and 6th lollipops.

### Confirmed layout (used by `pixel_map.py`)

- Light 1 is pixel 0 of its output (data enters at the bottom); pixel 99 is the top lollipop's stem light nearest the rod.
- Output 1 carries the **3'→5' strand** (confirmed on hardware 2026-11-11), output 2 the 5'→3' — `OUTPUT1_STRAND = "3to5"` in `pixel_map.py`.
- Stem meets the ring at its edge: ring center 10.5" from the rod axis, outer edge 14".
- 4 stem lights on the same stem: 2 outbound, 2 return, at about 1/3 and 2/3 of its length. The map offsets the two legs slightly to either side of the stem so they don't overlap in the preview.
- 5 ring lights evenly spaced, symmetric about the stem joint, one at the far point.
- Each base pair's stems and rings lie in one horizontal plane; the two lollipops are exactly 180° apart.
- Rod light is 2.25" below its lollipop, halfway to the next base pair.

### Coordinates and labels (`pixels.csv`)

- Inches. Origin on the rod axis at ground level, +z up. +x is the direction of the bottom base pair's output-1 lollipop (arbitrary until a front is chosen; `THETA0_DEG` rotates the whole map).
- Columns: `index,x,y,z,output,light,strand,base_pair,part,slot`
  - `index`: 0–199, global DDP pixel index
  - `output`: 1 or 2; `light`: 1–100 along that string
  - `strand`: `3to5` or `5to3`
  - `base_pair`: 0 (bottom) – 9 (top)
  - `part`: `stem`, `ring`, or `rod`
  - `slot`: stem 0–3 in top-down travel order (0 = outbound near rod, 1 = outbound near ring, 2 = return near ring, 3 = return near rod); ring 0–4 clockwise from above (2 = far point); rod 0
- Shows get the labels too, so the show interface becomes `render(t, xyz, meta)`.

## Architecture

### 1. WLED fallback (configured in WLED, not in this repo)

Time & Macros timers turn on a built-in preset at sunset and turn it off late at night, so the sculpture still runs if the Pi is down. WLED's own location/timezone (Config → Time & Macros) must be set to Madison for its sunset timer to line up with the Pi's.

### 2. Pi show runner (this repo)

- **Effects** (`effects/`; called `shows/` before milestone 6): one module per effect, interface
  `render(t: float, xyz: np.ndarray[N,3], meta) -> np.ndarray[N,3] uint8` (floats 0..1 also accepted)
  where `t` is seconds since the effect started, `xyz` is the pixel map, and `meta` holds the per-pixel labels from `pixels.csv` (strand, base_pair, part, slot) so effects can target stems, rings, and rods. Effects are pure functions of time and position, so they render identically on hardware and in the simulator.
- **Effect options:** an effect can declare `OPTIONS = {name: default}`; it then gets `render(t, xyz, meta, opts)`, and an optional `prepare(opts)` validates and parses them once. Options come from `play.py -o key=value`, a show entry's `options:` mapping, or the defaults. A `seed` option left at `None` gets a random value per run (logged so a good one can be pinned; the preview's Restart re-rolls it), so "random" effects are still pure functions of `t` within a run.
- **Shows:** a show is a named list of effects (and `wled:<id>` presets), defined in the config's `shows:` section and modelled in `shows.py` (`Entry`, `Show`, `parse_entries`, `load_shows`). Each schedule window plays one show. See "Shows, effects and a tabbed dashboard (milestone 6)".
- **WLED presets in a show:** an entry can be `wled:<preset_id>`. The runner stops DDP streaming and sends `POST /json/state {"ps": id}`; WLED runs its own effect until the next slot.
- **Scheduler:** uses `astral` to compute sunset/sunrise daily. YAML config, e.g.
  ```yaml
  schedule:
    windows: [{on: sunset - 15m, off: "23:00", show: evening}]
    minutes_each: 10
  shows:
    evening: {effects: [rainbow_helix, wled:3, twinkle]}
  ```
  (Before milestone 6 this was a single `schedule.rotation:` list; that form still loads as a show named `evening`.)
- **On-time:** send `{"on": true, "bri": N}`, then start streaming.
  **Off-time:** stop streaming, then send `{"on": false}`.
- **Deployment:** Docker on the Pi (`Dockerfile` + `docker-compose.yml`, `restart: unless-stopped`, so it starts at boot and after crashes). The config is `data/config.yaml` in a mounted `data/` dir (`WLED_CONFIG=/data/config.yaml`), so the dashboard can rewrite it; the container runs as uid 1000; logs capped by json-file rotation. Only one DDP sender at a time: stop the container before bench tools touch the sculpture.
- **Web dashboard:** built (milestone 5), on port 8049, split into three tabs in milestone 6. See "Web dashboard (milestone 5)" and "Shows, effects and a tabbed dashboard (milestone 6)" below, and README "Dashboard".

### 3. Preview / simulator

Renders effects from the pixel map so they can be developed without the hardware. See "Proposals" below for the recommended form.

## Web dashboard (milestone 5)

*Milestone 6 renamed shows to effects, added named shows and split the page into tabs (next section). This section is the milestone 5 design; where it says "show" it means what are now effects, and `dashboard.js` is gone.*

A web page on the Pi for watching and steering the sculpture, served at `http://<pi>:8049/`.

Decided 2026-11-13:
- **Scope:** all three pieces: status + controls, a live view, and a settings editor.
- **Server:** FastAPI + uvicorn.
- **Saving:** edits are written back to `config.yaml` with ruamel.yaml, which keeps the comments.
- **Password:** optional, via `ADMIN_PASSWORD`.

### Shape

The dashboard runs **inside the runner process**, so it sees and steers what is actually playing. It doesn't simulate it.

- `runner.py` starts uvicorn in a daemon thread (`--web-port`, default 8049; 0 turns the dashboard off). The control loop stays on the main thread, so SIGTERM handling is unchanged.
- **The web side never touches runner state directly.** Its requests go on a `queue.Queue` of commands, which the control loop drains every `TICK` (0.25 s). Reads go to a status snapshot that the loop rebuilds each tick under a lock. The runner's state stays single-threaded, as it is now.
- **Live view:** `Mixer.__call__` keeps the last frame it returned. An SSE endpoint sends it at about 15 fps (base64 RGB, 600 bytes). Outside a window, or while a `wled:<id>` preset runs, it sends "idle"/"preset" instead.

### Pages and API

One page, `web/static/index.html` + `dashboard.js`, in plain JS like `preview/`, with no CDN.

1. **Status:**
   - **Window:** whether it's on, plus today's sunset/sunrise and the next window.
   - **Now playing:** the current entry and its options, time left, and what's next.
   - **Brightness:** the current scale.
   - **WLED:** reachable or not (the last API result, plus a `/json/info` check every 60 s), and its `bri`.
   - **Log:** the last ~100 lines, from a ring-buffer logging handler.
2. **Controls** (all go through the command queue):
   - **Skip:** next entry.
   - **Play now:** a show (with options) or `wled:<id>`, for N minutes. The rotation then resumes.
   - **On now:** until the current window's end, or for N minutes outside a window.
   - **Off until next window.**
   - **Live scale slider:** applies straight to the current `Player.scale`. A separate "save" button stores it.

   These overrides live in memory and a restart clears them, which is fine for one-offs.
3. **Live view:** the canvas 3D renderer from `preview/index.html`, moved into a shared `web/static/sculpture.js`. The preview page loads that same file (`preview/server.py` also serves it), so there's one renderer.
4. **Settings:** edits only the `schedule:` section:
   - windows (`on`/`off` expressions, previewed with the next 7 days computed by `schedule.py`)
   - `brightness`, `scale`, `minutes_each`, `shuffle`, `transition_seconds`, `reassert_on`
   - the rotation: reorder, add or remove entries, minutes per entry, and per-show options. The option fields are seeded from each show's `OPTIONS` defaults, with `DESCRIPTION` alongside, and values are parsed with `shows.parse_option`.

   The `wled:` and `location:` sections stay hand-edited, because changing them means a restart.

API sketch: `GET /api/status`, `GET /api/stream` (SSE), `GET /api/shows` (name, description, `OPTIONS`), `GET /api/pixels`, `POST /api/cmd/{skip|play|on|off|scale}`, `GET/PUT /api/settings`, `GET /api/schedule?days=7`.

### Saving settings safely

- **Validate first:** `PUT /api/settings` parses windows with `Schedule.from_config`, rotation entries with `parse_rotation`, and show options by building a `shows.Player` for each entry, so `prepare()` gets to reject bad values. Any error goes back to the page, and nothing is written.
- **Write:** a ruamel.yaml round-trip changes only the edited keys under `schedule:`, keeping comments and order. It writes a temp file, then `os.replace` swaps it in. The previous file is kept as `config.yaml.bak`.
- **Apply live:** the write is followed by an `apply_config` command. The loop rebuilds the schedule and rotation and updates the scale/fade, without restarting the stream. If the current entry is still in the rotation it keeps playing; otherwise the runner moves on. If brightness changed during a window, the new `bri` is sent.
- **Docker:** `os.replace` can't swap a bind-mounted *file*, so the config moves into a mounted directory:
  - Compose mounts `./data:/data`, and the Dockerfile CMD becomes `runner.py --config /data/config.yaml`. `data/` is git-ignored.
  - One-time migration on the Pi: `mkdir data && mv config.yaml data/`.
  - Running locally (venv) still defaults to `./config.yaml`.

### Password

If the `ADMIN_PASSWORD` env var is set in `docker-compose.yml`, every route needs HTTP Basic auth (any user name). Empty means open, the same scheme as `eink_photo_server`.

### Files

- **New:**
  - `web/app.py`: the FastAPI app, built around the `Runner`.
  - `web/config_edit.py`: the ruamel round-trip, validation and atomic write.
  - `web/static/{index.html, dashboard.js, sculpture.js}`.
- **Changed:**
  - `runner.py`: command queue, status snapshot, `apply_config`, log ring buffer, last-frame capture in `Mixer`, web thread.
  - `preview/index.html` and `preview/server.py`: use the shared `sculpture.js`.
  - `requirements.txt`: add `fastapi`, `uvicorn` and `ruamel.yaml`, unpinned.
  - `Dockerfile` and `docker-compose.yml`: `ports: "8049:8049"`, `./data:/data`, `ADMIN_PASSWORD`.
  - `.gitignore`: add `data/`.
  - README, CLAUDE.md files.

**Memory:** FastAPI + uvicorn add roughly 30–40 MB on a 1 GB Pi that's already about 620 MB in use with the desktop. Check `docker stats` after deploying.

### Build order

1. **Runner internals:** command queue, status snapshot, `apply_config`, log buffer, last frame. Check by driving the queue from a REPL with `--preview --force-on`.
2. **FastAPI status + controls**, with the password.
3. **Shared `sculpture.js`:** the live view in the dashboard, and the preview switched over to it. Check that the preview still works.
4. **Settings editor:** ruamel write, validation, live apply, and the `data/` migration.
5. **Docker + docs.**

### Verification

- **Without the sculpture:** in the container, run `docker compose run --rm -p 8049:8049 wled-show-runner python runner.py --preview --force-on --config /data/config.yaml`. That sends DDP to the container's own localhost and makes no WLED calls, but the live view still shows the frames.
  - Check that skip / play now / on / off / scale act within a tick and show up in the log pane.
  - Make an invalid edit (a bad window expression, an unknown show option) and confirm it's rejected with a message and that `config.yaml` is unchanged.
  - Make a valid edit and confirm the rotation changes without the stream dropping, that `diff data/config.yaml.bak data/config.yaml` shows only the edited keys, and that the comments survived.
- **Password:** with `ADMIN_PASSWORD` set, `curl` without credentials gets 401.
- **On the sculpture:** with the runner's container stopped, one evening's run that uses the dashboard's controls. The live view should match the sculpture.
- **Afterwards:** `docker stats` memory, then a reboot. The dashboard comes back with the runner.

## Shows, effects and a tabbed dashboard (milestone 6)

The goal: named **shows**, such as "morning" and "evening", each built from individual **effects** (dna_strand, rainbow_helix, firework…). Each schedule window plays one show. The dashboard splits into three tabs: **Scheduler**, **Preview** and **Show builder**.

**Built 2026-11-13.** The design below is what was built. Differences from the plan: Play now for a show during a window lasts until the window ends unless minutes are given, and the builder's Play on sculpture now requires the show to be saved.

Decided 2026-11-13:
- **Naming:** rename the code's "shows" to "effects", so "show" only ever means a named list of effects.
- **Per-show settings:** each show can set its own timing (minutes per effect, shuffle, crossfade) and brightness (`scale`). Shows can also include `wled:<id>` presets.
- **Preview tab:** watches the live output, and also has an **audition** mode that plays any effect or show in the browser only, without sending it to the sculpture.

### Rename: shows → effects

- **Files:**
  - `git mv shows effects`. `shows.Player` becomes `effects.Player`, plus `available()`, `load()` and `parse_option()`.
  - Rotation entries are written `{effect: name, …}`. The old `{show: name}` key is still accepted when reading.
  - `play.py` still plays one effect, and its help text and `--list` say "effects".
  - The preview's Source menu says "Effect".
- **Docs:** README, PROJECT.md and both CLAUDE.md files. The show-writing guide becomes "Writing an effect": `render(t, xyz, meta[, opts])`, `OPTIONS`, `prepare()`, `DESCRIPTION`, all unchanged.

### Config shape

```yaml
schedule:
  default_show: evening        # windows without show:, and the dashboard's "Turn on"
  windows:
    - {on: sunset - 15m, off: "23:00", show: evening}
    - {on: "06:00", off: sunrise + 15m, show: morning}
  brightness: 160              # WLED master bri (global)
  scale: 1.0                   # global defaults, used when a show doesn't set its own
  minutes_each: 10
  shuffle: false
  transition_seconds: 2
  reassert_on: false

shows:
  evening:
    effects:
      - rainbow_helix
      - {effect: dna_strand, minutes: 5, options: {motion: up}}
      - firework
      - wled:1
  morning:
    scale: 0.5                 # optional per-show: scale, minutes_each, shuffle, transition_seconds
    effects: [twinkle, ring_spin]
```

- **Backward compatible:** a config with no `shows:` but a `schedule.rotation:` loads as one show, `evening`, set as the default. The current Pi config keeps working unchanged. The first save from the dashboard writes the new shape and drops `schedule.rotation`.
- **Show names:** `[a-z0-9_-]`, 1–32 characters.

### Runner

- **Windows name their show:** `schedule.Window` gets a `show` field, and `intervals()` / `active()` return `(start, end, show)` in place of `(start, end)`. The callers to update are `runner.py`, `print_schedule` (which now lists the show per window) and `web/app.py`.
- **Per-show state:** the runner builds one `Show` per config entry (effects as `Entry` list, plus scale, minutes, shuffle and fade, with the globals filled in). It tracks `self.show`. When a window starts, or the next window wants a different show, it switches rotation, resets the rotation position and crossfades into the new show's first effect. The scale also changes per show.
- **Dashboard commands:**
  - `play` takes `{show: name}` (switch to that show now; outside a window this starts a manual window) or `{effect: name, options, minutes}` (one-off, as today).
  - `on` takes an optional `show` and defaults to `default_show`.
  - `apply_config` reloads all shows. If the current show still exists and the current effect is still in it, that effect keeps playing.
- **Status** gains `show` (current show name) and the show of each upcoming window.

### Audition (Preview tab, browser only)

- **`web/audition.py`:** an `Auditioner` that renders into its own `Mixer`, using the same `effects.Player` and crossfade, at 20 fps on a thread. It sends no DDP. It only runs while a browser is watching, and stops 10 s after the last `/api/audition/stream` client leaves.
- **Endpoints:**
  - `POST /api/audition` takes `{effect, options}` or `{show}`, or an unsaved show body straight from the builder, plus `seconds_each` (default 20, so a whole show can be skimmed quickly).
  - `POST /api/audition/next` and `/api/audition/stop`.
  - `GET /api/audition/stream` (SSE, same frame format as `/api/stream`).
- **Cost:** rendering 200 px with numpy is cheap. The real stream's timing is unaffected, because audition runs in its own thread with its own Players.

### Dashboard tabs

Every tab shares a header: the title, state and WLED chips, and a compact **now playing** bar showing the current show › effect, time left and a Skip button. Tabs use `#scheduler`, `#preview` and `#builder` in the URL, so a reload stays on the same tab. Unsaved settings changes are flagged on the tab that has them.

1. **Scheduler:**
   - **Now:** the current show and effect, its options, the window, sun times, and WLED status.
   - **Controls:**
     - Turn on, choosing a show (defaults to the default show)
     - Off until next window
     - Back to schedule
     - Play a show now / play an effect now
     - The live brightness slider
   - **Windows editor:** on/off times plus a show picker, with the 7-day preview listing each window's show.
   - **Global settings:** default show, WLED brightness, the default scale/timing, and re-assert.
   - The log.
2. **Preview:**
   - The 3D view, with a **Live / Audition** switch.
   - In audition mode: pick an effect (with an options form) or a show, then Play, Next or Stop, plus a seconds-per-effect setting.
   - View and spin buttons.
   - A banner makes it clear that audition doesn't affect the sculpture.
3. **Show builder:**
   - **Show list:** new, duplicate, rename, delete. A show used by a window or set as the default can't be deleted, and the page says why.
   - **Editor for the selected show:** its effects list (reorder, minutes, options per effect, `wled:<id>` presets), plus per-show timing and brightness overrides, with the global value shown as the placeholder.
   - Buttons: **Audition** (switches to Preview and plays this show, including unsaved edits) and **Play on sculpture now**.

**Saving:** one Save & apply button for all three tabs, writing `schedule:` and `shows:` together.

**Files:** split `dashboard.js` into `common.js` (api, el, time formatting, settings state + save, tabs), `scheduler.js`, `preview.js` and `builder.js`. `index.html` gets one section per tab, and `sculpture.js` is unchanged.

### Saving

- **Settings API:** `GET/PUT /api/settings` becomes `{schedule: {...}, shows: {name: {...}}}`.
- **Validation** adds these checks to today's:
  - every window's show exists, and so does `default_show`
  - every show has at least one effect
  - per-show values are in range
  - show names are valid
- **ruamel write:** updates `schedule:` keys as today. `shows:` is a map that is created, updated or deleted per show; unchanged shows aren't touched, so their comments stay. The legacy `schedule.rotation` is removed on that first save.

### Build order

1. **Rename:** shows → effects, with the old key accepted when reading. Check that `play.py --list`, the preview and the runner all still work.
2. **Config model:** shows and per-window show in `schedule.py` and `runner.py`, plus the legacy fallback. Check with `runner.py --schedule` and `--preview --force-on`, using a config with two shows and back-to-back windows.
3. **Saving:** `config_edit` for `shows:` and the new windows.
4. **Audition:** `web/audition.py` and its endpoints.
5. **Front end:** tabs and the JS split.
6. **Deploy:** docs, then redeploy. The Pi's `data/config.yaml` keeps working through the legacy fallback, and you choose when to save it in the new shape.

### Verification

- **Without the sculpture:**
  - In `--preview` mode, run a two-show config with windows a few minutes apart, and confirm the runner switches shows at the boundary.
  - Check play show / play effect / on-with-show.
  - Audition an unsaved show, and confirm that the real stream's fps is unaffected and that audition stops when the tab closes.
  - Save, then confirm the comment and key diff is tidy and that the legacy config migrates.
- **Page checks:** each tab at desktop and phone widths, using the same captured-data harness as milestone 5. In a real browser if the Chrome extension is connected.
- **On the sculpture (not yet done):** an evening with the evening show, and a morning window with its own show.

## DDP details

- UDP port 4048, one packet per frame (200 × 3 = 600 bytes of data, well under one MTU).
- Header: `struct.pack("!BBBBIH", 0x41, seq, 0x01, 1, offset, length)`
  - flags `0x41` = version 1 + PUSH
  - `seq` cycles 1–15 (0 means "not used")
  - data type `0x01` = RGB, destination id 1
  - byte offset, data length
- Target about 40 fps. WLED returns to its own effect about 2.5 s after packets stop (realtime timeout, Config → Sync Interfaces).
- "Receive UDP realtime" must stay enabled in WLED.

## Open items

- **Pixel map:** `pixels.csv` is generated by `pixel_map.py` from the measurements above. Refine by editing its constants and rerunning. Pixel IDs and strand assignment verified on hardware (2026-11-11). Still open: choosing a front.
- ~~**Color order:**~~ resolved — the test-pattern run on the sculpture came out right (2026-11-11).
- **Power:** brightness limiter on, about 10A cap. Each output runs 100 px, so no power injection is needed. At ~5A full white the limiter shouldn't engage in practice.

## Hardware bench results (2026-11-11)

`testpattern.py` run against the real Dig-Uno from a laptop (no Pi yet). Everything worked as expected:

- **Patterns:** all test patterns displayed correctly.
- **Pixel IDs:** lights identify correctly. The map in `pixels.csv` matches the physical stems, rings, and rods (`parts`, `step`/`chase`).
- **Strands:** output 1 = 3'→5', output 2 = 5'→3', matching `OUTPUT1_STRAND = "3to5"`. No swap needed.
- **Brightness:** `--scale` (runner/tool side) dims DDP and `ramp` fades smoothly. WLED's master brightness (`power on --bri 60`) had **no effect on DDP**.

Still to check on hardware: the runner's `wled:<id>` preset hand-off (`{"live": false, "ps": id}`) and a full scheduled evening.

**Pi deployment (2026-11-13):**
- **Setup:** Pi 5 (1 GB, Debian 13), Docker 29.
- **Container:** builds on arm64, and `--schedule` inside it shows the right Madison times in CST.
- **Restarts:** after the process exits, Docker restarts it on its own. On SIGTERM it stops cleanly (exit 0, <0.5 s). After a reboot it came back by itself.
- **Network:** the Pi (192.168.30.x) reaches the Dig-Uno (192.168.20.233) through the router. The firewall must allow TCP 80 and UDP 4048. This hasn't been checked yet: WLED was offline during the deployment.

## Questions to settle

1. **Brightness during DDP.** Does WLED apply its master brightness (`bri`) and the limiter to realtime data with our settings? There's a realtime "force max brightness" option in Sync Interfaces. Decide whether brightness is controlled by WLED's `bri` or scaled in the runner, and verify on hardware.
   *Resolved 2026-11-11:* WLED's `bri` does **not** scale DDP on this setup. Most likely "Force max brightness" is on under Sync Interfaces → Realtime; not checked. So DDP shows are dimmed only by the runner's `schedule.scale` (or `--scale`), and `schedule.brightness` only affects `wled:<id>` presets and WLED's own fallback effect. Still unverified: whether WLED's power limiter caps realtime data. Full white is ~5 A, well under the supply, so it's low stakes.
2. **Handing off to a WLED preset.** While realtime is active, WLED ignores effect changes on the display. Stopping DDP and waiting out the ~2.5 s timeout works but leaves a gap; alternatively, send `{"live": false}` / the `lor` live-override field along with `ps`. Pick one and test it.
   *Implemented:* the runner stops sending DDP, then posts `{"live": false, "ps": id}`. **Verify on hardware** that the preset appears right away rather than after the timeout.
3. **Pi vs. WLED timers.** Both turn the sculpture on around sunset. Confirm they don't fight: the runner's DDP overrides WLED's preset while streaming, and its `{"on": false}` at off-time should come before (or match) WLED's own off timer.
4. **Morning window?** Only an evening window so far. Is a pre-sunrise window wanted (e.g. `on: "06:00"`, `off: sunrise`)?
   *Implemented:* `schedule.windows` is a list; the example config has a commented-out morning window.
5. **Transitions.** Hard cut between shows, or a short crossfade (easy for DDP→DDP; DDP↔preset is limited to what WLED does itself).
   *Implemented:* `transition_seconds` crossfade between DDP shows (0 = hard cut); preset hand-offs are hard cuts.
6. **Daytime/manual override.** A way to run a show on demand outside the schedule (CLI flag now, web UI later).
   *Implemented (CLI):* `play.py <effect>` for one effect, `runner.py --force-on` for the default show. *Web UI:* built in milestones 5–6.

## Proposals (for discussion)

- **Simulator as a DDP receiver.** Besides calling `render()` directly, the preview can listen on UDP 4048 and draw whatever DDP it receives. Pointing the runner at the preview's host then tests the whole pipeline (scheduler, rotation, packet format) with no hardware.
- **Browser preview over matplotlib.** A small local web page (three.js points at `xyz`, colors pushed over a websocket) handles 3D rotation and 40 fps far better than matplotlib, and becomes the basis of the later FastAPI UI. matplotlib stays an option for quick static snapshots.
- **Bench/test CLI first.** Before shows: a tool to send solid R/G/B (color order), single-pixel chase and per-string colors (verifying the map and string order), and a brightness ramp. These are needed to build `pixels.csv` anyway.

## Proposed layout

```
wled_lighting_tools/
  PROJECT.md          this file
  CLAUDE.md
  README.md           setup, Pi install, WLED settings checklist
  requirements.txt    PyYAML so far; numpy, astral (+ preview deps) later
  config.example.yaml host, brightness, schedule (windows), shows
  pixel_map.py        generates pixels.csv (+ SVG check plot); load() reads it back
  pixels.csv          pixel map
  wled/               ddp.py (sender + Streamer thread), api.py (JSON API, stdlib urllib)
  layout.py           Layout: pixels.csv as numpy arrays + derived geometry (the `meta` effects get)
  effects/            one module per effect; __init__.py has the loader + Player; _util.py helpers
  shows.py            Entry, Show, parse_entries, load_shows (named lists of effects)
  play.py             play one effect over DDP (sculpture, preview, or both)
  schedule.py         sun/clock time expressions and on/off windows (astral)
  runner.py           scheduler + show playback + streaming loop; serves the dashboard
  testpattern.py      bench/test CLI
  preview/            server.py (DDP receiver + HTTP/SSE) + index.html (canvas 3D view)
  web/                app.py (FastAPI), config_edit.py (ruamel round-trip), audition.py (browser-only players),
                      static/ index.html, common.js, scheduler.js, preview.js, builder.js, sculpture.js
  Dockerfile          runner image (python:3.13-slim)
  docker-compose.yml  Pi deployment: config.yaml mount, restart unless-stopped, log rotation
```

## Milestones

1. **Bench tools:** DDP sender, WLED JSON client, test-pattern CLI. Confirm color order, string order, and brightness behavior on the real hardware.
   *Status:* built and **verified on the sculpture (2026-11-11)** — see "Hardware bench results".
2. **Pixel map + simulator:** approximate `pixels.csv` from the sculpture description; preview renders shows and receives DDP.
   *Status:* `pixel_map.py` and `preview/` (stdlib DDP receiver + SSE → canvas 3D view) built and checked with `testpattern.py` at ~40 fps. It can also render shows locally (no DDP) with live reload; see milestone 3.
3. **Effects (called shows until milestone 6):** effect interface, loader, and a first handful of effects designed for the sculpture's shape.
   *Status:* built. `layout.Layout` (meta), `effects.Player` (clock, scale, hot reload, keeps last good frame on error), `play.py`, and seven effects: `rainbow_helix`, `sequence` (A/T/G/C read-out), `ring_spin`, `strand_flow`, `twinkle`, `firework` (rocket up the rod, random-palette burst, twinkling fall), `dna_strand` (random complementary sequence in 4 user/palette/random colors, light stems and darker rings, optional rod color, static or flowing up/down at a set bpm; the first effect with options, and its `PALETTES` dict is where holiday color sets go). The preview can run effects locally with live reload. Checked in the preview only, not on the sculpture.
4. **Runner:** astral scheduler, YAML config, rotation (now shows) incl. `wled:<id>`, on/off handling, Docker deployment.
   *Status:* built (`schedule.py`, `runner.py`, `Dockerfile`, `docker-compose.yml`; replaced the earlier systemd unit 2026-11-13). Tested on this Mac against the preview and a fake WLED JSON API: window on/off at the scheduled minute, rotation with crossfades, preset hand-off (DDP pauses), bad entries skipped, WLED-unreachable retries every 30 s while streaming continues, clean SIGTERM. Deployed on the Pi in Docker 2026-11-13 (see "Hardware bench results"); preset hand-off and a full evening not yet checked on the sculpture.
5. **Web dashboard:** status + controls, live view, settings editor (FastAPI, in the runner process). *Status:* built 2026-11-13 (`web/`). Tested on the Pi in `--preview` mode: every control, the settings validation/save/live-apply (comments kept), the password, and the page at desktop and phone widths, rendered from a local copy of the page fed with captured API data. The headless browser here couldn't load it over HTTP. Not yet used against the sculpture.
6. **Shows, effects and a tabbed dashboard:** `shows/` renamed to `effects/`; named shows (`shows.py`, `shows:` config section) with per-show overrides; per-window `show:` and `schedule.default_show`; crossfade between back-to-back windows with different shows; dashboard split into Scheduler / Preview / Show builder tabs with browser-only audition (`web/audition.py`). *Status:* built 2026-11-13. Verified on the Pi in `--preview` mode: a two-show config with back-to-back windows switched morning → evening with a crossfade; all commands; audition (effect, saved show, unsaved show, bad options rejected, idle stop); settings save (renaming a show updates its window, live apply keeps the current effect playing, a legacy config migrates, comments kept); each tab rendered at desktop and phone width from a local copy of the page fed captured API data. No real-browser click-through (the Chrome extension wasn't connected). Not yet run against the sculpture.
