#!/usr/bin/env python3
"""Generate pixels.csv for the double-helix sculpture.

Geometry and wiring are described in PROJECT.md ("Sculpture geometry").
Edit the constants below and rerun to refine the map.

    python3 pixel_map.py                    # writes pixels.csv
    python3 pixel_map.py --svg map.svg      # also writes a top/side-view check plot
    python3 pixel_map.py --swap-strands     # output 1 <-> output 2 strand labels

Stdlib only.
"""
import argparse
import csv
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- Which strand is on which Dig-Uno output (unknown — flip when confirmed) ---
OUTPUT1_STRAND = "3to5"          # the other strand ("5to3") is on output 2

# --- Geometry, inches ---
BASE_PAIRS = 10
RISE = 4.5                        # vertical spacing between base pairs
TWIST_DEG = 40.0                  # right-handed: counterclockwise from above going up
THETA0_DEG = 0.0                  # direction of bottom base pair's output-1 lollipop (+x)
Z0 = 14.0                         # bottom base pair height above ground
STEM_LEN = 7.0
RING_DIAM = 7.0
STEM_FRACS = (1 / 3, 2 / 3)       # stem light positions along the stem, rod -> ring
STEM_SIDE_OFFSET = 0.4            # outbound/return legs drawn this far either side of the stem
ROD_DROP = 2.25                   # rod light distance below its lollipop
ROD_RADIUS = 0.5                  # rod lights sit on the rod surface (nominal)

LIGHTS_PER_LOLLIPOP = 10          # 4 stem + 5 ring + 1 rod
PIXELS_PER_OUTPUT = BASE_PAIRS * LIGHTS_PER_LOLLIPOP

FIELDS = ["index", "x", "y", "z", "output", "light", "strand",
          "base_pair", "part", "slot"]


def lollipop_lights(theta_deg, z):
    """The 10 lights of one lollipop in top-down travel order (light numbers
    decreasing): 2 stem out, 5 ring clockwise from above, 2 stem back, 1 rod.
    Returns (x, y, z, part, slot) tuples."""
    th = math.radians(theta_deg)
    u = (math.cos(th), math.sin(th))      # outward along the stem
    v = (-math.sin(th), math.cos(th))     # 90 deg counterclockwise of u (from above)

    def at(r, side):
        return (r * u[0] + side * v[0], r * u[1] + side * v[1])

    out = []
    # Clockwise travel around the lollipop outline: outbound leg on the +v side.
    for slot, f in enumerate(STEM_FRACS):
        out.append((*at(f * STEM_LEN, +STEM_SIDE_OFFSET), z, "stem", slot))

    rc = STEM_LEN + RING_DIAM / 2
    rr = RING_DIAM / 2
    # Junction is at ring angle 180 deg; clockwise from above = decreasing angle.
    # Five evenly spaced, symmetric about the junction -> slot 2 is the far point.
    for k in range(5):
        a = math.radians(180 - 36 - 72 * k)
        x = rc * u[0] + rr * (math.cos(a) * u[0] + math.sin(a) * v[0])
        y = rc * u[1] + rr * (math.cos(a) * u[1] + math.sin(a) * v[1])
        out.append((x, y, z, "ring", k))

    for slot, f in zip((2, 3), reversed(STEM_FRACS)):
        out.append((*at(f * STEM_LEN, -STEM_SIDE_OFFSET), z, "stem", slot))

    # Rod light: below the lollipop, on the rod between this stem and the one below.
    ra = math.radians(theta_deg - TWIST_DEG / 2)
    out.append((ROD_RADIUS * math.cos(ra), ROD_RADIUS * math.sin(ra),
                z - ROD_DROP, "rod", 0))
    return out


def build(output1_strand=OUTPUT1_STRAND):
    other = "5to3" if output1_strand == "3to5" else "3to5"
    rows = []
    for output, strand, phase in ((1, output1_strand, 0.0), (2, other, 180.0)):
        for bp in range(BASE_PAIRS):
            theta = THETA0_DEG + phase + TWIST_DEG * bp
            z = Z0 + RISE * bp
            for o, (x, y, zz, part, slot) in enumerate(lollipop_lights(theta, z), 1):
                light = LIGHTS_PER_LOLLIPOP * bp + LIGHTS_PER_LOLLIPOP + 1 - o
                rows.append({
                    "index": (output - 1) * PIXELS_PER_OUTPUT + light - 1,
                    "x": round(x, 3), "y": round(y, 3), "z": round(zz, 3),
                    "output": output, "light": light, "strand": strand,
                    "base_pair": bp, "part": part, "slot": slot,
                })
    rows.sort(key=lambda r: r["index"])
    assert [r["index"] for r in rows] == list(range(2 * PIXELS_PER_OUTPUT))
    return rows


def load(path=HERE / "pixels.csv"):
    """Read pixels.csv back as a list of dicts (numbers typed), in index order."""
    num = {"index": int, "x": float, "y": float, "z": float, "output": int,
           "light": int, "base_pair": int, "slot": int}
    with open(path, newline="") as f:
        rows = [{k: num.get(k, str)(v) for k, v in r.items()} for r in csv.DictReader(f)]
    rows.sort(key=lambda r: r["index"])
    return rows


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- SVG check plot

