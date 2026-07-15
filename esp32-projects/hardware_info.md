# ESP32 hardware

Informal running notes on the physical boards/displays in use. Add a new section per device as hardware is added.

## XIAO ePaper DIY Kit EE03 — 10.3" monochrome ePaper display

- Board: Seeed XIAO ESP32-S3 (Sense variant)
- Display: 10.3" monochrome e-paper panel (EE03 kit)
- Product page: https://www.seeedstudio.com/XIAO-ePaper-DIY-Kit-EE03-for-10-3-Monochrome-ePaper-Display.html
- Used by: `ee03-text-test/` (buttons/text/graphics demo), `test_bw_image_eink/` (pushes a pre-converted grayscale photo to test the 16 gray levels), `wifi_counter_eink/` (browser-controlled counter over WiFi, partial e-paper refresh), `panorama_photo_frame_w_counter/` (battery-powered panorama photo frame — LittleFS image storage, deep sleep between refreshes, manually-set internal RTC, persistent counter; see its `DESIGN.md` for the full design)
- Notes: e-paper panels like this typically render more than 2 gray levels via dithering rather than pure black/white. `python-projects/grayscale_image_conversion/prepare_image.py` outputs 4-bit (16-level) dithered grayscale PNGs at 1872x1404 by default — that resolution lines up with this panel's native size, so it's likely the image-prep step feeding this display. Worth confirming and cross-referencing if either side changes.
- Battery/deep-sleep note (unconfirmed, flagged during `panorama_photo_frame_w_counter/` design): community reports (Seeed/Arduino forum threads) suggest the XIAO ESP32-S3 **Sense** variant's camera/mic expansion board can draw much more current in deep sleep than the base module's ~14µA spec unless it's explicitly powered down. Relevant to any future battery-powered project on this board, not just one — worth measuring directly and updating this note once confirmed either way.
