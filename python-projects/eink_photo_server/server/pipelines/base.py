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


_SRGB = ImageCms.createProfile("sRGB")


def load_oriented(path) -> Image.Image:
    """Open, apply EXIF orientation, and convert to sRGB RGB (dropping alpha onto white)."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
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
