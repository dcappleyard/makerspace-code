"""Pipeline contract + shared image helpers.

A pipeline turns a source photo into the exact bytes one kind of panel wants.
It knows nothing about playlists or HTTP; devices.yaml pairs a pipeline with a
protocol adapter per device.
"""
from __future__ import annotations

import io

from PIL import Image, ImageCms, ImageOps


class Pipeline:
    name: str = ""
    # Bump whenever output changes for the same inputs -- it's part of the cache
    # key, so a bump invalidates every cached image this pipeline produced.
    version: str = "1"
    file_suffix: str = "_L.jpg"
    content_type: str = "image/jpeg"
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
