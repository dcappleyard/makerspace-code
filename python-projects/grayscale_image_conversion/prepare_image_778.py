#!/usr/bin/env python3

"""
Variant of prepare_image.py that fills a 1872 x 778 strip (instead of the
default ~6:17, 1872 x 661 letterboxed strip), vertically centered on the
1872 x 1404 panel canvas.

Fit mode is *fill/cover* (not letterbox): the photo is scaled to cover the whole
1872 x 778 strip with no white bars, then the overflow is center-cropped. So a
wide panorama fills the full 778 height and loses its left/right edges (trimmed
equally from both sides); a tall image loses top/bottom. This is the key
difference from prepare_image.py, whose scale-to-width letterbox would leave a
wide panorama shorter than 778 with white padding.

Everything else is identical to prepare_image.py -- same interactive metadata
prompts, .xml sidecar, nibble-packed .bin, and preview PNG -- this script just
reuses that pipeline (`run()`) with a different strip height and fill mode, so
any change to the imaging/packing/metadata logic lives in one place.

IMPORTANT -- keep the firmware in sync: if you display these on the frame, set
REGION_HEIGHT / REGION_TOP in
esp32-projects/panorama_photo_frame_w_counter/src/main.cpp to 778 / 313 (the
values below), otherwise the header/caption overlays won't line up with the
taller photo. (The default frame firmware expects the 661 strip.)

Usage:
    python3 prepare_image_778.py ~/Pictures/harbor.tif --output-dir ./sd_pictures
    (then answer the metadata prompts)
"""

from prepare_image import DEFAULT_HEIGHT, run

REGION_HEIGHT = 778
REGION_TOP = (DEFAULT_HEIGHT - REGION_HEIGHT) // 2  # 313


if __name__ == "__main__":
    raise SystemExit(
        run(region_height=REGION_HEIGHT, region_top=REGION_TOP, fill=True)
    )
