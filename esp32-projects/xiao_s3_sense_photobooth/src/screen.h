#pragma once

#include "booth_config.h"

#include <SPI.h>

// -----------------------------------------------------------------------------
// The round touch display: panel power, touch, and the few things the booth
// draws. Frames are composed in a 240x240 PSRAM sprite and pushed in one go,
// so overlays (countdown, prompt) don't flicker. All called from loop().
// -----------------------------------------------------------------------------

// Call BEFORE mountSd(): it brings up the SPI bus the SD card then shares
// (see screenSpi()). Leaves the panel off.
void setupScreen();

// The display's SPI instance (Seeed_GFX uses its own HSPI host on GPIO 7/8/9).
// The Sense SD slot is on the same three pins, so the SD card runs on this
// instance too -- two SPI hosts can't drive the same pins at once.
SPIClass &screenSpi();

void panelOn();  // wake the GC9A01 + backlight
void panelOff(); // backlight off + GC9A01 sleep

// --- Touch ---------------------------------------------------------------------
// True once per tap (see TOUCH_REARM_MS / TOUCH_LOCKOUT_MS).
bool takeTap();
// Where the finger is right now (panel coords, rotation applied); false if
// the controller reports no press.
bool readTouchPoint(int &x, int &y);
// Starts a TOUCH_LOCKOUT_MS window: call on every screen change.
void touchLockout();
// Light sleep until the touch INT goes low. Returns after waking, with the
// touch that woke it counted as a tap (takeTap() returns true once).
void sleepUntilTouch();

// --- Drawing -------------------------------------------------------------------
// Decodes a JPEG at the cheapest scale that still covers the circle,
// centre-crops it into the sprite and pushes it. `big` is drawn huge in the
// middle (countdown), `small` near the bottom (e.g. "A"); either may be null.
bool drawJpeg(const uint8_t *jpg, size_t len, int width, int height, const char *big, const char *small);
// "Capture?" with Yes (left half) / No (right half), over the last frame.
void drawPrompt(const char *question);
void flashWhite();
void blankScreen(); // black, straight to the panel (ends the flash)
void drawMessage(const char *line1, const char *line2 = nullptr);
