"""Pipeline contract + shared image helpers.

A pipeline turns a source photo into the exact bytes one kind of panel wants.
It knows nothing about playlists or HTTP; devices.yaml pairs a pipeline with a
protocol adapter per device.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageCms, ImageEnhance, ImageOps


class Pipeline:
    name: str = ""
    # Bump whenever output changes for the same inputs -- it's part of the cache
    # key, so a bump invalidates every cached image this pipeline produced.
    version: str = "1"
    file_suffix: str = "_L.jpg"
    content_type: str = "image/jpeg"
    color: bool = False   # panel can show colour (e.g. red low-battery overlay)
    default_params: dict = {}

    def prepare(self, img: Image.Image, device, params: dict,
                focal: tuple[float, float] = (0.5, 0.5)) -> bytes:
        raise NotImplementedError

    def preview(self, img: Image.Image, device, params: dict,
                focal: tuple[float, float] = (0.5, 0.5)) -> Image.Image | None:
        """Optional: what the panel will roughly look like, as mounted (unrotated)."""
        return None

    def decode(self, data: bytes, device) -> Image.Image | None:
        """For non-image outputs (e.g. packed panel buffers): the prepared bytes
        as a viewable image, so the UI can show exactly what was sent."""
        return None

    def content_size(self, device) -> tuple[int, int]:
        """Size of the area a photo fills (the whole panel unless the pipeline
        places photos in a sub-region, e.g. a panorama strip). Test cards render
        at this size."""
        return device.width, device.height


_SRGB = ImageCms.createProfile("sRGB")


HIGH_BIT_DEPTH_MODES = {"I;16", "I;16L", "I;16B", "I;16N", "I", "F"}


def percentile_to_l(img: Image.Image, low: float = 0.5, high: float = 99.5) -> Image.Image:
    """High-bit-depth grayscale -> 8-bit L by percentile mapping (low% -> black,
    high% -> white), as in python-projects/grayscale_image_conversion/prepare_image.py.
    A plain convert("L") would clip 16-bit data instead of scaling it."""
    a = np.asarray(img, dtype=np.float64)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return Image.new("L", img.size, 0)
    lo, hi = np.percentile(finite, low), np.percentile(finite, high)
    if hi <= lo:
        lo, hi = finite.min(), finite.max()
        if hi <= lo:
            return Image.new("L", img.size, 255 if hi > 0 else 0)
    out = np.clip(np.nan_to_num((a - lo) / (hi - lo), nan=0.0, posinf=1.0, neginf=0.0), 0, 1)
    return Image.fromarray(np.round(out * 255).astype(np.uint8), "L")


def load_oriented(path) -> Image.Image:
    """Open, apply EXIF orientation, and convert to sRGB RGB (dropping alpha onto
    white; high-bit-depth grayscale is percentile-mapped first)."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode in HIGH_BIT_DEPTH_MODES:
        return percentile_to_l(img).convert("RGB")
    icc = img.info.get("icc_profile")
    if icc and img.mode in ("RGB", "RGBA"):
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            img = ImageCms.profileToProfile(img, src, _SRGB, outputMode=img.mode)
        except (ImageCms.PyCMSError, OSError):
            pass  # bad/unsupported profile -- treat as sRGB
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    return img.convert("RGB")


def cover_crop(img: Image.Image, w: int, h: int, focal=(0.5, 0.5)) -> Image.Image:
    """Crop to the w:h aspect ratio, centred on the focal point (fractions of the
    image), clamped so the crop box stays inside the image."""
    sw, sh = img.size
    target = w / h
    if sw / sh > target:
        cw, ch = round(sh * target), sh
    else:
        cw, ch = sw, round(sw / target)
    fx, fy = focal
    left = min(max(round(fx * sw - cw / 2), 0), sw - cw)
    top = min(max(round(fy * sh - ch / 2), 0), sh - ch)
    return img.crop((left, top, left + cw, top + ch))


def resize_lanczos(img: Image.Image, w: int, h: int) -> Image.Image:
    return img.resize((w, h), Image.Resampling.LANCZOS)


# Tuning values that leave an image unchanged. Stored as a photo's per-photo
# params to bypass device/pipeline tuning (e.g. for pre-tuned test cards).
NEUTRAL_TUNING = {"saturation": 1.0, "contrast": 1.0, "brightness": 1.0, "gamma": 1.0,
                  "lift": 0.0, "lift_threshold": 90.0}

TUNING_KEYS = tuple(NEUTRAL_TUNING)

