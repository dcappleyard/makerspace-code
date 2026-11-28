#!/usr/bin/env python3
"""Generate tree_pixels.csv for the tree strand, an optional add-on fixture.

The tree strand is a hand install, so it changes from year to year. It runs
from the base of the trunk (light 1) up to the split, then round a rounded
triangle: up the left side, across the top, and down the right side, with the
last light back at the split. Seen from the street the triangle stands on
its point (the split).

Each year: find the split and the two top corners with
    python3 testpattern.py --tree step
measure roughly where they are (inches; x from the trunk, + to the right as
seen from the street, z above the ground), set TREE_ANCHORS and rerun:

    python3 tree_map.py                     # writes tree_pixels.csv
    python3 tree_map.py --svg tree.svg      # also a front-view check plot

Coordinates are in the sculpture's world frame (pixels.csv): inches, z up
from the ground, the sculpture's rod at x = y = 0. The tree stands TREE_X
inches to its side. Stdlib only.
"""
import argparse
import csv
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

N_LIGHTS = 100
TREE_X = -36.0          # trunk position relative to the sculpture's rod (3 ft to its left)
TREE_Y = 0.0

# (light, x from the trunk, z above ground), measured 2026-11-27 (rough, by eye);
# lights between two anchors are spaced evenly along the path between them.
BASE, SPLIT, LEFT_CORNER, RIGHT_CORNER = 1, 16, 55, 71
TREE_ANCHORS = [
    (BASE, 0.0, 2.0),
    (SPLIT, 0.0, 30.0),                # split ~2.5 ft up
    (LEFT_CORNER, -36.0, 84.0),        # top left: ~3 ft left of the split, ~7 ft up
    (RIGHT_CORNER, 12.0, 84.0),        # top right: ~1 ft right of the split
    (N_LIGHTS, 2.0, 32.0),             # back at the split
]
CORNER_ROUND = 9.0      # inches: the two top corners curve this far either side of the anchor

FIELDS = ["index", "x", "y", "z", "light", "part", "s", "pos"]


def _part(light):
    if light < SPLIT:
        return "trunk"
    if light < LEFT_CORNER:
        return "left"
    if light < RIGHT_CORNER:
        return "top"
    return "right"


def _path():
    """A dense polyline through the anchors, with the two top corners rounded
    (quadratic Bezier), and the distance along it of each anchor."""
    pts, at = [], {}
    corners = {LEFT_CORNER, RIGHT_CORNER}
    for i, (light, x, z) in enumerate(TREE_ANCHORS):
        if light in corners and 0 < i < len(TREE_ANCHORS) - 1:
            (_, xp, zp), (_, xn, zn) = TREE_ANCHORS[i - 1][:3], TREE_ANCHORS[i + 1][:3]
            din, dout = math.hypot(x - xp, z - zp), math.hypot(xn - x, zn - z)
            r = min(CORNER_ROUND, din / 2, dout / 2)
            pin = (x - (x - xp) * r / din, z - (z - zp) * r / din)
            pout = (x + (xn - x) * r / dout, z + (zn - z) * r / dout)
            for k in range(21):
                tau = k / 20
                a, b, c = (1 - tau) ** 2, 2 * (1 - tau) * tau, tau ** 2
                pts.append((a * pin[0] + b * x + c * pout[0], a * pin[1] + b * z + c * pout[1]))
                if k == 10:
                    at[light] = len(pts) - 1
        else:
            pts.append((x, z))
            at[light] = len(pts) - 1
    s = [0.0]
    for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
        s.append(s[-1] + math.hypot(x1 - x0, z1 - z0))
    return pts, s, {light: s[k] for light, k in at.items()}


def _point_at(pts, s, d):
    k = max(0, min(len(s) - 2, next((j for j in range(1, len(s)) if s[j] >= d), len(s) - 1) - 1))
    f = 0.0 if s[k + 1] == s[k] else (d - s[k]) / (s[k + 1] - s[k])
    return pts[k][0] + (pts[k + 1][0] - pts[k][0]) * f, pts[k][1] + (pts[k + 1][1] - pts[k][1]) * f


def build():
    pts, s, anchor_s = _path()
    lights = [a[0] for a in TREE_ANCHORS]
    rows = []
    for light in range(1, N_LIGHTS + 1):
        j = max(i for i, l in enumerate(lights) if l <= light)
        if j == len(lights) - 1:
            d = anchor_s[lights[j]]
        else:
            l0, l1 = lights[j], lights[j + 1]
            d = anchor_s[l0] + (anchor_s[l1] - anchor_s[l0]) * (light - l0) / (l1 - l0)
        x, z = _point_at(pts, s, d)
        rows.append({"index": light - 1, "x": round(TREE_X + x, 2), "y": TREE_Y, "z": round(z, 2),
                     "light": light, "part": _part(light), "s": round(d, 2), "pos": 0.0})
    total = rows[-1]["s"]
    for r in rows:
        r["pos"] = round(r["s"] / total, 4)
    return rows


def load(path=HERE / "tree_pixels.csv"):
    """Read tree_pixels.csv back as a list of dicts (numbers typed), in index order."""
    num = {"index": int, "x": float, "y": float, "z": float, "light": int, "s": float, "pos": float}
    with open(path, newline="") as f:
        rows = [{k: num.get(k, str)(v) for k, v in r.items()} for r in csv.DictReader(f)]
    rows.sort(key=lambda r: r["index"])
    return rows


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


PART_COLOR = {"trunk": "#8a5a2b", "left": "#2a7de1", "top": "#c0392b", "right": "#e8890c"}


def write_svg(rows, path):
    s, pad = 5.0, 30
    xs, zs = [r["x"] for r in rows], [r["z"] for r in rows]
    x0, z1 = min(xs), max(zs)
    w = (max(xs) - x0) * s + 2 * pad
    h = z1 * s + 2 * pad
    P = lambda r: (pad + (r["x"] - x0) * s, pad + (z1 - r["z"]) * s)   # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
           f'font-family="sans-serif" font-size="9">',
           f'<rect width="100%" height="100%" fill="white"/>',
           '<polyline fill="none" stroke="#bbb" points="'
           + " ".join(f"{P(r)[0]:.1f},{P(r)[1]:.1f}" for r in rows) + '"/>']
    for r in rows:
        x, y = P(r)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{PART_COLOR[r["part"]]}"/>')
        if r["light"] in (1, N_LIGHTS) or r["light"] % 5 == 0 or r["light"] in (SPLIT, LEFT_CORNER, RIGHT_CORNER):
            out.append(f'<text x="{x + 4:.1f}" y="{y - 3:.1f}">{r["light"]}</text>')
    out.append("</svg>")
    Path(path).write_text("\n".join(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=str(HERE / "tree_pixels.csv"))
    ap.add_argument("--svg", help="also write a front-view SVG check plot here")
    args = ap.parse_args()
    rows = build()
    write_csv(rows, args.out)
    gaps = [b["s"] - a["s"] for a, b in zip(rows, rows[1:])]
    print(f"wrote {len(rows)} lights to {args.out}: strand {rows[-1]['s']:.0f} in, "
          f"spacing {min(gaps):.1f}-{max(gaps):.1f} in")
    if args.svg:
        write_svg(rows, args.svg)
        print(f"wrote {args.svg}")


if __name__ == "__main__":
    main()
