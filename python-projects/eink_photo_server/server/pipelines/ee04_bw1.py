"""Seeed EE04 + 4.26" monochrome (800x480, black/white) pipeline.

The photo is cover-cropped (around its focal point) or letterboxed to the full
panel, tuned, Floyd-Steinberg dithered to pure black/white and bit-packed into
the exact buffer layout of Seeed_GFX's 1-bit EPaper sprite, so the firmware
(esp32-projects/xiao_s3_ee04_pullframe) copies it straight into the sprite and
refreshes:
  row-major, width/8 bytes per row, MSB = leftmost pixel, bit 1 = white.
800x480 -> 48,000 bytes.

devices.yaml: width/height are the panel as mounted (800x480 landscape, or
480x800 with output_rotation 90/270 for portrait). Captions: overlay_bottom
(there's no white band, so below_strip falls back to it).

Options (devices.yaml `options:`):
  fit   "cover" (default: fill the panel, crop around the focal point) or
        "letterbox" (whole photo, white bars)
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from ..dashboards.draw import BLACK, WHITE, Fill, Theme
from . import register
from .base import Pipeline, apply_tuning, cover_crop, draw_battery, draw_caption, resize_lanczos, rotate_cw


def pack_bits(white: np.ndarray) -> bytes:
    """(H x W) bool, True = white -> MSB-first packed rows."""
    return np.packbits(white.astype(np.uint8), axis=1, bitorder="big").tobytes()


def unpack_bits(data: bytes, w: int, h: int) -> Image.Image:
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")[: w * h]
    return Image.fromarray((bits.reshape(h, w) * 255).astype(np.uint8), "L")


@register
class EE04BW1(Pipeline):
    name = "ee04_bw1"
    version = "1"
    file_suffix = "_B.bin"
    content_type = "application/octet-stream"
    color = False
    # A little extra contrast helps photos survive a 1-bit dither.
    default_params = {"contrast": 1.15, "brightness": 1.0, "gamma": 1.0,
                      "lift": 0.0, "lift_threshold": 90.0}

    def _white(self, img, device, params, focal) -> np.ndarray:
        """(H x W) bool, True = white, in panel orientation."""
        w, h = device.width, device.height
        if device.options.get("fit", "cover") == "letterbox":
            scale = min(w / img.width, h / img.height)
            sw, sh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
            photo = resize_lanczos(img, sw, sh)
            canvas = Image.new("RGB", (w, h), "white")
            canvas.paste(apply_tuning(photo.convert("RGB"), params), ((w - sw) // 2, (h - sh) // 2))
        else:
            canvas = apply_tuning(resize_lanczos(cover_crop(img, w, h, focal), w, h).convert("RGB"), params)
        if params.get("caption"):
            canvas = draw_caption(canvas, params["caption"], params["caption_layout"], params["caption_size"])
        if params.get("battery_overlay") is not None:
            canvas = draw_battery(canvas, params["battery_overlay"], False)
        canvas = rotate_cw(canvas.convert("L"), device.output_rotation)
        # Pillow's "1" conversion is Floyd-Steinberg by default.
        bw = canvas.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        return np.asarray(bw, dtype=bool)

    # Dashboards: pure black/white, with patterns standing in for greys. Text is
    # drawn without antialiasing so glyph edges stay crisp at 1 bit.
    THEME = Theme(
        name="bw", antialias=False, min_font=11,
        fills={
            "clear": Fill(),
            "partly": Fill(pattern="dots"),
            "cloudy": Fill(pattern="stipple"),
            "fog": Fill(pattern="fog"),
            "wind": Fill(pattern="hlines"),
            "rain": Fill(pattern="hatch"),
            "mix": Fill(pattern="crosshatch"),
            "snow": Fill(border_w=3),
            "storm": Fill(bg=BLACK, icon=WHITE, halo=None),
            "hot": Fill(pattern="vlines"),
            "cold": Fill(border_w=3),
        })

    def dashboard_theme(self, device):
        return self.THEME

    def _bw(self, img) -> np.ndarray:
        """Rendered RGB -> (H x W) bool, True = white (threshold, no dither)."""
        return np.asarray(img.convert("L"), dtype=np.uint8) >= 128

    def encode_rendered(self, img, device) -> bytes:
        canvas = Image.new("L", (device.width, device.height), 255)
        canvas.paste(img.convert("L"), (0, 0))
        white = self._bw(rotate_cw(canvas, device.output_rotation))
        data = pack_bits(white)
        if len(data) != device.width * device.height // 8:
            raise ValueError(f"packed image is {len(data)} bytes, expected {device.width * device.height // 8}")
        return data

    def rendered_preview(self, img, device):
        return Image.fromarray((self._bw(img) * 255).astype(np.uint8), "L").convert("RGB")

    def prepare(self, img, device, params, focal=(0.5, 0.5)) -> bytes:
        white = self._white(img, device, params, focal)
        h, w = white.shape
        if w % 8:
            raise ValueError(f"panel width {w} isn't a multiple of 8")
        data = pack_bits(white)
        if len(data) != device.width * device.height // 8:
            raise ValueError(f"packed image is {len(data)} bytes, expected {device.width * device.height // 8}")
        return data

    def decode(self, data, device):
        w, h = (device.height, device.width) if device.output_rotation in (90, 270) else (device.width, device.height)
        return unpack_bits(data, w, h)

    def preview(self, img, device, params, focal=(0.5, 0.5)):
        white = self._white(img, device, params, focal)
        out = Image.fromarray((white * 255).astype(np.uint8), "L")
        return rotate_cw(out, (360 - device.output_rotation) % 360).convert("RGB")
