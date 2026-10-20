#pragma once

#include "cam_config.h"

#include <esp_camera.h>

// -----------------------------------------------------------------------------
// The OV2640 / OV3660 (/ OV5640) on the Sense expansion board. Settings are the
// esp32-camera sensor_t controls, saved to NVS on every change and re-applied
// at boot.
//
// Called from two esp_http_server tasks at once (the API on HTTP_PORT, the
// stream on STREAM_PORT). esp_camera_fb_get() is queue-based and safe for that;
// settings writes race a frame in flight at worst, which only garbles that one
// frame -- the same trade-off the core's CameraWebServer example makes.
// -----------------------------------------------------------------------------

bool cameraInit();
bool cameraReady();
const char *sensorName();     // "OV2640", "OV3660", ... or "none"
framesize_t maxFramesize();    // largest the UI may pick for this sensor

// {"framesize":8,"quality":12,"aec":1,...}: every control cameraSetControl()
// accepts, with its current value.
String cameraSettingsJson();

enum class SetResult
{
    Ok,
    UnknownControl,
    OutOfRange,
    SensorRefused, // the sensor driver doesn't implement it (returned non-zero)
};
SetResult cameraSetControl(const String &name, int value);

// Back to the boot defaults (sensor defaults + the per-sensor tweaks in
// camera.cpp), forgetting everything saved in NVS.
void cameraResetDefaults();

// A frame taken *now*: drops one queued frame first, which with
// CAMERA_GRAB_LATEST may predate the last settings change. Caller hands it back
// with esp_camera_fb_return(). nullptr on failure.
camera_fb_t *grabFreshFrame();
