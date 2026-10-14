"""Tuning test cards: one image, three columns, each tuned with its own params.

The card is rendered at the device's mounted resolution and tuned per column
with the same apply_tuning() the pipelines use. It's then saved as a photo with
neutral per-photo tuning, so the pipeline only rotates/encodes it and the panel
shows columns A/B/C side by side.

Pure ink swatches barely respond to saturation/contrast, so each column also
carries ramps, wedges and tints where the differences actually show.
"""
from __future__ import annotations

import colorsys

from PIL import Image, ImageDraw, ImageFont

from .pipelines.base import apply_tuning, cover_crop, resize_lanczos
from .pipelines.bloomin8_spectra6 import SPECTRA6

KINDS = ("color", "mono")
TUNING_KEYS = ("saturation", "contrast", "brightness", "gamma")
LABEL_FRAC = 0.09

PASTELS = [(232, 190, 172), (198, 134, 66), (141, 85, 36),   # skin tones
           (170, 205, 235), (180, 225, 190), (250, 215, 180)]  # sky, mint, peach


def _font(px: int):
    return ImageFont.load_default(size=max(px, 8))


def _hue_sweep(w, h, sat):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        r, g, b = colorsys.hsv_to_rgb(x / w, sat, 1.0)
        for y in range(h):
            px[x, y] = (round(r * 255), round(g * 255), round(b * 255))
    return img


def _ramp(w, h, start, end):
    """Horizontal linear ramp between two RGB colours."""
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for x in range(w):
        t = x / max(w - 1, 1)
        d.line([(x, 0), (x, h)], fill=tuple(round(a + (b - a) * t) for a, b in zip(start, end)))
    return img


def _steps(w, h, values):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    n = len(values)
    for i, v in enumerate(values):
        fill = v if isinstance(v, tuple) else (v, v, v)
        d.rectangle([round(i * w / n), 0, round((i + 1) * w / n), h], fill=fill)
    return img


def _rows(w, h, rows, filler):
    """Stack (fraction, builder) rows top-down; `filler` gets whatever height is left."""
    col = Image.new("RGB", (w, h), "white")
    y = 0
    for frac, build in rows:
        rh = round(h * frac)
        col.paste(build(w, rh), (0, y))
        y += rh
    if h - y > 0:
        col.paste(filler(w, h - y), (0, y))
    return col


def _photo_strip(photo_img, focal, mono):
    """Builder for the same crop of a library photo in every column."""
    def build(w, h):
        img = resize_lanczos(cover_crop(photo_img, w, h, focal), w, h)
        return img.convert("L").convert("RGB") if mono else img
    return build


def _color_column(w, h, strip):
    def tints(w, h):
        inks = [c for c in SPECTRA6 if c not in ((0, 0, 0), (255, 255, 255))]
        img = Image.new("RGB", (w, h), "white")
        for i, ink in enumerate(inks):
            y0, y1 = round(i * h / len(inks)), round((i + 1) * h / len(inks))
            half = w // 2
            img.paste(_ramp(half, y1 - y0, (255, 255, 255), ink), (0, y0))
            img.paste(_ramp(w - half, y1 - y0, ink, (0, 0, 0)), (half, y0))
        return img

    rows = [
        (LABEL_FRAC, lambda w, h: Image.new("RGB", (w, h), "white")),
        (0.12, lambda w, h: _steps(w, h, SPECTRA6)),
        (0.07, lambda w, h: _hue_sweep(w, h, 1.0)),
        (0.07, lambda w, h: _hue_sweep(w, h, 0.5)),
        (0.06, lambda w, h: _ramp(w, h, (0, 0, 0), (255, 255, 255))),
        (0.06, lambda w, h: _steps(w, h, [round(255 * i / 10) for i in range(11)])),
        (0.09, lambda w, h: _steps(w, h, PASTELS)),
    ]
    return _rows(w, h, rows, strip or tints)


def _mono_column(w, h, strip):
    def detail(w, h):
        img = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(img)
        q = w // 4
        for x in range(0, q, 2):                      # 1px vertical lines
            d.line([(x, 0), (x, h)], fill="black")
        for y in range(0, h, 2):                      # 1px horizontal lines
            d.line([(q, y), (2 * q, y)], fill="black")
        for cell, x0 in ((2, 2 * q), (4, 3 * q)):     # 2px and 4px checkerboards
            for y in range(0, h, cell):
                for x in range(x0, x0 + q, cell):
                    if ((x - x0) // cell + y // cell) % 2 == 0:
                        d.rectangle([x, y, x + cell - 1, y + cell - 1], fill="black")
        return img

    def text(w, h):
        img = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(img)
        y = 2
        for px in (10, 14, 20):
            px = max(round(px * h / 58), 8)
            d.text((4, y), f"{px}px Aa Bb 0123", fill="black", font=_font(px))
            y += px + 3
        return img

    def shadows_highlights(w, h):
        img = Image.new("RGB", (w, h), "white")
        img.paste(_steps(w, h // 2, [round(64 * i / 7) for i in range(8)]), (0, 0))
        img.paste(_steps(w, h - h // 2, [191 + round(64 * i / 7) for i in range(8)]), (0, h // 2))
        return img

    rows = [
        (LABEL_FRAC, lambda w, h: Image.new("RGB", (w, h), "white")),
        (0.11, lambda w, h: _steps(w, h, [round(255 * i / 15) for i in range(16)])),
        (0.08, lambda w, h: _ramp(w, h, (0, 0, 0), (255, 255, 255))),
        (0.16, detail),
        (0.12, text),
    ]
    return _rows(w, h, rows, strip or shadows_highlights)


def _label(params: dict, name: str) -> str:
    return f"{name}  sat {params['saturation']:.2f}  con {params['contrast']:.2f}\n" \
           f"    bri {params['brightness']:.2f}  gamma {params['gamma']:.2f}"


def render_card(kind: str, w: int, h: int, segments: list[dict],
                photo_img: Image.Image | None = None, focal=(0.5, 0.5)) -> Image.Image:
    """Render a w x h card with one column per params dict in `segments`. If
    photo_img is given, the bottom of each column is the same crop of it."""
    if kind not in KINDS:
        raise ValueError(f"unknown card kind {kind!r}")
    build = _color_column if kind == "color" else _mono_column
    strip = _photo_strip(photo_img, focal, kind == "mono") if photo_img else None
    card = Image.new("RGB", (w, h), "white")
    n = len(segments)
    label_h = round(h * LABEL_FRAC)
    font = _font(max(round(label_h * 0.32), 8))
    d = ImageDraw.Draw(card)
    for i, params in enumerate(segments):
        params = {k: float(params.get(k, 1.0)) for k in TUNING_KEYS}
        x0, x1 = round(i * w / n), round((i + 1) * w / n)
        col = apply_tuning(build(x1 - x0, h, strip), params)
        card.paste(col, (x0, 0))
        # Label and separators go on after tuning so they stay crisp and legible.
        d.rectangle([x0, 0, x1, label_h - 1], fill="white")
        d.multiline_text((x0 + 6, 3), _label(params, "ABCDEFGH"[i]), fill="black", font=font, spacing=2)
        if i:
            d.line([(x0, 0), (x0, h)], fill="black", width=2)
    return card