PART_COLOR = {"stem": "#e8890c", "ring": "#2a7de1", "rod": "#888888"}
STRAND_LINE = {1: "#c0392b", 2: "#16a085"}


def write_svg(rows, path):
    s = 9.0      # px per inch
    pad = 40
    zmax = max(r["z"] for r in rows) + 4
    R = STEM_LEN + RING_DIAM + 1
    pw = 2 * R * s                  # panel width
    ph_top = 2 * R * s
    ph_side = zmax * s
    W = int(3 * pw + 4 * pad)
    H = int(max(ph_top, ph_side) + 2 * pad + 60)

    views = [
        ("Top view (from above, +x right, +y up)", lambda r: (r["x"], r["y"]), ph_top, -R),
        ("Side view (looking along +y: x horizontal)", lambda r: (r["x"], r["z"]), ph_side, 0),
        ("Side view (looking along -x: y horizontal)", lambda r: (r["y"], r["z"]), ph_side, 0),
    ]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="11">',
           f'<rect width="{W}" height="{H}" fill="white"/>']
    for i, (title, proj, ph, vmin) in enumerate(views):
        ox = pad + i * (pw + pad)
        oy = pad + 20

        def P(r):
            h, v = proj(r)
            return ox + (h + R) * s, oy + ph - (v - vmin) * s

        out.append(f'<text x="{ox}" y="{pad}" font-size="13" font-weight="bold">{title}</text>')
        out.append(f'<rect x="{ox}" y="{oy}" width="{pw}" height="{ph}" fill="none" stroke="#ddd"/>')
        if i == 0:
            cx, cy = ox + R * s, oy + R * s
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{ROD_RADIUS * s + 2}" fill="#333"/>')
        else:
            x0 = ox + R * s
            out.append(f'<line x1="{x0}" y1="{oy}" x2="{x0}" y2="{oy + ph}" stroke="#333" stroke-width="3"/>')
            gy = oy + ph
            out.append(f'<text x="{ox + 4}" y="{gy - 4}" fill="#999">ground (z=0)</text>')
        # wire path per output, in data order
        for output in (1, 2):
            pts = [P(r) for r in rows if r["output"] == output]
            d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            out.append(f'<polyline points="{d}" fill="none" stroke="{STRAND_LINE[output]}" '
                       f'stroke-width="0.8" stroke-opacity="0.5"/>')
        for r in sorted(rows, key=lambda r: r["z"]):
            x, y = P(r)
            op = 0.35 + 0.65 * r["base_pair"] / (BASE_PAIRS - 1)
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{PART_COLOR[r["part"]]}" '
                       f'fill-opacity="{op:.2f}" stroke="{STRAND_LINE[r["output"]]}" stroke-width="1"/>')
        # label the top lollipop of each output and light 1
        if i == 0:
            for r in rows:
                if r["base_pair"] == BASE_PAIRS - 1 and r["part"] != "rod":
                    x, y = P(r)
                    out.append(f'<text x="{x + 4:.1f}" y="{y - 4:.1f}" fill="{STRAND_LINE[r["output"]]}">{r["light"]}</text>')
        else:
            for r in rows:
                if r["light"] in (1, 100) or (r["part"] == "rod" and r["output"] == 1):
                    x, y = P(r)
                    out.append(f'<text x="{x + 5:.1f}" y="{y + 4:.1f}" fill="{STRAND_LINE[r["output"]]}">'
                               f'{r["light"]}</text>')

    ly = H - 34
    lx = pad
    for part, c in PART_COLOR.items():
        out.append(f'<circle cx="{lx}" cy="{ly - 4}" r="4" fill="{c}"/><text x="{lx + 8}" y="{ly}">{part}</text>')
        lx += 70
    for o, c in STRAND_LINE.items():
        strand = rows[(o - 1) * PIXELS_PER_OUTPUT]["strand"]
        out.append(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 18}" y2="{ly - 4}" stroke="{c}" stroke-width="2"/>'
                   f'<text x="{lx + 24}" y="{ly}">output {o} ({strand}) wire path</text>')
        lx += 230
    out.append(f'<text x="{pad}" y="{ly + 18}" fill="#666">Labels = light number on its string '
               f'(1 = pixel 0). Fainter = lower base pair.</text>')
    out.append("</svg>")
    Path(path).write_text("\n".join(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=str(HERE / "pixels.csv"))
    ap.add_argument("--svg", help="also write a top/side-view SVG check plot here")
    ap.add_argument("--swap-strands", action="store_true",
                    help="put the other strand on output 1 (overrides OUTPUT1_STRAND)")
    args = ap.parse_args()

    s1 = OUTPUT1_STRAND
    if args.swap_strands:
        s1 = "5to3" if s1 == "3to5" else "3to5"
    rows = build(s1)
    write_csv(rows, args.out)
    print(f"wrote {len(rows)} pixels to {args.out} (output 1 = {s1})")
    if args.svg:
        write_svg(rows, args.svg)
        print(f"wrote {args.svg}")


if __name__ == "__main__":
    main()
