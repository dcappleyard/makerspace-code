"""Drawing primitives shared by dashboards.

Dashboards are drawn natively for each panel, not rendered once and converted.
Each pipeline supplies a Surface (its content size) and a Theme (the inks it can
show exactly), and the dashboard draws with *semantic* inks: fg, muted, rule,
and one Fill per weather condition. Then the pipeline's encode_rendered() packs
the pixels with no photo dithering. A B/W theme gets its "greys" from patterns
(stipple, hatch...), a 16-grey theme uses exact grey levels, and a colour theme
uses its palette colours.

Canvases are RGB, and every ink is an RGB tuple the panel shows exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Ink = tuple[int, int, int]
WHITE: Ink = (255, 255, 255)
BLACK: Ink = (0, 0, 0)

ICON_FONT = Path(__file__).parent / "fonts" / "weathericons-regular-webfont.ttf"
_TEXT_FONTS = {
    False: ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"),
    True: ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf"),
}


@dataclass(frozen=True)
class Fill:
    """How a condition's inset tile looks."""
    bg: Ink = WHITE
    pattern: str | None = None      # see PATTERNS
    pattern_ink: Ink = BLACK
    icon: Ink = BLACK
    halo: Ink | None = WHITE        # outline around the icon so it reads over a pattern
    border: Ink | None = BLACK
    border_w: int = 1               # x the tile's scale (see chip())


@dataclass(frozen=True)
class Theme:
    name: str
    bg: Ink = WHITE
    fg: Ink = BLACK
    muted: Ink = BLACK               # secondary text (lows, labels)
    rule: Ink = BLACK                # divider lines
    hi: Ink = BLACK                  # daily high
    lo: Ink = BLACK                  # daily low
    bar_bg: Ink = BLACK              # title bar
    bar_fg: Ink = WHITE
    antialias: bool = True           # False for 1-bit panels: crisp glyph edges
    min_font: int = 12
    fills: dict = field(default_factory=dict)   # condition -> Fill

    def fill(self, cond: str) -> Fill:
        return self.fills.get(cond) or self.fills.get("cloudy") or Fill()


@dataclass(frozen=True)
class Surface:
    width: int
    height: int
    theme: Theme

    def canvas(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (self.width, self.height), self.theme.bg)
        d = ImageDraw.Draw(img)
        if not self.theme.antialias:
            d.fontmode = "1"
        return img, d


# --- fonts ---------------------------------------------------------------------

@lru_cache(maxsize=256)
def font(size: int, bold: bool = False):
    size = max(6, int(size))
    for path in _TEXT_FONTS[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=128)
def icon_font(size: int):
    return ImageFont.truetype(str(ICON_FONT), max(6, int(size)))


def text_w(d: ImageDraw.ImageDraw, text: str, f) -> int:
    l, _, r, _ = d.textbbox((0, 0), text, font=f)
    return r - l


def fit_font(d, text: str, max_w: float, max_h: float, bold: bool = False, min_size: int = 6):
    """Largest font (by cap height ~ max_h) whose text fits max_w."""
    size = max(min_size, int(max_h))
    while size > min_size and text_w(d, text, font(size, bold)) > max_w:
        size -= 1
    return font(size, bold)


def text(d, xy, s: str, f, fill: Ink, anchor: str = "mm") -> None:
    if s:
        d.text(xy, s, font=f, fill=fill, anchor=anchor)


# --- patterns ------------------------------------------------------------------
# Each returns a bool mask (True = pattern ink) in absolute canvas coordinates,
# so neighbouring tiles line up. Spacing scales with `s` (the tile's scale) so
# a pattern stays visible on big panels without turning to mush on small ones.

def _grid(w, h, x0, y0):
    ys, xs = np.mgrid[y0:y0 + h, x0:x0 + w]
    return xs, ys


