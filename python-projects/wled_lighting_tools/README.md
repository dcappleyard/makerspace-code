# wled_lighting_tools

Show runner and bench tools for the double-helix light sculpture (QuinLED Dig-Uno, stock WLED, 200 px over DDP). The full spec is in [PROJECT.md](PROJECT.md).

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml      # set wled.host to the Dig-Uno's mDNS name or IP
```

`config.yaml` is git-ignored.

## Pixel map

```bash
python3 pixel_map.py --svg pixel_map_check.svg
```

Writes `pixels.csv` from the geometry constants at the top of `pixel_map.py`, plus an optional top/side-view check plot. Edit the constants and rerun; don't hand-edit the CSV.

## Browser preview

```bash
python3 preview/server.py                         # open http://localhost:8048
python3 testpattern.py --host 127.0.0.1 parts     # in another terminal
```

The preview stands in for the Dig-Uno. It listens for DDP on udp/4048 and draws the frames on a 3D model of the sculpture built from `pixels.csv`. Anything that speaks DDP can target it, including the Pi runner pointed at this machine's IP. It uses only the Python standard library, and the page draws on a plain canvas, so it works offline.

- Drag to rotate, scroll to zoom, double-click to reset. Front / 3/4 / Top views, plus auto-spin.
- Hover a bulb to see its index, output/light, strand, base pair, part, slot, and current RGB.
- The status chip shows live/idle, fps, the sender's address, and DDP sequence gaps. After 2.5 s without packets the frame dims: that's when the real sculpture would fall back to its WLED effect.
- Options: `--ddp-port`, `--http-port`, `--bind 127.0.0.1` (local only; the default 0.0.0.0 accepts DDP from the LAN). Only one program can hold udp/4048 at a time.

## WLED settings checklist

- **Config → LED Preferences:** 2 outputs. GPIO16 start 0 length 100; GPIO3 start 100 length 100. Brightness limiter on, ~10 A.
- **Config → Sync Interfaces:** "Receive UDP realtime" on. Realtime timeout ~2.5 s.
- **Config → Time & Macros:** location Madison, WI (43.07, -89.40), timezone America/Chicago; sunset-on / late-off fallback timers.

## Bench check (`testpattern.py`)

Every pattern streams until Ctrl-C, and WLED goes back to its own effect ~2.5 s later. `--scale` (default 0.5) scales all colors; `--host` overrides the config.

1. **Reachability:** `python3 testpattern.py info`. LED count should be 200.
2. **Color order:** `python3 testpattern.py rgb`. It prints RED / GREEN / BLUE / WHITE as it sends them. If the sculpture shows something else, fix Color Order in LED Preferences.
3. **Which strand is on which output:** `python3 testpattern.py outputs`. Output 1 is red, output 2 green. If the red strand isn't the 3'→5' side, set `OUTPUT1_STRAND = "5to3"` in `pixel_map.py` and rerun it.
4. **Pixel map:**
   - `python3 testpattern.py parts`: stems orange, rings blue, rods white.
   - `python3 testpattern.py basepairs`: red at the bottom to violet at the top.
   - `python3 testpattern.py step --output 1`: one pixel at a time, with its labels printed. Enter = next, `b` = back, a number jumps to that index, `q` quits.
   - `python3 testpattern.py chase --speed 4`: the same walk, automated.
5. **Brightness / power:** `python3 testpattern.py ramp --scale 1`. Also try it after `python3 testpattern.py power on --bri 60`, to see whether WLED's master brightness applies to DDP.

Other commands: `solid R G B`, `blank`, `power on|off [--bri N]`.
