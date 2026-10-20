#pragma once

#include "cam_config.h"

#include <SPI.h>

// -----------------------------------------------------------------------------
// The round touch display: off normally; a tap wakes it into a live camera
// preview, a second tap asks "Turn screen off?" (Yes / No), and it also turns
// itself off after SCREEN_IDLE_OFF_MS without a touch.
//
// Everything here runs in the Arduino loop() task.
// -----------------------------------------------------------------------------

// Call after cameraInit() and BEFORE mountSd(): it brings up the SPI bus that
// the SD card then shares (see screenSpi()).
void setupScreen();
void serviceScreen();
bool screenOn();

// The display's SPI instance (Seeed_GFX uses its own HSPI host on GPIO 7/8/9).
// The Sense SD slot sits on the same three pins, so the SD card must run on
// this instance too -- two SPI hosts can't drive the same pins at once.
// SPIClass::beginTransaction()'s lock serializes the two across tasks.
SPIClass &screenSpi();
