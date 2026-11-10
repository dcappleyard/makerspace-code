#!/usr/bin/env python3
"""Bench/test patterns for the sculpture, streamed to WLED over DDP.

Patterns stream until Ctrl-C; WLED returns to its own effect ~2.5 s later.

  info                 controller info (LED count, version, realtime/live state)
  power on|off         WLED on/off via the JSON API (--bri 0-255 with "on")
  rgb                  cycle solid red / green / blue / white to check color order
  solid R G B          one solid color
  outputs              output 1 red, output 2 green -> which strand is on which output
  parts                stems orange, rings blue, rods white (checks the pixel map labels)
  basepairs            one hue per base pair, red at the bottom -> violet at the top
  chase                one pixel walks through the string, printing its labels
  step                 light one pixel at a time; Enter = next, b = back, <n> = jump, q = quit
  ramp                 white brightness ramp up and down (power / limiter check)
  blank                all pixels black (until Ctrl-C)

Host comes from config.yaml (copy config.example.yaml) or --host.
"""
import argparse
import colorsys
import sys
import time
from pathlib import Path

import pixel_map
from wled.api import WLED
from wled.ddp import DDPSender, Streamer

HERE = Path(__file__).resolve().parent

PART_COLORS = {"stem": (255, 120, 0), "ring": (0, 60, 255), "rod": (255, 255, 255)}
OUTPUT_COLORS = {1: (255, 0, 0), 2: (0, 255, 0)}


def load_config(path):
    if not path.exists():
        return {}
    import yaml
    return yaml.safe_load(path.read_text()) or {}


def describe(p):
    return (f"pixel {p['index']:3d} | output {p['output']} light {p['light']:3d} | "
            f"{p['strand']} bp {p['base_pair']} {p['part']} slot {p['slot']}")


def hue(h):
    r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


class Frame:
    """Builds RGB byte frames with a global brightness scale."""

    def __init__(self, n, scale):
        self.n, self.scale = n, scale

    def solid(self, rgb):
        return self.colors([rgb] * self.n)

    def colors(self, rgbs):
        s = self.scale
        return bytes(min(255, int(c * s)) for rgb in rgbs for c in rgb)


