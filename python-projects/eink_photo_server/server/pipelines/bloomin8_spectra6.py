"""Bloomin8 (E Ink Spectra 6) pipeline.

The frame dithers to its six inks itself, so we hand it a clean, slightly punchy
full-colour JPEG at native resolution -- no dithering here. preview() simulates
the panel's dither so the web UI can show roughly what will appear.
"""
from __future__ import annotations

from PIL import Image

from ..dashboards.draw import Fill, Theme
from . import register
from .base import (Pipeline, apply_tuning, cover_crop, draw_battery, draw_caption, encode_jpeg,
                   resize_lanczos, rotate_cw)

# Nominal Spectra 6 inks. The real pigments are duller than these; good enough
# for a preview, not for colour-accurate simulation.
SPECTRA6 = [
    (0, 0, 0), (255, 255, 255), (200, 30, 30),
    (240, 210, 0), (30, 60, 170), (40, 130, 60),
]


def _palette_image() -> Image.Image:
    pal = Image.new("P", (1, 1))
    flat = [c for rgb in SPECTRA6 for c in rgb]
    pal.putpalette(flat + flat[:3] * (256 - len(SPECTRA6)))
    return pal


_K, _W, _R, _Y, _B, _GR = SPECTRA6


@register
class Bloomin8Spectra6(Pipeline):
    name = "bloomin8_spectra6"
    version = "3"   # 2: luma-only gamma + shadow lift; 3: per-run caption contrast
    file_suffix = "_L.jpg"
    color = True
    default_params = {"saturation": 1.2, "contrast": 1.1, "brightness": 1.0,
                      "gamma": 1.0, "lift": 0.0, "lift_threshold": 90.0, "quality": 92}

    def _tuned(self, img, device, params, focal):
        img = cover_crop(img, device.width, device.height, focal)
        img = resize_lanczos(img, device.width, device.height)
        return apply_tuning(img, params)

    def prepare(self, img, device, params, focal=(0.5, 0.5)) -> bytes:
        img = self._tuned(img, device, params, focal)
        if params.get("caption"):
            img = draw_caption(img, params["caption"], params["caption_layout"], params["caption_size"])
        if params.get("battery_overlay") is not None:
            img = draw_battery(img, params["battery_overlay"], self.color)
        img = rotate_cw(img, device.output_rotation)
        return encode_jpeg(img, int(params["quality"]))

    # Dashboards: flat Spectra 6 colours only (the frame dithers anything else,
    # which would speckle text and tiles), drawn without antialiasing so edges
    # don't snap to stray inks.
    THEME = Theme(
        name="spectra6", antialias=False, muted=_B, rule=_K, hi=_R, lo=_B, bar_bg=_K, min_font=14,
        fills={
            "clear": Fill(bg=_Y, border=None, halo=None),
            "partly": Fill(bg=_W, border=_Y, border_w=4),
            "cloudy": Fill(),
            "fog": Fill(pattern="fog", pattern_ink=_K),
            "wind": Fill(bg=_GR, border=None, icon=_W, halo=None),
            "rain": Fill(bg=_B, border=None, icon=_W, halo=None),
            "mix": Fill(bg=_B, border=None, icon=_W, halo=None, pattern="hatch", pattern_ink=_W),
            "snow": Fill(bg=_W, border=_B, border_w=3, icon=_B),
            "storm": Fill(bg=_K, border=None, icon=_Y, halo=None),
            "hot": Fill(bg=_R, border=None, icon=_W, halo=None),
            "cold": Fill(bg=_W, border=_B, border_w=3, icon=_B),
        })

    def dashboard_theme(self, device):
        return self.THEME

    def _snap(self, img):
        """Every pixel onto the nearest ink (antialiased edges included), no dither."""
        return img.convert("RGB").quantize(palette=_palette_image(), dither=Image.Dither.NONE).convert("RGB")

    def encode_rendered(self, img, device) -> bytes:
        return encode_jpeg(rotate_cw(self._snap(img), device.output_rotation), 95)

    def rendered_preview(self, img, device):
        return self._snap(img)

    def preview(self, img, device, params, focal=(0.5, 0.5)):
        img = self._tuned(img, device, params, focal)
        if params.get("caption"):
            img = draw_caption(img, params["caption"], params["caption_layout"], params["caption_size"])
        return img.quantize(palette=_palette_image(),
                            dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
