"""Seeed EE03 10.3" (1872x1404, 16-gray) panorama pipeline.

Ported from python-projects/grayscale_image_conversion/prepare_image.py (and its
prepare_image_778.py variant): the photo fills a fixed panorama strip centred on
a white canvas, is dithered to 16 grays, and nibble-packed into the exact
1,314,144-byte .bin the frame pushes straight to the panel (byte = 2 pixels,
high nibble first, 0 = black .. 15 = white). Captions are drawn here, in the
white band below the strip, instead of by the firmware.

Options (devices.yaml `options:`):
  strip_height  661 (default, 6:17) or e.g. 778
  fit           "letterbox" (default: full width, crop/pad the height) or
                "cover" (fill the strip, cropping around the focal point)
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from . import register
from .base import (Pipeline, apply_tuning, cover_crop, draw_battery, draw_caption, resize_lanczos,
                   rotate_cw)

LEVELS = 16
DEFAULT_STRIP_HEIGHT = 661   # round(1872 * 6/17), as in prepare_image.py


def _palette() -> Image.Image:
    pal = Image.new("P", (1, 1))
    grays = [round(i * 255 / (LEVELS - 1)) for i in range(LEVELS)]
    # Pad with white so unused slots can't win as "nearest" for anything darker.
    pal.putpalette([g for v in grays for g in (v, v, v)] + [255, 255, 255] * (256 - LEVELS))
    return pal


def pack_nibbles(indices: np.ndarray) -> bytes:
    flat = indices.reshape(-1).astype(np.uint8)
    if flat.size % 2:
        flat = np.append(flat, np.uint8(0))
    return ((flat[0::2] << 4) | (flat[1::2] & 0x0F)).astype(np.uint8).tobytes()


def unpack_nibbles(data: bytes, w: int, h: int) -> Image.Image:
    """Inverse of pack_nibbles, as an L image (for previews and checks)."""
    b = np.frombuffer(data, dtype=np.uint8)
    idx = np.empty(b.size * 2, dtype=np.uint8)
    idx[0::2], idx[1::2] = b >> 4, b & 0x0F
    return Image.fromarray((idx[: w * h].reshape(h, w) * 17).astype(np.uint8), "L")


@register
class EE03Gray16(Pipeline):
    name = "ee03_gray16"
    version = "2"   # 2: overlay_bottom captions sit inside the strip
    file_suffix = "_G.bin"
    content_type = "application/octet-stream"
    color = False
    default_params = {"contrast": 1.0, "brightness": 1.0, "gamma": 1.0,
                      "lift": 0.0, "lift_threshold": 90.0}

    def _strip(self, device) -> tuple[int, int]:
        sh = int(device.options.get("strip_height", DEFAULT_STRIP_HEIGHT))
        sh = max(1, min(sh, device.height))
        top = (device.height - sh) // 2
        return top, top + sh

    def content_size(self, device):
        top, bottom = self._strip(device)
        return device.width, bottom - top

    def _quantized(self, img, device, params, focal) -> np.ndarray:
        """16-level indices (H x W) for the panel, as mounted."""
        w, h = device.width, device.height
        top, bottom = self._strip(device)
        sh = bottom - top
        if device.options.get("fit", "letterbox") == "cover":
            strip = resize_lanczos(cover_crop(img, w, sh, focal), w, sh)
            y = top
        else:
            # Full width; crop the height around the focal point or pad it.
            scaled = img.resize((w, max(1, round(img.height * w / img.width))), Image.Resampling.LANCZOS)
            if scaled.height > sh:
                fy = focal[1]
                crop_top = min(max(round(fy * scaled.height - sh / 2), 0), scaled.height - sh)
                scaled = scaled.crop((0, crop_top, w, crop_top + sh))
            strip, y = scaled, top + (sh - scaled.height) // 2
        strip = apply_tuning(strip.convert("RGB"), params).convert("L")
        canvas = Image.new("L", (w, h), 255)
        canvas.paste(strip, (0, y))
        if params.get("caption"):
            canvas = draw_caption(canvas, params["caption"], params["caption_layout"],
                                  params["caption_size"], strip=(top, bottom))
        if params.get("battery_overlay") is not None:
            canvas = draw_battery(canvas.convert("RGB"), params["battery_overlay"], False).convert("L")
        canvas = rotate_cw(canvas, device.output_rotation)
        # Quantize from RGB: Pillow's palette quantize mis-maps "L" input.
        q = canvas.convert("RGB").quantize(palette=_palette(), dither=Image.Dither.FLOYDSTEINBERG)
        # Padding slots are white too; fold any that got picked back onto 15.
        return np.minimum(np.asarray(q, dtype=np.uint8), LEVELS - 1)

    def prepare(self, img, device, params, focal=(0.5, 0.5)) -> bytes:
        data = pack_nibbles(self._quantized(img, device, params, focal))
        expected = device.width * device.height // 2
        if len(data) != expected:
            raise ValueError(f"packed image is {len(data)} bytes, expected {expected}")
        return data

    def decode(self, data, device):
        w, h = (device.height, device.width) if device.output_rotation in (90, 270) else (device.width, device.height)
        return unpack_nibbles(data, w, h)

    def preview(self, img, device, params, focal=(0.5, 0.5)):
        idx = self._quantized(img, device, params, focal)
        return rotate_cw(Image.fromarray((idx * 17).astype(np.uint8), "L"),
                         (360 - device.output_rotation) % 360).convert("RGB")