def run(streamer):
    streamer.start()
    try:
        while streamer.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        streamer.stop()
    if streamer.error:
        raise streamer.error


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", choices=["info", "power", "rgb", "solid", "outputs", "parts",
                                        "basepairs", "chase", "step", "ramp", "blank"])
    ap.add_argument("args", nargs="*", help="pattern arguments (power: on|off; solid: R G B)")
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--host", help="WLED host or IP (overrides config)")
    ap.add_argument("--pixels", default=str(HERE / "pixels.csv"))
    ap.add_argument("--fps", type=float, help="stream rate (default from config, else 40)")
    ap.add_argument("--scale", type=float, default=0.5,
                    help="brightness scale applied to every pattern, 0-1 (default 0.5)")
    ap.add_argument("--bri", type=int, help="with 'power on': WLED master brightness 0-255")
    ap.add_argument("--hold", type=float, default=3.0, help="rgb: seconds per color")
    ap.add_argument("--speed", type=float, default=4.0, help="chase: pixels per second")
    ap.add_argument("--start", type=int, default=0, help="chase/step: first pixel index")
    ap.add_argument("--output", type=int, choices=[1, 2], help="chase/step: only this output")
    ap.add_argument("--period", type=float, default=10.0, help="ramp: seconds per up+down cycle")
    a = ap.parse_args()

    cfg = load_config(Path(a.config)).get("wled", {})
    host = a.host or cfg.get("host")
    if not host:
        sys.exit("No WLED host: set wled.host in config.yaml (see config.example.yaml) or pass --host")
    fps = a.fps or cfg.get("fps", 40)

    if a.pattern == "info":
        info = WLED(host).info()
        leds = info.get("leds", {})
        print(f"{info.get('name')}  WLED {info.get('ver')}  ip {info.get('ip')}")
        print(f"LED count: {leds.get('count')}  (pixel map expects 200)")
        print(f"power limiter: {leds.get('maxpwr')} mA  est. current: {leds.get('pwr')} mA")
        print(f"realtime active: {info.get('live')}  mode: {info.get('lm')}  source: {info.get('lip')}")
        st = WLED(host).state()
        print(f"state: on={st.get('on')} bri={st.get('bri')} preset={st.get('ps')} "
              f"live override (lor)={st.get('lor')}")
        return

    if a.pattern == "power":
        if a.args not in (["on"], ["off"]):
            sys.exit("usage: testpattern.py power on|off [--bri N]")
        w = WLED(host)
        w.on(a.bri) if a.args == ["on"] else w.off()
        st = w.state()          # POST replies {"success": true}; read back the real state
        print(f"on={st.get('on')} bri={st.get('bri')}")
        return

    pixels = pixel_map.load(a.pixels)
    n = len(pixels)
    F = Frame(n, max(0.0, min(1.0, a.scale)))
    sender = DDPSender(host, cfg.get("ddp_port", 4048))
    print(f"streaming '{a.pattern}' to {host} ({sender.addr[0]}) at {fps:g} fps, "
          f"scale {F.scale:g}; Ctrl-C to stop")

    if a.pattern == "solid":
        try:
            rgb = tuple(int(v) for v in a.args)
            assert len(rgb) == 3
        except (ValueError, AssertionError):
            sys.exit("usage: testpattern.py solid R G B   (0-255 each)")
        frame = F.solid(rgb)
        run(Streamer(sender, lambda: frame, fps))

    elif a.pattern == "blank":
        frame = F.solid((0, 0, 0))
        run(Streamer(sender, lambda: frame, fps))

    elif a.pattern == "rgb":
        seq = [("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)),
               ("BLUE", (0, 0, 255)), ("WHITE", (255, 255, 255))]
        frames = [(name, F.solid(c)) for name, c in seq]
        state = {"i": -1}
        t0 = time.monotonic()

        def src():
            i = int((time.monotonic() - t0) / a.hold) % len(frames)
            if i != state["i"]:
                state["i"] = i
                print(f"  sending {frames[i][0]}")
            return frames[i][1]

        print("If what you see doesn't match, change Color Order in WLED -> LED Preferences.")
        run(Streamer(sender, src, fps))

    elif a.pattern == "outputs":
        frame = F.colors([OUTPUT_COLORS[p["output"]] for p in pixels])
        for o in (1, 2):
            strand = next(p["strand"] for p in pixels if p["output"] == o)
            name = "RED" if o == 1 else "GREEN"
            print(f"  output {o} = {name}  (pixel map currently labels it {strand})")
        print("If the labels are backwards, flip OUTPUT1_STRAND in pixel_map.py and rerun it.")
        run(Streamer(sender, lambda: frame, fps))

    elif a.pattern == "parts":
        frame = F.colors([PART_COLORS[p["part"]] for p in pixels])
        print("  stems ORANGE, rings BLUE, rods WHITE")
        run(Streamer(sender, lambda: frame, fps))

    elif a.pattern == "basepairs":
        frame = F.colors([hue(0.8 * p["base_pair"] / 9) for p in pixels])
        print("  bottom base pair RED ... top base pair VIOLET")
        run(Streamer(sender, lambda: frame, fps))

    elif a.pattern in ("chase", "step"):
        order = [p for p in pixels if a.output in (None, p["output"])]
        pos = next((i for i, p in enumerate(order) if p["index"] >= a.start), 0)
        state = {"pos": pos, "shown": None}
        frames = {}

        def frame_for(i):
            if i not in frames:
                rgbs = [(0, 0, 0)] * n
                rgbs[order[i]["index"]] = (255, 255, 255)
                frames[i] = F.colors(rgbs)
            return frames[i]

        if a.pattern == "chase":
            t0 = time.monotonic()

            def src():
                i = (state["pos"] + int((time.monotonic() - t0) * a.speed)) % len(order)
                if i != state["shown"]:
                    state["shown"] = i
                    print("  " + describe(order[i]))
                return frame_for(i)

            run(Streamer(sender, src, fps))
        else:
            st = Streamer(sender, lambda: frame_for(state["pos"]), fps)
            st.start()
            try:
                while st.is_alive():
                    print("  " + describe(order[state["pos"]]))
                    cmd = input("  [Enter]=next  b=back  <index>=jump  q=quit > ").strip().lower()
                    if cmd == "q":
                        break
                    elif cmd == "b":
                        state["pos"] = (state["pos"] - 1) % len(order)
                    elif cmd.isdigit():
                        j = next((i for i, p in enumerate(order) if p["index"] == int(cmd)), None)
                        if j is None:
                            print(f"  no pixel {cmd} in this selection")
                        else:
                            state["pos"] = j
                    else:
                        state["pos"] = (state["pos"] + 1) % len(order)
            except (KeyboardInterrupt, EOFError):
                pass
            finally:
                st.stop()
            if st.error:
                raise st.error

    elif a.pattern == "ramp":
        t0 = time.monotonic()

        def src():
            ph = ((time.monotonic() - t0) / a.period) % 1.0
            v = int(255 * (1 - abs(2 * ph - 1)))      # triangle 0 -> 255 -> 0
            return F.solid((v, v, v))

        print(f"  white ramp, {a.period:g} s per cycle, peak = 255 x scale {F.scale:g}")
        run(Streamer(sender, src, fps))

    sender.close()
    print("stopped; WLED reverts to its own effect in ~2.5 s")


if __name__ == "__main__":
    main()
