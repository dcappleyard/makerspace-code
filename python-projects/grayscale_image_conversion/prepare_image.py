#!/usr/bin/env python3

"""
Prepare a panorama photo (and its metadata) for the SD-card photo frame.

For each source photo this produces a matched pair, written to --output-dir:
    <name>.bin  -- display-ready, nibble-packed 4-bit grayscale, exactly
                   1872x1404 (1,314,144 bytes), ready for the ESP32 to read
                   straight off the SD card and pushImage() to the EE03 panel.
    <name>.xml  -- a small, flat metadata sidecar the firmware parses to draw
                   the caption line (Artist / Date / Location / Description /
                   Film). A <name>.png preview is also written unless disabled.

Drop the .bin + .xml pairs into the SD card's /pictures/ directory; the frame
cycles through them in filename order.

Photo geometry:
    The panel is 1872 x 1404 (landscape). Photos are treated as ~6:17 panoramas
    that occupy the long (1872 px) edge, so the photo fills a fixed strip of
    1872 x 661 (round(1872 * 6/17)) that is vertically centered on the canvas
    (rows 371..1032), with white above and below. The firmware draws the caption
    line just beneath that strip -- so REGION_HEIGHT/REGION_TOP here must stay in
    sync with the matching constants in the frame's src/main.cpp (kept by hand).

Processing steps:
1. Apply EXIF orientation.
2. Convert high-bit-depth grayscale to 8-bit (percentile contrast mapping).
3. Resize to the panel width (1872) preserving aspect ratio.
4. Crop/pad to the fixed 6:17 strip and center it on a white 1872x1404 canvas.
5. Quantize to 4-bit grayscale (16 shades) with Floyd-Steinberg dithering.
6. Nibble-pack to a .bin, and write the .xml metadata sidecar (+ .png preview).

Example:
    python3 prepare_image.py ~/Pictures/harbor.tif --output-dir ./sd_pictures
    (then answer the metadata prompts)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageOps


DEFAULT_WIDTH = 1872
DEFAULT_HEIGHT = 1404
DEFAULT_BIT_DEPTH = 4
DEFAULT_LOW_PERCENTILE = 0.5
DEFAULT_HIGH_PERCENTILE = 99.5

# The photo strip: a fixed 6:17 region on the panel's long (1872 px) edge,
# vertically centered on the canvas. Keep REGION_HEIGHT/REGION_TOP in sync with
# the REGION_HEIGHT/REGION_TOP constants in the frame firmware's src/main.cpp --
# the firmware places the caption line just below REGION_TOP + REGION_HEIGHT.
REGION_HEIGHT = round(DEFAULT_WIDTH * 6 / 17)  # 661
REGION_TOP = (DEFAULT_HEIGHT - REGION_HEIGHT) // 2  # 371

# Order matters: this is the element order in the .xml sidecar and the order the
# firmware's readTag() looks them up by name.
METADATA_FIELDS = ("artist", "date", "location", "title", "film")


HIGH_BIT_DEPTH_MODES = {
    "I;16",
    "I;16L",
    "I;16B",
    "I;16N",
    "I",
    "F",
}


def flatten_transparency(image: Image.Image) -> Image.Image:
    """
    Composite an image containing transparency onto a white background.

    This function should only be used after high-bit-depth grayscale images
    have been handled, since converting an I;16 image directly to RGB can
    discard or clip its high-bit-depth information.
    """
    has_transparency = (
        image.mode in ("RGBA", "LA")
        or (image.mode == "P" and "transparency" in image.info)
    )

    if has_transparency:
        rgba = image.convert("RGBA")
        background = Image.new(
            "RGBA",
            rgba.size,
            (255, 255, 255, 255),
        )
        return Image.alpha_composite(background, rgba).convert("RGB")

    return image


def percentile_to_8bit(
    array: np.ndarray,
    low_percentile: float,
    high_percentile: float,
) -> np.ndarray:
    """
    Convert a numerical image array to uint8 using percentile mapping.

    Pixels at or below the low percentile become 0.
    Pixels at or above the high percentile become 255.
    Values between them are scaled linearly.
    """
    array = np.asarray(array, dtype=np.float64)

    finite_mask = np.isfinite(array)

    if not np.any(finite_mask):
        raise ValueError("The image contains no finite pixel values.")

    finite_values = array[finite_mask]

    low_value = float(
        np.percentile(finite_values, low_percentile)
    )
    high_value = float(
        np.percentile(finite_values, high_percentile)
    )

    actual_minimum = float(np.min(finite_values))
    actual_maximum = float(np.max(finite_values))

    print(
        f"Original pixel range: "
        f"{actual_minimum:g} to {actual_maximum:g}"
    )
    print(
        f"Percentile mapping: "
        f"{low_percentile:g}% = {low_value:g}, "
        f"{high_percentile:g}% = {high_value:g}"
    )

    if high_value <= low_value:
        # This can happen with a uniform or nearly uniform image.
        if actual_maximum > actual_minimum:
            low_value = actual_minimum
            high_value = actual_maximum
            print(
                "Percentile range was too narrow; "
                "using the full pixel range instead."
            )
        else:
            fill_value = 255 if actual_maximum > 0 else 0
            return np.full(
                array.shape,
                fill_value,
                dtype=np.uint8,
            )

    normalized = (
        (array - low_value)
        / (high_value - low_value)
    )

    # Replace NaN and infinite values before conversion.
    normalized = np.nan_to_num(
        normalized,
        nan=0.0,
        posinf=1.0,
        neginf=0.0,
    )

    normalized = np.clip(normalized, 0.0, 1.0)

    return np.round(normalized * 255.0).astype(np.uint8)


def convert_to_8bit_grayscale(
    image: Image.Image,
    low_percentile: float,
    high_percentile: float,
) -> Image.Image:
    """
    Convert a Pillow image to 8-bit grayscale.

    High-bit-depth grayscale images use percentile-based mapping. Ordinary
    8-bit RGB and grayscale images use Pillow's standard grayscale conversion.
    """
    print(f"Input mode: {image.mode}")
    print(f"Input dimensions: {image.width} x {image.height}")

    if image.mode in HIGH_BIT_DEPTH_MODES:
        array = np.asarray(image)

        grayscale_8bit = percentile_to_8bit(
            array,
            low_percentile=low_percentile,
            high_percentile=high_percentile,
        )

        return Image.fromarray(grayscale_8bit, mode="L")

    image = flatten_transparency(image)

    return image.convert("L")


def resize_to_width(
    image: Image.Image,
    target_width: int,
) -> Image.Image:
    """
    Resize an image to the target width while preserving aspect ratio.
    """
    if image.width <= 0 or image.height <= 0:
        raise ValueError("The input image has invalid dimensions.")

    scale = target_width / image.width
    target_height = max(
        1,
        round(image.height * scale),
    )

    print(
        f"Resized dimensions: "
        f"{target_width} x {target_height}"
    )

    return image.resize(
        (target_width, target_height),
        resample=Image.Resampling.LANCZOS,
    )


def fit_panorama_region(
    image: Image.Image,
    canvas_width: int,
    canvas_height: int,
    region_height: int,
    region_top: int,
) -> Image.Image:
    """
    Fit the (already width-matched) image into the fixed panorama strip and
    center that strip on a white canvas.

    The image must already be canvas_width wide. If it is taller than the strip
    it is center-cropped vertically to exactly region_height; if shorter it is
    white-padded (centered within the strip). The strip is then pasted onto a
    white canvas at y=region_top, leaving white above and below.
    """
    if image.width != canvas_width:
        raise ValueError(
            f"Image width is {image.width}, "
            f"but canvas width is {canvas_width}."
        )

    if image.height > region_height:
        crop_top = (image.height - region_height) // 2
        crop_bottom = crop_top + region_height
        print(
            f"Photo taller than the {region_height}px strip; "
            f"center-cropping rows {crop_top} through {crop_bottom}."
        )
        image = image.crop((0, crop_top, canvas_width, crop_bottom))

    canvas = Image.new("L", (canvas_width, canvas_height), color=255)

    # Center within the strip (matters only when the photo is shorter than the
    # strip); an exactly-strip-height photo lands flush at region_top.
    paste_y = region_top + (region_height - image.height) // 2
    print(
        f"Placing photo strip at y={paste_y} "
        f"(strip {region_top}..{region_top + region_height}), white elsewhere."
    )
    canvas.paste(image, (0, paste_y))

    return canvas


def cover_on_canvas(
    image: Image.Image,
    canvas_width: int,
    canvas_height: int,
    region_height: int,
    region_top: int,
) -> Image.Image:
    """
    Scale the image to *cover* the full canvas_width x region_height strip (so
    it touches all four edges of the strip with no white bars), center-crop the
    overflow, then place that strip on a white canvas at y=region_top.

    Unlike fit_panorama_region (scale-to-width, then letterbox/crop only the
    height), this fills the strip completely: whichever axis overflows after
    scale-to-cover is center-cropped, so wide panoramas lose their left/right
    edges and tall images lose top/bottom, trimmed equally from both sides.
    """
    if image.width <= 0 or image.height <= 0:
        raise ValueError("The input image has invalid dimensions.")

    region_width = canvas_width

    # Cover scale: the larger of the two ratios guarantees both target
    # dimensions are met or exceeded.
    scale = max(region_width / image.width, region_height / image.height)
    scaled_width = max(region_width, round(image.width * scale))
    scaled_height = max(region_height, round(image.height * scale))

    resized = image.resize(
        (scaled_width, scaled_height),
        resample=Image.Resampling.LANCZOS,
    )

    crop_left = (scaled_width - region_width) // 2
    crop_top = (scaled_height - region_height) // 2
    cropped = resized.crop(
        (crop_left, crop_top, crop_left + region_width, crop_top + region_height)
    )

    print(
        f"Cover-scaled to {scaled_width} x {scaled_height}, "
        f"center-cropped to {region_width} x {region_height} "
        f"(trimmed {crop_left}px each side, {crop_top}px top/bottom)."
    )

    canvas = Image.new("L", (canvas_width, canvas_height), color=255)
    print(
        f"Placing filled strip at y={region_top} "
        f"(strip {region_top}..{region_top + region_height}), white elsewhere."
    )
    canvas.paste(cropped, (0, region_top))

    return canvas


def create_grayscale_palette(bit_depth: int) -> list[int]:
    """
    Create a complete 256-entry RGB palette.

    The first 2**bit_depth entries are evenly spaced grayscale values.
    Remaining entries are set to white, but they will never be referenced.
    """
    number_of_levels = 2**bit_depth
    palette: list[int] = []

    for index in range(number_of_levels):
        gray = round(index * 255 / (number_of_levels - 1))
        palette.extend((gray, gray, gray))

    palette.extend(
        [255, 255, 255] * (256 - number_of_levels)
    )

    return palette


def quantize_grayscale(
    image: Image.Image,
    bit_depth: int,
) -> Image.Image:
    """
    Quantize an L-mode image to fixed grayscale levels using
    Floyd-Steinberg error diffusion.

    The returned palette-image indices are guaranteed to remain between
    0 and 2**bit_depth - 1, making them safe for a 1-, 2-, 4-, or 8-bit PNG.
    """
    if image.mode != "L":
        image = image.convert("L")

    number_of_levels = 2**bit_depth
    maximum_index = number_of_levels - 1

    # Work in normalized level space. For 4-bit output, values range 0-15.
    pixels = np.asarray(image, dtype=np.float32)
    working = pixels * maximum_index / 255.0

    height, width = working.shape
    indices = np.empty((height, width), dtype=np.uint8)

    for y in range(height):
        # Serpentine scanning reduces directional artifacts.
        if y % 2 == 0:
            x_range = range(width)
            direction = 1
        else:
            x_range = range(width - 1, -1, -1)
            direction = -1

        for x in x_range:
            old_value = working[y, x]
            new_index = int(np.clip(np.floor(old_value + 0.5), 0, maximum_index))
            indices[y, x] = new_index

            error = old_value - new_index

            next_x = x + direction
            previous_x = x - direction

            # Floyd-Steinberg diffusion, mirrored on alternate rows.
            if 0 <= next_x < width:
                working[y, next_x] += error * (7.0 / 16.0)

            if y + 1 < height:
                if 0 <= previous_x < width:
                    working[y + 1, previous_x] += error * (3.0 / 16.0)

                working[y + 1, x] += error * (5.0 / 16.0)

                if 0 <= next_x < width:
                    working[y + 1, next_x] += error * (1.0 / 16.0)

    output = Image.fromarray(indices, mode="P")
    output.putpalette(create_grayscale_palette(bit_depth))

    return output


def pack_image(image: Image.Image) -> bytes:
    """
    Nibble-pack a 4-bit indexed ('P' mode) image into the byte layout
    Seeed_GFX expects for a GRAY_LEVEL16 EPaper sprite: each byte holds two
    pixels, high nibble = first (even) pixel, low nibble = second (odd) pixel.
    The palette index is stored directly as the gray level (0 = black ..
    15 = white), matching create_grayscale_palette(), so no color-map
    translation is needed.

    (Folded in from the retired panorama_photo_frame_w_counter/tools/
    pack_images.py now that images live on the SD card rather than LittleFS.)
    """
    if image.mode != "P":
        raise ValueError(
            f"Expected a 4-bit palette ('P' mode) image, got mode {image.mode!r}."
        )

    indices = np.asarray(image, dtype=np.uint8).reshape(-1)

    if indices.size and int(indices.max()) > 15:
        raise ValueError(
            "Palette indices must fit in 4 bits (0-15) -- the panel is 4-bit "
            "(GRAY_LEVEL16); use --bit-depth 4."
        )

    if indices.size % 2 != 0:
        indices = np.append(indices, np.uint8(0))

    high = indices[0::2]
    low = indices[1::2]
    packed = ((high << 4) | (low & 0x0F)).astype(np.uint8)

    return packed.tobytes()


def build_sidecar_xml(metadata: dict[str, str]) -> str:
    """
    Build the flat metadata sidecar. Empty fields are written as empty
    elements (the firmware renders them as blank). Values are XML-escaped.
    """
    lines = ["<meta>"]
    for field in METADATA_FIELDS:
        value = escape(metadata.get(field, ""))
        lines.append(f"  <{field}>{value}</{field}>")
    lines.append("</meta>")
    return "\n".join(lines) + "\n"


def prompt_metadata() -> tuple[str, dict[str, str]]:
    """
    Interactively collect the output base filename and metadata fields.
    All fields accept an empty answer.
    """
    print()
    print("Enter photo metadata (press Enter to leave a field blank):")

    prompts = {
        "artist": "Artist",
        "date": "Date (YYYY-MM-DD)",
        "location": "Location",
        "title": "Title",
        "film": "Film",
    }

    metadata: dict[str, str] = {}
    for field in METADATA_FIELDS:
        metadata[field] = input(f"  {prompts[field]}: ").strip()

    base = ""
    while not base:
        base = input("  Output filename (no extension): ").strip()
        # Guard against a user typing an extension or path separators.
        base = Path(base).name
        if base:
            base = Path(base).stem

    return base, metadata


def process_image(
    input_path: Path,
    bit_depth: int,
    low_percentile: float,
    high_percentile: float,
    region_height: int = REGION_HEIGHT,
    region_top: int = REGION_TOP,
    fill: bool = False,
) -> Image.Image:
    """
    Run the imaging pipeline and return the quantized 4-bit 'P' mode canvas.

    region_height/region_top control the photo strip's size and vertical
    placement on the canvas; they default to the ~6:17 strip but a variant
    script (e.g. prepare_image_778.py) can pass a different strip.

    fill selects how the photo maps into the strip:
      - False (default): scale-to-width, then letterbox/center-crop the height
        (a wide panorama keeps its full width and may leave white bars).
      - True: scale-to-cover the whole strip and center-crop the overflow, so
        the photo fills 1872 x region_height with no white bars (wide panoramas
        lose their left/right edges).
    """
    with Image.open(input_path) as source:
        source.load()
        source = ImageOps.exif_transpose(source)

        grayscale = convert_to_8bit_grayscale(
            source,
            low_percentile=low_percentile,
            high_percentile=high_percentile,
        )

        if fill:
            canvas = cover_on_canvas(
                grayscale,
                canvas_width=DEFAULT_WIDTH,
                canvas_height=DEFAULT_HEIGHT,
                region_height=region_height,
                region_top=region_top,
            )
        else:
            resized = resize_to_width(
                grayscale,
                target_width=DEFAULT_WIDTH,
            )
            canvas = fit_panorama_region(
                resized,
                canvas_width=DEFAULT_WIDTH,
                canvas_height=DEFAULT_HEIGHT,
                region_height=region_height,
                region_top=region_top,
            )

        return quantize_grayscale(
            canvas,
            bit_depth=bit_depth,
        )


def write_outputs(
    quantized: Image.Image,
    output_dir: Path,
    base: str,
    metadata: dict[str, str],
    save_preview: bool,
) -> None:
    """
    Write the .bin + .xml pair (and optional .png preview) into output_dir.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    bin_path = output_dir / f"{base}.bin"
    xml_path = output_dir / f"{base}.xml"

    packed = pack_image(quantized)
    bin_path.write_bytes(packed)
    xml_path.write_text(build_sidecar_xml(metadata))

    print()
    print(f"Wrote {bin_path} ({len(packed)} bytes)")
    print(f"Wrote {xml_path}")

    if save_preview:
        png_path = output_dir / f"{base}.png"
        quantized.save(png_path, format="PNG", optimize=True, bits=4)
        print(f"Wrote {png_path} (preview)")

    print()
    print("Copy the .bin + .xml pair into the SD card's /pictures/ directory.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a panorama photo as a display-ready .bin + .xml metadata "
            "pair for the SD-card photo frame."
        )
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Input image path.",
    )

    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("sd_pictures"),
        help="Directory for the .bin/.xml/.png outputs. Default: ./sd_pictures.",
    )

    parser.add_argument(
        "--bit-depth",
        type=int,
        default=DEFAULT_BIT_DEPTH,
        choices=(1, 2, 4, 8),
        help=(
            "Output grayscale bit depth. The panel is 4-bit (GRAY_LEVEL16), so "
            "only 4 produces a valid .bin; other values are for preview PNGs. "
            f"Default: {DEFAULT_BIT_DEPTH}."
        ),
    )

    parser.add_argument(
        "--low-percentile",
        type=float,
        default=DEFAULT_LOW_PERCENTILE,
        help=(
            "Input percentile mapped to black for high-bit-depth images. "
            f"Default: {DEFAULT_LOW_PERCENTILE}."
        ),
    )

    parser.add_argument(
        "--high-percentile",
        type=float,
        default=DEFAULT_HIGH_PERCENTILE,
        help=(
            "Input percentile mapped to white for high-bit-depth images. "
            f"Default: {DEFAULT_HIGH_PERCENTILE}."
        ),
    )

    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Skip writing the <name>.png preview alongside the .bin/.xml.",
    )

    return parser.parse_args()


