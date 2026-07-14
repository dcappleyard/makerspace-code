#!/usr/bin/env python3

"""
Prepare an image for a fixed-size grayscale display.

Processing steps:
1. Apply EXIF orientation.
2. Properly convert high-bit-depth grayscale images to 8-bit grayscale.
3. Use percentile-based contrast mapping for high-bit-depth images.
4. Resize to the target width while preserving aspect ratio.
5. Vertically center the image on a white canvas.
6. Center-crop vertically if the resized image is too tall.
7. Quantize to a fixed grayscale bit depth using Floyd-Steinberg dithering.
8. Save as a PNG.

Default output:
    1872 x 1404 pixels
    4-bit grayscale (16 shades)
    0.5th to 99.5th percentile contrast mapping

Examples:
    python3 prepare_image.py input.tif output.png

    python3 prepare_image.py input.tif output.png \
        --width 1872 \
        --height 1404 \
        --bit-depth 4

    python3 prepare_image.py input.tif output.png \
        --low-percentile 1 \
        --high-percentile 99
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


DEFAULT_WIDTH = 1872
DEFAULT_HEIGHT = 1404
DEFAULT_BIT_DEPTH = 4
DEFAULT_LOW_PERCENTILE = 0.5
DEFAULT_HIGH_PERCENTILE = 99.5


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


def center_on_canvas(
    image: Image.Image,
    width: int,
    height: int,
) -> Image.Image:
    """
    Vertically center the image on a white canvas.

    If the resized image is taller than the canvas, it is center-cropped
    vertically to the target height.
    """
    if image.width != width:
        raise ValueError(
            f"Image width is {image.width}, "
            f"but canvas width is {width}."
        )

    if image.height > height:
        crop_top = (image.height - height) // 2
        crop_bottom = crop_top + height

        print(
            f"Image is too tall; center-cropping rows "
            f"{crop_top} through {crop_bottom}."
        )

        return image.crop(
            (0, crop_top, width, crop_bottom)
        )

    canvas = Image.new(
        "L",
        (width, height),
        color=255,
    )

    paste_y = (height - image.height) // 2

    print(
        f"Vertically centering image at y={paste_y} "
        f"with white padding."
    )

    canvas.paste(image, (0, paste_y))

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


def process_image(
    input_path: Path,
    output_path: Path,
    width: int,
    height: int,
    bit_depth: int,
    low_percentile: float,
    high_percentile: float,
) -> None:
    """
    Process and save one image.
    """
    with Image.open(input_path) as source:
        source.load()
        source = ImageOps.exif_transpose(source)

        grayscale = convert_to_8bit_grayscale(
            source,
            low_percentile=low_percentile,
            high_percentile=high_percentile,
        )

        resized = resize_to_width(
            grayscale,
            target_width=width,
        )

        canvas = center_on_canvas(
            resized,
            width=width,
            height=height,
        )

        output = quantize_grayscale(
            canvas,
            bit_depth=bit_depth,
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.save(
            output_path,
            format="PNG",
            optimize=True,
            bits=bit_depth,
        )

    print(
        f"Saved {width} x {height}, "
        f"{bit_depth}-bit grayscale PNG to:"
    )
    print(output_path)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resize an image by width, vertically center or crop it, "
            "and save it as a dithered grayscale PNG."
        )
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Input image path.",
    )

    parser.add_argument(
        "output",
        type=Path,
        help="Output PNG path.",
    )

    parser.add_argument(
        "--width",
        type=int,
        default=DEFAULT_WIDTH,
        help=(
            f"Final image width. "
            f"Default: {DEFAULT_WIDTH}."
        ),
    )

    parser.add_argument(
        "--height",
        type=int,
        default=DEFAULT_HEIGHT,
        help=(
            f"Final image height. "
            f"Default: {DEFAULT_HEIGHT}."
        ),
    )

    parser.add_argument(
        "--bit-depth",
        type=int,
        default=DEFAULT_BIT_DEPTH,
        choices=(1, 2, 4, 8),
        help=(
            "Output grayscale bit depth. "
            "Supported values: 1, 2, 4, or 8. "
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

    return parser.parse_args()


def validate_arguments(
    args: argparse.Namespace,
) -> None:
    if args.width <= 0:
        raise ValueError(
            "Width must be greater than zero."
        )

    if args.height <= 0:
        raise ValueError(
            "Height must be greater than zero."
        )

    if not args.input.is_file():
        raise FileNotFoundError(
            f"Input file does not exist: {args.input}"
        )

    if args.output.suffix.lower() != ".png":
        raise ValueError(
            "The output filename must end in .png."
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


def main() -> int:
    args = parse_arguments()

    try:
        validate_arguments(args)

        process_image(
            input_path=args.input,
            output_path=args.output,
            width=args.width,
            height=args.height,
            bit_depth=args.bit_depth,
            low_percentile=args.low_percentile,
            high_percentile=args.high_percentile,
        )

    except Exception as error:
        print(
            f"Error: {error}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())