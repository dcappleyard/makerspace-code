#!/usr/bin/env python3
"""Play one show over DDP: to the sculpture, the preview, or both.

    python3 play.py --list
    python3 play.py rainbow_helix                    # to wled.host from config.yaml
    python3 play.py sequence --preview               # to the browser preview on this machine
    python3 play.py twinkle --also 127.0.0.1         # sculpture + preview at once
    python3 play.py ring_spin --preview --reload     # re-import the show when its file changes
    python3 play.py dna_strand -o motion=up -o rod=white   # show options (see the show's OPTIONS)

Streams until Ctrl-C (or --duration); WLED reverts to its own effect ~2.5 s later.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import shows
from layout import Layout
from testpattern import load_config
from wled.ddp import DDPSender, Streamer

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("show", nargs="?", help="show name (a module in shows/)")
    ap.add_argument("--list", action="store_true", help="list shows and exit")
    ap.add_argument("--config", default=os.environ.get("WLED_CONFIG", str(HERE / "config.yaml")),
                    help="config file (default: $WLED_CONFIG, else config.yaml here)")
    ap.add_argument("--host", help="DDP target (default: wled.host from config)")
    ap.add_argument("--preview", action="store_true", help="send to 127.0.0.1 instead of the sculpture")
    ap.add_argument("--also", action="append", default=[], help="additional DDP target (repeatable)")
    ap.add_argument("--fps", type=float)
    ap.add_argument("--scale", type=float, default=1.0, help="brightness scale 0-1 (default 1)")
    ap.add_argument("--duration", type=float, help="stop after this many seconds")
    ap.add_argument("--reload", action="store_true", help="re-import the show file when it changes")
    ap.add_argument("-o", "--option", action="append", default=[], metavar="KEY=VALUE",
                    help="show option (repeatable), e.g. -o colors=red,blue,gold,green")
    a = ap.parse_args()

    if a.list or not a.show:
        for name in shows.available():
            mod = shows.load(name)
            print(f"  {name:16s} {getattr(mod, 'DESCRIPTION', '')}")
            if getattr(mod, "OPTIONS", None):
                print(f"  {'':16s} options: " + ", ".join(f"{k}={v}" for k, v in mod.OPTIONS.items()))
        return

    if a.show not in shows.available():
        sys.exit(f"No show '{a.show}'. Available: {', '.join(shows.available())}")

    cfg = load_config(Path(a.config)).get("wled", {})
    targets = ["127.0.0.1"] if a.preview else [a.host or cfg.get("host")]
    targets += a.also
    if not targets[0]:
        sys.exit("No DDP target: set wled.host in config.yaml, or use --host / --preview")
    fps = a.fps or cfg.get("fps", 40)
    port = cfg.get("ddp_port", 4048)

    try:
        options = dict(shows.parse_option(o) for o in a.option)
        player = shows.Player(a.show, Layout.load(), scale=max(0.0, min(1.0, a.scale)),
                              reload=a.reload, options=options)
    except ValueError as e:
        sys.exit(str(e))
    senders = [DDPSender(h, port) for h in targets]

    class Fanout:
        def send(self, data):
            for s in senders:
                s.send(data)

    shown_error = [None]

    def source():
        f = player.frame()
        if player.error != shown_error[0]:
            shown_error[0] = player.error
            print(f"  show error: {player.error}" if player.error else "  show OK again")
        return f

    st = Streamer(Fanout(), source, fps)
    print(f"playing '{a.show}' to {', '.join(targets)} at {fps:g} fps; Ctrl-C to stop")
    if player.raw_opts:
        print("  options: " + ", ".join(f"{k}={v}" for k, v in player.raw_opts.items()))
    st.start()
    t_end = time.monotonic() + a.duration if a.duration else None
    try:
        while st.is_alive() and (t_end is None or time.monotonic() < t_end):
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        st.stop()
        for s in senders:
            s.close()
    if st.error:
        raise st.error


if __name__ == "__main__":
    main()