# Rec. 709 luma weights (as used by eink-optimize).
_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _lift_and_gamma(img: Image.Image, lift: float, threshold: float, gamma: float) -> Image.Image:
    """Shadow lift and luma-only gamma, after fwmone/eink-optimize (MIT).

    Lift: for pixels with luma Y < threshold, add lift * (1 - Y/threshold)^2 to
    R, G and B -- a soft raise of the deepest shadows, which Spectra 6 crushes.
    Gamma: map luma through 255 * (Y/255)^(1/gamma) and scale RGB by Y'/Y, so
    hue and saturation are preserved (>1 lightens, as before).
    """
    a = np.asarray(img.convert("RGB"), dtype=np.float64)
    if lift and threshold > 0:
        y = a @ _LUMA
        t = np.clip(1.0 - y / threshold, 0.0, 1.0)
        a = np.clip(a + (lift * t * t)[..., None], 0, 255)
    if gamma != 1.0:
        y0 = a @ _LUMA
        y1 = 255.0 * (y0 / 255.0) ** (1.0 / gamma)
        scale = np.divide(y1, y0, out=np.ones_like(y0), where=y0 > 0)
        a = np.clip(a * scale[..., None], 0, 255)
    return Image.fromarray(np.rint(a).astype(np.uint8), "RGB")


def apply_tuning(img: Image.Image, params: dict) -> Image.Image:
    """Lift -> luma gamma -> brightness -> contrast -> saturation.
    Missing keys are neutral."""
    lift = float(params.get("lift", 0.0))
    gamma = float(params.get("gamma", 1.0))
    if lift or gamma != 1.0:
        img = _lift_and_gamma(img, lift, float(params.get("lift_threshold", 90.0)), gamma)
    for key, enhancer in (("brightness", ImageEnhance.Brightness),
                          ("contrast", ImageEnhance.Contrast),
                          ("saturation", ImageEnhance.Color)):
        if params.get(key, 1.0) != 1.0:
            img = enhancer(img).enhance(params[key])
    return img


LOW_BATTERY = 10  # percent; below this the overlay is red (and shown in "low" mode)


def draw_battery(img: Image.Image, pct: int, color: bool, height: int = 20,
                 low: int = LOW_BATTERY) -> Image.Image:
    """Draw 'NN%' in a small white box in the upper-right corner (as mounted).
    Red when below `low` on colour panels, black otherwise."""
    from PIL import ImageDraw, ImageFont  # local: only needed when overlaying
    img = img.copy()
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=round(height * 0.8))
    text = f"{pct}%"
    left, top, right, bottom = d.textbbox((0, 0), text, font=font)
    pad = max(round(height * 0.2), 2)
    box_w = right - left + 2 * pad
    x1, y0 = img.width - 4, 4
    x0, y1 = x1 - box_w, y0 + height
    d.rectangle([x0, y0, x1, y1], fill="white")
    fill = (255, 0, 0) if color and pct < low else (0, 0, 0)
    # Centre the glyphs' ink box vertically inside the white box.
    d.text((x0 + pad - left, y0 + (height - (bottom - top)) / 2 - top), text, fill=fill, font=font)
    return img


# --- captions ----------------------------------------------------------------
# Server-side caption overlay, any pipeline can use it. Same layout as the EE03
# firmware's drawTextOverlay(): a left run "Title · Location · Film" and a larger
# right run "Artist ‡ Date". The separators are drawn as shapes (as the firmware
# does), so they work whatever glyphs the font has.

CAPTION_LAYOUTS = ("none", "below_strip", "overlay_bottom")
# A real font if the system has one (the Docker image installs DejaVu; nothing is
# vendored in the repo), else Pillow's bundled font (ASCII-ish coverage only).
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
)
_font_cache: dict[int, object] = {}


def caption_font(size: int):
    from PIL import ImageFont
    if size not in _font_cache:
        font = None
        for path in _FONT_CANDIDATES:
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        _font_cache[size] = font or ImageFont.load_default(size=size)
    return _font_cache[size]


def caption_runs(cap: dict) -> tuple[list[str], list[str]]:
    left = [cap.get(k, "").strip() for k in ("title", "location", "film")]
    right = [cap.get(k, "").strip() for k in ("artist", "date")]
    return [t for t in left if t], [t for t in right if t]


def _run_width(draw, parts, font, sep_w) -> float:
    return sum(draw.textlength(p, font=font) for p in parts) + sep_w * max(len(parts) - 1, 0)


