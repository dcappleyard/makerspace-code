#pragma once

#include "booth_config.h"

#include <esp_camera.h>

// -----------------------------------------------------------------------------
// The OV2640 / OV3660 on the Sense expansion board, in two modes: a small,
// fast live view (LIVE_FRAMESIZE) and full-size captures. Everything runs in
// the Arduino loop() task.
// -----------------------------------------------------------------------------

// Starts the camera in live mode (no-op if it's already on). Image controls
// saved in NVS by ../xiao_s3_sense_webcam are re-applied. Takes a few hundred
// ms, including the WAKE_DISCARD_FRAMES warm-up.
bool cameraInit();
// Stops the camera (XCLK, DMA, frame buffers) for sleep.
void cameraOff();
bool cameraReady();
const char *sensorName();   // "OV2640", "OV3660", ... or "none"
framesize_t maxFramesize(); // the size captures use

// Switches to the largest size at CAPTURE_QUALITY and lets it settle
// (CAPTURE_DISCARD_FRAMES) -- done before the flash, so the flash only has to
// cover one fresh frame. cameraLiveMode() switches back.
void cameraCaptureMode();
void cameraLiveMode();
// A frame, after dropping `discardFirst` queued ones (with CAMERA_GRAB_LATEST
// the queued frame may predate whatever just changed, e.g. the flash). Hand it
// back with esp_camera_fb_return(). nullptr on failure.
camera_fb_t *grabFrame(int discardFirst);
