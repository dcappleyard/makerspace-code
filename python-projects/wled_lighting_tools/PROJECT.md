# Lighted Sculpture: show runner — project overview & goals

Working spec for `wled_lighting_tools/`. This is the document to revise before and during the build; `CLAUDE.md` in this folder is a short summary that points here.

Status: **planning** — no code yet. Sculpture description pending (it will drive the pixel map and the shows).

## Goal

A Python service on a Raspberry Pi (4 or 5) that streams animations to a QuinLED Dig-Uno running **stock WLED** over DDP, on a sunset-based schedule. Plus a simulator so shows can be written and tested without the hardware.

The Dig-Uno firmware is not modified. All control goes through WLED's network interfaces (DDP over UDP, JSON API over HTTP).

## Hardware (installed and working)

- **Pixels:** 4 × Light-o-rama 12V WS2811 bullet strings in use, 50 px each, 4" spacing, xConnect. **200 px total.** A 5th identical string is a spare and is not installed.
- **Power:** Mean Well LRS-150-12 (12V, 12.5A). Full-white load is about 60W / 5A.
- **Controller:** QuinLED Dig-Uno v3 (ESP32, WLED), 2 outputs:
  - Output 1: GPIO16, start 0, length 100 (strings 1–2)
  - Output 2: GPIO3, start 100, length 100 (strings 3–4)
- **Network:** controller is reachable on the LAN by mDNS name or IP. The real host goes in config; nothing is hardcoded.
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
- Which strand is on output 1 is **unknown** — `OUTPUT1_STRAND` in `pixel_map.py` (or `--swap-strands`).
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

- **Shows** (`shows/`): one module per show, interface
  `render(t: float, xyz: np.ndarray[N,3], meta) -> np.ndarray[N,3] uint8`
  where `t` is seconds since the show started, `xyz` is the pixel map, and `meta` holds the per-pixel labels from `pixels.csv` (strand, base_pair, part, slot) so shows can target stems, rings, and rods. Shows are pure functions of time and position, so they render identically on hardware and in the simulator.
- **WLED presets in the rotation:** an entry can be `wled:<preset_id>`. The runner stops DDP streaming and sends `POST /json/state {"ps": id}`; WLED runs its own effect until the next rotation slot.
- **Scheduler:** uses `astral` to compute sunset/sunrise daily. YAML config, e.g.
  ```yaml
  on: sunset - 15m
  off: "23:00"
  minutes_each: 10
  rotation: [rainbow_sweep, wled:3, twinkle]
  ```
- **On-time:** send `{"on": true, "bri": N}`, then start streaming.
  **Off-time:** stop streaming, then send `{"on": false}`.
- **Deployment:** systemd service with auto-restart.
- **Later (optional):** small FastAPI web UI to pick a show and edit the schedule.

### 3. Preview / simulator

Renders shows from the pixel map so they can be developed without the hardware. See "Proposals" below for the recommended form.

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

- **Pixel map:** `pixels.csv` is generated by `pixel_map.py` from the measurements above. Refine by editing its constants and rerunning; verify on hardware with a chase pattern. Still open: which strand is on output 1, and choosing a front.
- **Color order:** not confirmed. Test with solid red, green, and blue and set it in WLED (LED Preferences), not in the runner.
- **Power:** brightness limiter on, about 10A cap. Each output runs 100 px, so no power injection is needed. At ~5A full white the limiter shouldn't engage in practice.

## Questions to settle

1. **Brightness during DDP.** Does WLED apply its master brightness (`bri`) and the limiter to realtime data with our settings? There's a realtime "force max brightness" option in Sync Interfaces. Decide whether brightness is controlled by WLED's `bri` or scaled in the runner, and verify on hardware.
2. **Handing off to a WLED preset.** While realtime is active, WLED ignores effect changes on the display. Stopping DDP and waiting out the ~2.5 s timeout works but leaves a gap; alternatively, send `{"live": false}` / the `lor` live-override field along with `ps`. Pick one and test it.
3. **Pi vs. WLED timers.** Both turn the sculpture on around sunset. Confirm they don't fight: the runner's DDP overrides WLED's preset while streaming, and its `{"on": false}` at off-time should come before (or match) WLED's own off timer.
4. **Morning window?** Only an evening window so far. Is a pre-sunrise window wanted (e.g. `on: "06:00"`, `off: sunrise`)? The config should probably allow a list of windows.
5. **Transitions.** Hard cut between shows, or a short crossfade (easy for DDP→DDP; DDP↔preset is limited to what WLED does itself).
6. **Daytime/manual override.** A way to run a show on demand outside the schedule (CLI flag now, web UI later).

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
  config.example.yaml host, brightness, schedule, rotation
  pixel_map.py        generates pixels.csv (+ SVG check plot); load() reads it back
  pixels.csv          pixel map
  wled/               ddp.py (sender + Streamer thread), api.py (JSON API, stdlib urllib)
  shows/              one module per show
  runner.py           scheduler + rotation + streaming loop
  testpattern.py      bench/test CLI
  preview/            simulator (DDP receiver + browser view)
  systemd/            wled-show-runner.service
```

## Milestones

1. **Bench tools:** DDP sender, WLED JSON client, test-pattern CLI. Confirm color order, string order, and brightness behavior on the real hardware.
   *Status:* built (`wled/`, `testpattern.py`); packet format and the 40 fps rate verified against a local UDP listener. **Not yet run on the sculpture** — see README "Bench check".
2. **Pixel map + simulator:** approximate `pixels.csv` from the sculpture description; preview renders shows and receives DDP.
3. **Shows:** show interface, loader, and a first handful of shows designed for the sculpture's shape.
4. **Runner:** astral scheduler, YAML config, rotation incl. `wled:<id>`, on/off handling, systemd unit.
5. **Optional:** FastAPI web UI for picking a show and editing the schedule.