def _draw_run(draw, x, baseline, parts, font, size, fill, sep, stroke=None):
    """Draw parts left-to-right from x on a baseline, with shape separators."""
    sep_w = size * 1.1
    kw = {"stroke_width": max(1, size // 12), "stroke_fill": stroke} if stroke is not None else {}
    for i, part in enumerate(parts):
        if i:
            cx = x + sep_w / 2
            if sep == "dot":
                r = max(1.5, size * 0.09)
                cy = baseline - size * 0.32
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
            else:  # double dagger
                top, bot = baseline - size * 0.72, baseline + size * 0.12
                w, lw = size * 0.22, max(1, round(size / 14))
                draw.line([(cx, top), (cx, bot)], fill=fill, width=lw)
                for y in (top + size * 0.18, bot - size * 0.24):
                    draw.line([(cx - w, y), (cx + w, y)], fill=fill, width=lw)
            x += sep_w
        draw.text((x, baseline), part, font=font, fill=fill, anchor="ls", **kw)
        x += draw.textlength(part, font=font)


def _contrast_ink(img: Image.Image, box) -> tuple:
    """(fill, stroke) for text over the pixels in box. Gray panels follow
    prepare_image.py's gray_color_for_mean() (the per-corner text_color_* the old
    EE03 firmware drew with, no outline); colour panels get black or white with
    an outline in the other, so it survives busy photos."""
    region = img.convert("L").crop(box)
    mean = float(np.asarray(region, dtype=np.float32).mean()) if region.size[0] and region.size[1] else 255.0
    if img.mode == "L":
        level = mean * 15 / 255
        gray = 12 if level < 4.5 else 15 if level < 7.5 else 0 if level < 10.5 else 3
        return gray * 17, None
    return ((0, 0, 0), (255, 255, 255)) if mean >= 128 else ((255, 255, 255), (0, 0, 0))


def draw_caption(img: Image.Image, cap: dict, layout: str, size: int,
                 strip: tuple[int, int] | None = None) -> Image.Image:
    """Render the caption onto img (RGB or L). `strip` = (top, bottom) rows of a
    photo strip, if the pipeline uses one:
      below_strip     in the white band under the strip, black
      overlay_bottom  over the bottom of the photo (the strip's bottom edge when
                      there is one), each run in a colour contrasting with what's
                      under it -- the old EE03 firmware's look on a 778 strip
    below_strip with no strip falls back to overlay_bottom."""
    from PIL import ImageDraw
    left, right = caption_runs(cap)
    if layout == "none" or not (left or right):
        return img
    img = img.copy()
    d = ImageDraw.Draw(img)
    f_l, f_r = caption_font(size), caption_font(round(size * 1.5))
    size_r = round(size * 1.5)
    margin = max(8, round(img.width * 0.013))
    w_r = _run_width(d, right, f_r, size_r * 1.1)
    # Keep the left run clear of the right one: drop trailing parts, then trim.
    room = img.width - 3 * margin - w_r
    while left and _run_width(d, left, f_l, size * 1.1) > room:
        if len(left) > 1:
            left = left[:-1]
        else:
            left = [left[0][:-4] + "..."] if len(left[0]) > 4 else []
    w_l = _run_width(d, left, f_l, size * 1.1)
    x_l, x_r = margin, img.width - margin - w_r

    if layout == "below_strip" and strip:
        baseline = strip[1] + round(size * 0.6) + round(size_r * 0.8)
        black = 0 if img.mode == "L" else (0, 0, 0)
        ink_l = ink_r = (black, None)
    else:
        # Leave room under the baseline for descenders, inside the photo.
        bottom = strip[1] if strip else img.height
        baseline = bottom - max(round(size_r * 0.35), margin // 2)
        top = baseline - size_r
        ink_l = _contrast_ink(img, (x_l, top, x_l + max(1, int(w_l)), bottom))
        ink_r = _contrast_ink(img, (int(x_r), top, int(x_r + w_r) + 1, bottom))
    if left:
        _draw_run(d, x_l, baseline, left, f_l, size, ink_l[0], "dot", ink_l[1])
    if right:
        _draw_run(d, x_r, baseline, right, f_r, size_r, ink_r[0], "dagger", ink_r[1])
    return img


def rotate_cw(img: Image.Image, degrees: int) -> Image.Image:
    return {
        0: img,
        90: img.transpose(Image.Transpose.ROTATE_270),   # PIL's ROTATE_* are CCW
        180: img.transpose(Image.Transpose.ROTATE_180),
        270: img.transpose(Image.Transpose.ROTATE_90),
    }[degrees % 360]


def encode_jpeg(img: Image.Image, quality: int = 92) -> bytes:
    """Baseline (non-progressive) sRGB JPEG, 4:4:4, no EXIF/ICC."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, subsampling=0,
                            progressive=False, optimize=True)
    return buf.getvalue()