PATTERNS = {
    # ~12% dots: partly cloudy
    "dots": lambda xs, ys, s: (xs % (4 * s) < s) & (ys % (4 * s) < s) & (((xs // (4 * s)) + (ys // (4 * s))) % 2 == 0),
    # 25% stipple: cloudy
    "stipple": lambda xs, ys, s: (xs % (2 * s) < s) & (ys % (2 * s) < s),
    # 50% checker
    "checker": lambda xs, ys, s: ((xs // s) + (ys // s)) % 2 == 0,
    # diagonal hatch: rain
    "hatch": lambda xs, ys, s: (xs + ys) % (4 * s) < s,
    # cross-hatch: wintry mix
    "crosshatch": lambda xs, ys, s: ((xs + ys) % (4 * s) < s) | ((xs - ys) % (4 * s) < s),
    # horizontal lines: wind
    "hlines": lambda xs, ys, s: ys % (3 * s) < s,
    # sparse horizontal lines: fog
    "fog": lambda xs, ys, s: ys % (5 * s) < s,
    # vertical lines: hot
    "vlines": lambda xs, ys, s: xs % (3 * s) < s,
}


def pattern_tile(w: int, h: int, x0: int, y0: int, fill: Fill, s: int) -> Image.Image:
    tile = Image.new("RGB", (w, h), fill.bg)
    if fill.pattern:
        xs, ys = _grid(w, h, x0, y0)
        mask = PATTERNS[fill.pattern](xs, ys, max(1, s))
        arr = np.asarray(tile).copy()
        arr[mask] = fill.pattern_ink
        tile = Image.fromarray(arr, "RGB")
    return tile


# --- widgets -------------------------------------------------------------------

def chip(img: Image.Image, d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: Fill,
         glyph: str, theme: Theme) -> None:
    """The inset condition tile: a rounded square shaded for the condition, with
    the weather icon on top (haloed so it reads over a pattern)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    w, h = x1 - x0, y1 - y0
    if w < 6 or h < 6:
        return
    side = min(w, h)
    s = max(1, side // 48)                 # pattern / border scale
    r = max(2, side // 7)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    img.paste(pattern_tile(w, h, x0, y0, fill, s), (x0, y0), mask)
    if fill.border is not None:
        d.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=r, outline=fill.border,
                            width=max(1, fill.border_w * s))
    size = int(side * 0.62)
    f = icon_font(size)
    halo = max(1, size // 14) if fill.halo is not None and fill.pattern else 0
    d.text(((x0 + x1) / 2, (y0 + y1) / 2), glyph, font=f, fill=fill.icon, anchor="mm",
           stroke_width=halo, stroke_fill=fill.halo if halo else None)


def pill(img: Image.Image, d: ImageDraw.ImageDraw, box: tuple[float, float, float, float], fill: Fill,
         theme: Theme) -> None:
    """A fully rounded bar (the range-bar style), shaded for the condition.
    Outlined only when its fill wouldn't otherwise stand out from the page, or
    when the outline is the condition's mark (border_w > 1)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    w, h = x1 - x0, y1 - y0
    if w < 4 or h < 4:
        return
    r = min(w, h) // 2
    s = max(1, w // 48)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    img.paste(pattern_tile(w, h, x0, y0, fill, s), (x0, y0), mask)
    plain = fill.pattern is None and fill.bg == theme.bg
    if fill.border is not None and (plain or fill.border_w > 1):
        d.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=r, outline=fill.border,
                            width=max(1, fill.border_w * s))


def small_icon(d, xy, glyph: str, size: int, ink: Ink, anchor: str = "rm") -> int:
    """An inline icon (e.g. the raindrop before a precip %). Returns its width."""
    f = icon_font(size)
    d.text(xy, glyph, font=f, fill=ink, anchor=anchor)
    return text_w(d, glyph, f)


def hline(d, x0, x1, y, ink: Ink, w: int = 1) -> None:
    d.line([(x0, y), (x1, y)], fill=ink, width=w)


def vline(d, x, y0, y1, ink: Ink, w: int = 1) -> None:
    d.line([(x, y0), (x, y1)], fill=ink, width=w)