def validate_arguments(
    args: argparse.Namespace,
) -> None:
    if not args.input.is_file():
        raise FileNotFoundError(
            f"Input file does not exist: {args.input}"
        )

    if not 0.0 <= args.low_percentile <= 100.0:
        raise ValueError(
            "Low percentile must be between 0 and 100."
        )

    if not 0.0 <= args.high_percentile <= 100.0:
        raise ValueError(
            "High percentile must be between 0 and 100."
        )

    if args.low_percentile >= args.high_percentile:
        raise ValueError(
            "Low percentile must be less than high percentile."
        )


def run(
    region_height: int = REGION_HEIGHT,
    region_top: int = REGION_TOP,
    fill: bool = False,
) -> int:
    """
    Parse args, prompt for metadata, and write the .bin/.xml/.png outputs using
    the given photo-strip geometry and fit mode. Variant scripts call this with
    a different region_height/region_top (and fill); main() uses the default
    ~6:17 letterboxed strip.
    """
    args = parse_arguments()

    try:
        validate_arguments(args)

        base, metadata = prompt_metadata()

        quantized = process_image(
            input_path=args.input,
            bit_depth=args.bit_depth,
            low_percentile=args.low_percentile,
            high_percentile=args.high_percentile,
            region_height=region_height,
            region_top=region_top,
            fill=fill,
        )

        write_outputs(
            quantized=quantized,
            output_dir=args.output_dir,
            base=base,
            metadata=metadata,
            save_preview=not args.no_preview,
        )

    except Exception as error:
        print(
            f"Error: {error}",
            file=sys.stderr,
        )
        return 1

    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
