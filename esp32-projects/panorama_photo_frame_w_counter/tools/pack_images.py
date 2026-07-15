#!/usr/bin/env python3

"""
Pack one or more 4-bit indexed grayscale PNGs (as produced by
python-projects/grayscale_image_conversion/prepare_image.py) into the
nibble-packed byte layout Seeed_GFX expects for a GRAY_LEVEL16 EPaper sprite,
and write them out as raw .bin files plus a manifest for LittleFS -- see
data/images/ and `pio run -t uploadfs`.

This is a LittleFS-oriented sibling of
../../test_bw_image_eink/tools/convert_image.py, which instead compiles
images into flash as PROGMEM C arrays. That approach hits a flash-budget wall
at 2 full-canvas images (~89.5% of the app partition); storing images in
LittleFS instead keeps them off the app partition entirely and matches the
file-based read this project will use again once a physical SD card is added.

Packing format (same as convert_image.py, confirmed against the vendored
Seeed_GFX source): each byte holds two pixels, high nibble = first (even)
pixel, low nibble = second (odd) pixel. A 4bpp EPaper sprite stores the
palette index directly as the gray level (0 = black .. 15 = white), matching
prepare_image.py's palette, so no color-map translation is needed here.

All input images must be exactly PANEL_WIDTH x PANEL_HEIGHT (the EE03 panel's
fixed native resolution) -- this is normally already true if they came from
prepare_image.py's defaults.

Usage:
    python3 tools/pack_images.py ~/Pictures/test_1.png ~/Pictures/test_2.png
    python3 tools/pack_images.py --output-dir data/images a.png b.png c.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

PANEL_WIDTH = 1872
PANEL_HEIGHT = 1404


def pack_image(image: Image.Image) -> bytes:
    if image.mode != "P":
        raise ValueError(
            f"Expected a 4-bit palette ('P' mode) image, got mode {image.mode!r}. "
            "Run it through python-projects/grayscale_image_conversion/prepare_image.py "
            "first (--bit-depth 4)."
        )

    indices = list(image.getdata())

    if any(index > 15 for index in indices):
        raise ValueError(
            "Palette indices must fit in 4 bits (0-15) -- "
            "this doesn't look like a 4-bit grayscale image."
        )

    if len(indices) % 2 != 0:
        indices.append(0)

    packed = bytearray()
    for high, low in zip(indices[0::2], indices[1::2]):
        packed.append(((high & 0x0F) << 4) | (low & 0x0F))

    return bytes(packed)


def bin_name(index: int) -> str:
    return f"img_{index:02d}.bin"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs", type=Path, nargs="+", help="Source 4-bit indexed PNGs, in display order."
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("data/images"),
        help="Output directory for packed .bin files + manifest.txt (default: data/images).",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest_lines = []
    total_bytes = 0

    for index, input_path in enumerate(args.inputs):
        resolved = input_path.expanduser()

        with Image.open(resolved) as image:
            if image.size != (PANEL_WIDTH, PANEL_HEIGHT):
                raise ValueError(
                    f"{resolved} is {image.size}, but the EE03 panel is "
                    f"{PANEL_WIDTH}x{PANEL_HEIGHT} -- run it through prepare_image.py "
                    "at its default --width/--height first."
                )

            packed = pack_image(image)

        out_name = bin_name(index)
        (args.output_dir / out_name).write_bytes(packed)
        manifest_lines.append(f"{out_name}\t{resolved.name}")
        total_bytes += len(packed)

        print(f"Wrote {args.output_dir / out_name} ({len(packed)} bytes) <- {resolved.name}")

    manifest_path = args.output_dir / "manifest.txt"
    manifest_path.write_text("\n".join(manifest_lines) + "\n")

    print(
        f"Wrote {manifest_path} ({len(args.inputs)} image(s), "
        f"{total_bytes} bytes packed total). Next: pio run -t uploadfs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
