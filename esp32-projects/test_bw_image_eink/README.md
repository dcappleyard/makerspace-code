# test_bw_image_eink

PlatformIO project that pushes pre-converted grayscale test images to the
XIAO ePaper DIY Kit EE03 (10.3" panel) to see how its 16 gray levels
actually render. Same board/display as `../ee03-text-test` -- see
`../hardware_info.md`. Confirmed working on the physical panel with a single
image; now embeds two and switches between them with the kit's buttons.

## Workflow

1. Produce source images with `python-projects/grayscale_image_conversion/prepare_image.py`
   (4-bit depth, default 1872x1404 -- matches this panel's native resolution).
   `~/Pictures/test_1.png` and `~/Pictures/test_2.png` are already in that
   format.
2. Generate the firmware image header (gitignored, regenerate as needed).
   Pass images in the order you want them addressable -- the Nth image maps
   to `IMAGES[N-1]` in `main.cpp`, and the first one is what's shown at boot:
   ```
   pip install -r tools/requirements.txt   # first time only
   python3 tools/convert_image.py ~/Pictures/test_1.png ~/Pictures/test_2.png
   ```
3. Build/upload with PlatformIO as usual (`pio run -t upload`, or the VS Code
   PlatformIO extension).

`main.cpp` mirrors the flow in `../ee03-text-test/src/main.cpp` and the
vendored `Seeed_GFX` gray-level examples: `epaper.begin()` ->
`fillScreen`/`update()` to clear -> `initGrayMode(GRAY_LEVEL16)` ->
`pushImage()` the packed image -> `update()` to flush it to the panel.
Buttons 1 and 2 (same pins as `ee03-text-test`: GPIO 2 and 3, the kit's
built-in buttons) switch to image 1 and image 2 respectively, skipping the
push/update if that image is already showing.

## Flash budget

Both images are embedded as compiled-in arrays, which puts them in the same
app partition as the firmware code (`app0`, 0x330000 = 3,342,336 bytes per
`~/.platformio/packages/framework-arduinoespressif32/tools/partitions/default_8MB.csv`,
the board's default 8MB partition scheme). Two 1872x1404 4bpp images pack to
~1.25MB each (~2.5MB combined); a build with both linked in comes to
**2,990,181 bytes -- 89.5% of the 3.34MB app partition**, confirmed via
`pio run`. That leaves about 350KB of headroom, which is enough for minor
code growth but not a third image at this resolution -- a third image would
need switching to `board_build.embed_files` (link the packed `.bin`
directly instead of inlining as C source) or reading from SPIFFS/LittleFS at
runtime instead of compiling images in.

## Verified vs. unverified

Confirmed on the physical panel with a single image. The two-image/button
addition hasn't been tested on hardware yet -- the `pushImage`/`initGrayMode`
call pattern is unchanged from the working single-image version, so the main
new things to verify are the button wiring/debounce and that switching
between images doesn't need a full `fillScreen` clear first (currently it
doesn't do one, matching how `ee03-text-test`'s page-switching works).

- **Verified**: `EPaper` extends `TFT_eSprite`, which hides `TFT_eSPI`'s
  other `pushImage` overloads -- only
  `pushImage(x, y, w, h, uint16_t *data, uint8_t sbpp = 0)` is actually
  reachable on an `epaper` object. Its `_bpp == 4` branch
  (`Extensions/Sprite.cpp`) treats `data` as raw packed nibbles regardless of
  the `uint16_t*` parameter type, high nibble = first pixel, low nibble =
  second -- matching `tools/convert_image.py`'s packing. The 10.3" panel's
  driver (`TFT_Drivers/ED103TC2_Defines.h`) defines
  `USE_MUTIGRAY_EPAPER`/`GRAY_LEVEL16`. This whole path rendered correctly on
  the actual display with `test_2.png`.
- `src/image_data.h` is a generated ~16MB text header (hex byte literals) for
  two images -- fine for a one-off test but slow to compile repeatedly; if
  that becomes annoying, see the flash-budget note above about
  `board_build.embed_files`.
